"""Batched brain simulation: every fly of one sex and fidelity in one step call (BRAIN-R-050).

One step follows Brian2's schedule for the reference model, so reference mode reproduces it:

1. refractory check (``step - last_spike >= refractory steps``);
2. exact integration of membrane and synapse for non-refractory neurons;
3. threshold (spiking units only);
4. synaptic delivery of the spikes emitted ``delay`` steps ago, held graded coupling, sensory
   Poisson drive and background noise;
5. reset of the neurons that spiked, which are then queued for delivery.

The membrane potential is stored relative to each neuron's rest (``u = v - v_rest``).

Determinism (BRAIN-R-054, -055):

- synaptic input is summed as int64 fixed point; integer addition is associative, so the sum is
  the same in any order and one fly's input never depends on its batch;
- every per-neuron float operation is a single elementwise op (exact IEEE arithmetic);
- random numbers are counter-based per (fly, stream, step, neuron) (`flycolony.brain.rng`), so
  drawing them in blocks of steps gives the same events as drawing them step by step.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
import torch

from flycolony.brain import rng
from flycolony.brain.params import MS_PER_S, NeuronParams, StepConstants, membrane_propagator
from flycolony.brain.topology import Topology, expand_rows

_NEVER = -(1 << 40)  # registry-ok: "never spiked" step marker, far below any reachable step
_BLOCK_ELEMENTS = 1 << 24  # registry-ok: memory bound (elements) for one block of drive draws


class BrainInputError(ValueError):
    """External input aimed at a neuron that may not receive it (BRAIN-R-016)."""


@dataclass
class FlyBrainSpec:
    """Everything that individualises one fly's brain (BRAIN-R-001, -003).

    Built by 007 from the genome and developmental noise; arrays are per neuron of the template.
    `None` means the template default (gain 1, offset 0).
    """

    fly_id: str
    seed: int
    pre_gain: np.ndarray | None = None
    post_gain: np.ndarray | None = None
    v_thresh_offset: np.ndarray | None = None
    v_rest_offset: np.ndarray | None = None


@dataclass
class BrainEvent:
    kind: str
    fly_id: str
    step: int
    detail: dict = field(default_factory=dict)


@dataclass
class PlasticSet:
    """Shared description of a plastic synapse set (BRAIN-R-004): which CSR edges it covers."""

    name: str
    edges: torch.Tensor  # int64 [P], CSR edge ids


@dataclass
class _Events:
    """Pre-drawn input events for steps [start, end): flat fly*n + neuron ids grouped by step."""

    start: int
    end: int
    flat: torch.Tensor
    offsets: np.ndarray  # host int64 [end - start + 1]

    def at(self, t: int) -> torch.Tensor:
        k = t - self.start
        return self.flat[int(self.offsets[k]) : int(self.offsets[k + 1])]


def _group_by_step(times: torch.Tensor, flat: torch.Tensor, start: int, end: int) -> _Events:
    order = torch.argsort(times, stable=True)
    times, flat = times[order], flat[order]
    counts = torch.bincount(times - start, minlength=end - start)
    offsets = np.zeros(end - start + 1, dtype=np.int64)
    np.cumsum(counts.cpu().numpy(), out=offsets[1:])
    return _Events(start, end, flat, offsets)


class BrainBatch:
    """State of B brains sharing one Topology. Flies are addressed by id; slots are internal."""

    STATE_FIELDS = (
        "u", "g", "last", "next_noise", "theta", "vrest", "pre", "post", "ref", "graded_in",
        "rates", "plastic", "keys", "spike_window", "sense_rate", "photo_in",
    )  # fmt: skip

    def __init__(
        self,
        topo: Topology,
        params: NeuronParams,
        dt: float,
        *,
        plastic_sets: Sequence[PlasticSet] = (),
        output_groups: dict[str, np.ndarray] | None = None,
    ):
        self.topo = topo
        self.params = params
        self.k = StepConstants.build(params, dt)
        self.dt = dt
        self.device = topo.device
        self.n = topo.n
        self.step_count = 0
        self.fly_ids: list[str] = []
        self.taps: list[Callable] = []
        self.modulation = None  # set by flycolony.brain.modulation.Modulation.attach
        n, dev = self.n, self.device
        f32 = torch.float32
        self._scale = float(1 << params.fixed_point_bits)
        self._salt = rng.neuron_salt(n, dev)
        spiking = topo.spiking
        e_m = np.where(spiking.cpu().numpy(), self.k.e_m, self.k.e_graded)
        c_m = np.where(spiking.cpu().numpy(), self.k.c_m, self.k.c_graded)
        if topo.graded_tau is not None:  # per-type graded time constants (flyvis)
            own = ~np.isnan(topo.graded_tau)
            for tau in np.unique(topo.graded_tau[own]):
                e, c, _ = membrane_propagator(float(tau), params.tau_syn, dt)
                sel = topo.graded_tau == tau
                e_m[sel], c_m[sel] = e, c
        self.e_m = torch.from_numpy(e_m).to(device=dev, dtype=f32)
        self.c_m = torch.from_numpy(c_m).to(device=dev, dtype=f32)
        self.has_graded = topo.graded_edges is not None
        # Plastic sets: CSR edge -> slot in the per-fly plastic block (-1 = shared weight).
        self.plastic_sets = list(plastic_sets)
        self.n_plastic = sum(int(s.edges.numel()) for s in self.plastic_sets)
        self.slot_of_edge = None
        if self.n_plastic:
            slot = torch.full((topo.n_edges,), -1, dtype=torch.int64, device=dev)
            offset = 0
            for s in self.plastic_sets:
                m = int(s.edges.numel())
                slot[s.edges] = torch.arange(offset, offset + m, device=dev)
                offset += m
            self.slot_of_edge = slot
        # Output groups (BRAIN-R-017).
        groups = output_groups or {}
        self.group_names = sorted(groups)
        group_of = np.full(n, -1, dtype=np.int64)
        sizes = []
        for gi, name in enumerate(self.group_names):
            ids = np.asarray(groups[name], dtype=np.int64)
            if (group_of[ids] >= 0).any():
                raise ValueError(f"output group {name!r} overlaps another group")
            group_of[ids] = gi
            sizes.append(len(ids))
        self.n_groups = len(self.group_names)
        self.group_of = torch.from_numpy(group_of).to(dev)
        self._rate_gain = (
            torch.tensor(sizes, dtype=f32, device=dev).reciprocal()
            * (MS_PER_S / dt)
            * (1.0 - self.k.rate_decay)
        )
        self._alloc(0)
        self._acc = torch.zeros(0, dtype=torch.int64, device=dev)
        # Delivery queue: spikes emitted at step s are delivered at step s + delay.
        self.queue: list[torch.Tensor] = [self._empty() for _ in range(max(1, self.k.delay_steps))]
        self._drive_events: _Events | None = None
        self._noise_events: _Events | None = None
        # Closed-loop sensory input (004 §2): none until attach_senses().
        self.sense_ids = self._empty()
        self.photo_ids = self._empty()

    # --- state ---------------------------------------------------------------------------------

    def _empty(self) -> torch.Tensor:
        return torch.empty(0, dtype=torch.int64, device=self.device)

    def _alloc(self, b: int) -> None:
        n, dev, f32 = self.n, self.device, torch.float32
        self.u = torch.zeros(b, n, dtype=f32, device=dev)
        self.g = torch.zeros(b, n, dtype=f32, device=dev)
        self.last = torch.full((b, n), _NEVER, dtype=torch.int64, device=dev)
        self.next_noise = torch.full((b, n), _NEVER, dtype=torch.int64, device=dev)
        self.theta = torch.zeros(b, n, dtype=f32, device=dev)
        self.vrest = torch.zeros(b, n, dtype=f32, device=dev)
        self.pre = torch.ones(b, n, dtype=f32, device=dev)
        self.post = torch.ones(b, n, dtype=f32, device=dev)
        self.ref = torch.full((b, n), self.k.ref_steps, dtype=torch.int32, device=dev)
        self.graded_in = torch.zeros(b, n if self.has_graded else 0, dtype=f32, device=dev)
        self.rates = torch.zeros(b, self.n_groups, dtype=f32, device=dev)
        self.plastic = torch.zeros(b, self.n_plastic, dtype=f32, device=dev)
        self.keys = torch.zeros(b, dtype=torch.int64, device=dev)
        self.spike_window = torch.zeros(b, dtype=torch.int64, device=dev)
        n_s = int(self.sense_ids.numel()) if hasattr(self, "sense_ids") else 0
        n_p = int(self.photo_ids.numel()) if hasattr(self, "photo_ids") else 0
        self.sense_rate = torch.zeros(b, n_s, dtype=f32, device=dev)
        self.photo_in = torch.zeros(b, n_p, dtype=f32, device=dev)
        self.drive: dict[str, tuple[torch.Tensor, torch.Tensor]] = {}
        self._drive_flat = self._empty()
        self._drive_p = torch.empty(0, dtype=torch.float64, device=dev)

    @property
    def batch_size(self) -> int:
        return len(self.fly_ids)

    def slot(self, fly_id: str) -> int:
        try:
            return self.fly_ids.index(fly_id)
        except ValueError:
            raise KeyError(f"fly {fly_id!r} is not in this batch") from None

    def potential(self, fly_id: str) -> torch.Tensor:
        """Membrane potential v (mV) of every neuron of one fly (a copy)."""
        b = self.slot(fly_id)
        return self.u[b] + self.vrest[b]

    # --- adding and removing flies (BRAIN-R-005) -------------------------------------------------

    def add(self, spec: FlyBrainSpec) -> None:
        """Add a brain built from its template + spec only (BRAIN-R-001). Others are untouched."""
        if spec.fly_id in self.fly_ids:
            raise ValueError(f"fly {spec.fly_id!r} already in batch")
        n, dev, p = self.n, self.device, self.params

        def vec(a: np.ndarray | None, default: float) -> torch.Tensor:
            if a is None:
                return torch.full((n,), default, dtype=torch.float32, device=dev)
            a = np.asarray(a, dtype=np.float32)
            if a.shape != (n,):
                raise ValueError(f"per-neuron array has shape {a.shape}, expected ({n},)")
            return torch.from_numpy(a).to(dev)

        vrest = vec(spec.v_rest_offset, 0.0) + p.v_rest
        theta = vec(spec.v_thresh_offset, 0.0) + p.v_thresh - vrest
        theta = torch.where(self.topo.spiking, theta, math.inf)
        key = rng.fly_key(spec.seed)
        row = {
            "u": torch.zeros(n, device=dev),
            "g": torch.zeros(n, device=dev),
            "last": torch.full((n,), _NEVER, dtype=torch.int64, device=dev),
            "next_noise": self._first_noise(key),
            "theta": theta,
            "vrest": vrest,
            "pre": vec(spec.pre_gain, 1.0),
            "post": vec(spec.post_gain, 1.0),
            "ref": torch.full((n,), self.k.ref_steps, dtype=torch.int32, device=dev),
            "graded_in": torch.zeros(n if self.has_graded else 0, device=dev),
            "rates": torch.zeros(self.n_groups, device=dev),
            "plastic": self._shared_plastic_weights(),
            "keys": torch.tensor(key, dtype=torch.int64, device=dev),
            "spike_window": torch.zeros((), dtype=torch.int64, device=dev),
            "sense_rate": torch.zeros(self.sense_ids.numel(), device=dev),
            "photo_in": torch.zeros(self.photo_ids.numel(), device=dev),
        }
        b = self.batch_size
        for name, value in row.items():
            setattr(self, name, torch.cat([getattr(self, name), value.unsqueeze(0)]))
        self.fly_ids.append(spec.fly_id)
        if self.sense_ids.numel():
            self.ref[b, self.sense_ids] = self.k.driven_ref_steps
        self._acc = torch.zeros(self.batch_size * n, dtype=torch.int64, device=dev)
        self._drive_events = None
        if self._noise_events is not None:
            # Draw the new fly's background events for the rest of the current block and merge.
            ev = self._noise_events
            t, flat = self._draw_noise(
                self.next_noise[b : b + 1], self.keys[b : b + 1], self.step_count, ev.end
            )
            old_t, old_f = self._unpack(ev)
            self._noise_events = _group_by_step(
                torch.cat([old_t, t]), torch.cat([old_f, flat + b * n]), ev.start, ev.end
            )
        if self.modulation is not None:
            self.modulation.on_add()

    def remove(self, fly_id: str) -> None:
        b = self.slot(fly_id)
        old_b = self.batch_size
        keep = torch.tensor(
            [i for i in range(old_b) if i != b], dtype=torch.int64, device=self.device
        )
        for name in self.STATE_FIELDS:
            setattr(self, name, getattr(self, name).index_select(0, keep))
        self.drive.pop(fly_id, None)
        self.fly_ids.pop(b)
        remap = torch.full((old_b,), -1, dtype=torch.int64, device=self.device)
        remap[keep] = torch.arange(keep.numel(), device=self.device)
        self.queue = [self._remap(q, remap)[1] for q in self.queue]
        if self._noise_events is not None:
            ev = self._noise_events
            t, f = self._unpack(ev)
            ok, nf = self._remap(f, remap)
            self._noise_events = _group_by_step(t[ok], nf, ev.start, ev.end)
        self._acc = torch.zeros(self.batch_size * self.n, dtype=torch.int64, device=self.device)
        self._rebuild_drive()
        if self.modulation is not None:
            self.modulation.on_remove(keep)

    def _remap(self, flat: torch.Tensor, remap: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        nf = remap[flat // self.n]
        ok = nf >= 0
        return ok, nf[ok] * self.n + flat[ok] % self.n

    def _unpack(self, ev: _Events) -> tuple[torch.Tensor, torch.Tensor]:
        counts = torch.from_numpy(np.diff(ev.offsets)).to(self.device)
        times = torch.repeat_interleave(
            torch.arange(ev.start, ev.end, device=self.device), counts, output_size=ev.flat.numel()
        )
        return times, ev.flat

    def _shared_plastic_weights(self) -> torch.Tensor:
        if not self.n_plastic:
            return torch.zeros(0, device=self.device)
        edges = torch.cat([s.edges for s in self.plastic_sets])
        return self.topo.weight[edges].float()

    # --- random input ---------------------------------------------------------------------------------

    def _wait(self, u: torch.Tensor) -> torch.Tensor:
        """Geometric waiting time (>= 0 steps) of a Bernoulli(p_noise)-per-step process."""
        return torch.floor(torch.log(u) / math.log1p(-self.k.p_noise)).to(torch.int64)

    def _first_noise(self, key: int) -> torch.Tensor:
        if self.k.p_noise <= 0:
            return torch.full((self.n,), _NEVER, dtype=torch.int64, device=self.device)
        sk = rng.step_keys(
            torch.tensor([key], device=self.device), rng.STREAM_NOISE_INIT, self.step_count
        )
        return self.step_count + self._wait(rng.uniform(sk.expand(self.n), self._salt))

    def _draw_noise(
        self, next_noise: torch.Tensor, keys: torch.Tensor, start: int, end: int
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Background events in [start, end) for the rows of `next_noise` (updated in place to the
        first event at or after `end`). Each wait is drawn from (fly, event step, neuron) only."""
        n = self.n
        nxt = next_noise.view(-1)
        idx = (nxt < end).nonzero().squeeze(1)
        cur = nxt[idx]
        times, flats = [], []
        while idx.numel():
            times.append(cur)
            flats.append(idx)
            sk = rng.step_keys(keys[idx // n], rng.STREAM_NOISE, cur)
            cur = cur + self._wait(rng.uniform(sk, self._salt[idx % n])) + 1
            done = cur >= end
            nxt[idx[done]] = cur[done]
            idx, cur = idx[~done], cur[~done]
        if not times:
            return self._empty(), self._empty()
        return torch.cat(times), torch.cat(flats)

    def _noise_at(self, t: int) -> torch.Tensor:
        ev = self._noise_events
        if ev is None or t >= ev.end:
            end = t + self.params.event_block_steps
            times, flat = self._draw_noise(self.next_noise, self.keys, t, end)
            ev = self._noise_events = _group_by_step(times, flat, t, end)
        return ev.at(t)

    def _drive_at(self, t: int) -> torch.Tensor:
        d = self._drive_flat.numel()
        if d == 0:
            return self._empty()
        ev = self._drive_events
        if ev is None or t >= ev.end:
            steps = max(1, min(self.params.event_block_steps, _BLOCK_ELEMENTS // d))
            grid = torch.arange(t, t + steps, device=self.device).unsqueeze(1)
            sk = rng.step_keys(
                self.keys[self._drive_flat // self.n].unsqueeze(0), rng.STREAM_DRIVE, grid
            )
            u = rng.uniform(sk, self._salt[self._drive_flat % self.n].unsqueeze(0))
            k, j = (u < self._drive_p).nonzero(as_tuple=True)
            ev = self._drive_events = _group_by_step(k + t, self._drive_flat[j], t, t + steps)
        return ev.at(t)

    # --- external input (BRAIN-R-016) --------------------------------------------------------------

    def set_drive(self, fly_id: str, neuron_ids: Sequence[int] | np.ndarray, rates_hz) -> None:
        """Poisson drive on sensory neurons only, from 004 (or a validation assay).

        Replaces the fly's previous drive. Driven neurons use the registry's driven refractory
        period, as in the reference model.
        """
        b = self.slot(fly_id)
        ids = torch.as_tensor(np.asarray(neuron_ids, dtype=np.int64), device=self.device)
        if ids.numel() and not bool(self.topo.sensory[ids].all()):
            bad = ids[~self.topo.sensory[ids]][:5].tolist()
            raise BrainInputError(f"drive only reaches sensory neurons; not sensory: {bad}")
        rates = torch.as_tensor(rates_hz, dtype=torch.float64, device=self.device).expand(ids.shape)
        old = self.drive.pop(fly_id, None)
        if old is not None:
            self.ref[b, old[0]] = self.k.ref_steps
        if ids.numel():
            self.drive[fly_id] = (ids, rates * self.k.dt / MS_PER_S)
            self.ref[b, ids] = self.k.driven_ref_steps
        self._rebuild_drive()

    def _rebuild_drive(self) -> None:
        flats, ps = [], []
        for b, fid in enumerate(self.fly_ids):
            if fid in self.drive:
                ids, p = self.drive[fid]
                flats.append(ids + b * self.n)
                ps.append(p)
        self._drive_flat = torch.cat(flats) if flats else self._empty()
        self._drive_p = (
            torch.cat(ps) if ps else torch.empty(0, dtype=torch.float64, device=self.device)
        )
        self._drive_events = None

    # --- closed-loop sensory input (004 §2) -----------------------------------------------------------

    def attach_senses(self, sensory_ids: np.ndarray, photo_ids: np.ndarray) -> None:
        """Register the per-template sensory layout once.

        `sensory_ids` are Poisson-driven sensory neurons; each step draws one Bernoulli event per
        neuron from its current rate (`sense_rate`, Hz) with the counter-based RNG, so input is
        device- and batch-independent. `photo_ids` are photoreceptor units; `photo_in` (mV per
        step) is added to their synaptic input like the graded coupling. No neuron state is ever
        written directly.
        """
        dev = self.device
        s = torch.as_tensor(np.asarray(sensory_ids, dtype=np.int64), device=dev)
        ph = torch.as_tensor(np.asarray(photo_ids, dtype=np.int64), device=dev)
        for ids, what in ((s, "sensory"), (ph, "photoreceptor")):
            if ids.numel() and not bool(self.topo.sensory[ids].all()):
                bad = ids[~self.topo.sensory[ids]][:5].tolist()
                raise BrainInputError(f"{what} input only reaches sensory neurons; not: {bad}")
        if torch.isin(s, ph).any():
            raise BrainInputError("a neuron cannot be both rate-driven and photoreceptor input")
        driven = torch.cat([ids for ids, _ in self.drive.values()]) if self.drive else s[:0]
        if torch.isin(s, driven).any() or torch.isin(ph, driven).any():
            raise BrainInputError("sensory layout overlaps an existing set_drive() drive")
        self.sense_ids, self.photo_ids = s, ph
        b = self.batch_size
        self.sense_rate = torch.zeros(b, s.numel(), dtype=torch.float32, device=dev)
        self.photo_in = torch.zeros(b, ph.numel(), dtype=torch.float32, device=dev)
        if b and s.numel():
            self.ref[:, s] = self.k.driven_ref_steps
        self._sense_salt = self._salt[s]

    def set_senses(self, rates_hz: torch.Tensor, photo_mv: torch.Tensor | None = None) -> None:
        """Replace all flies' sensory rates [B, n_sensory] (Hz) and photoreceptor input [B, n_photo]."""
        if tuple(rates_hz.shape) != tuple(self.sense_rate.shape):
            raise BrainInputError(
                f"sensory rates have shape {tuple(rates_hz.shape)}, "
                f"expected {tuple(self.sense_rate.shape)}"
            )
        self.sense_rate = rates_hz.to(device=self.device, dtype=torch.float32).clamp_min(0)
        if photo_mv is not None:
            if tuple(photo_mv.shape) != tuple(self.photo_in.shape):
                raise BrainInputError("photoreceptor input has the wrong shape")
            self.photo_in = photo_mv.to(device=self.device, dtype=torch.float32)

    def _sense_at(self, t: int) -> torch.Tensor:
        """Flat indices of sensory neurons that receive a Poisson input event at step t."""
        b, m = self.sense_rate.shape
        if b == 0 or m == 0:
            return self._empty()
        sk = rng.step_keys(self.keys, rng.STREAM_SENSE, t).unsqueeze(1)  # [B, 1]
        u = rng.uniform(sk, self._sense_salt.unsqueeze(0))  # [B, M]
        p = self.sense_rate.double() * (self.k.dt / MS_PER_S)
        fb, j = (u < p).nonzero(as_tuple=True)
        return fb * self.n + self.sense_ids[j]

    # --- stepping ------------------------------------------------------------------------------------

    def step(self) -> list[BrainEvent]:
        """Advance every brain by one dt. Returns engine events (e.g. brain.runaway)."""
        t = self.step_count
        k = self.k
        if self.modulation is not None:
            self.modulation.before_step(t)
        # 1-2. refractory check and exact integration.
        nr = (t - self.last) >= self.ref
        x = self.u * self.e_m
        x.add_(self.g * self.c_m)
        self.u = torch.where(nr, x, self.u)
        self.g = torch.where(nr, self.g * k.e_s, self.g)
        # 3. threshold (theta is +inf for graded units).
        spk = (self.u > self.theta) & nr
        spikes = spk.view(-1).nonzero().squeeze(1)
        # Neurons that are refractory or just spiked ignore input this step: Brian2 makes every
        # write to an "(unless refractory)" variable conditional on not_refractory, and only
        # the reset is exempt.
        self._open = (nr ^ spk).view(-1)
        # 4. delivery, graded coupling, drive and noise.
        slot = t % len(self.queue)
        if self.has_graded:
            if t % k.graded_every == 0:
                self._update_graded()
            self.g = torch.where(self._open.view_as(nr), self.g + self.graded_in, self.g)
        self._deliver(self.queue[slot] if k.delay_steps else spikes)
        if self.photo_in.numel():
            gv = self.g.view(-1)
            flat = (
                torch.arange(self.batch_size, device=self.device).unsqueeze(1) * self.n
                + self.photo_ids.unsqueeze(0)
            ).reshape(-1)
            gv[flat] = torch.where(self._open[flat], gv[flat] + self.photo_in.reshape(-1), gv[flat])
        uf = self.u.view(-1)
        hit = self._drive_at(t)
        sense = self._sense_at(t)
        if sense.numel():
            sense = sense[self._open[sense]]
            uf[sense] = uf[sense] + self.params.w_poisson
        if hit.numel():
            hit = hit[self._open[hit]]
            uf[hit] = uf[hit] + self.params.w_poisson
        if k.p_noise > 0:
            ev = self._noise_at(t)
            if ev.numel():
                ev = ev[self._open[ev]]
                uf[ev] = uf[ev] + self.params.noise_w
        # 5. reset and queue.
        uf[spikes] = self.params.v_reset - self.vrest.view(-1)[spikes]
        self.g.view(-1)[spikes] = 0.0
        self.last.view(-1)[spikes] = t
        if k.delay_steps:
            self.queue[slot] = spikes
        events = self._after_spikes(t, spikes)
        for tap in self.taps:
            tap(self, t, spikes)
        self.step_count = t + 1
        return events

    def run(self, steps: int) -> list[BrainEvent]:
        events: list[BrainEvent] = []
        for _ in range(steps):
            events += self.step()
        return events

    def _deliver(self, flat: torch.Tensor) -> None:
        """Event-driven propagation of spikes (flat fly*n + neuron indices) into g (BRAIN-R-051)."""
        if flat.numel() == 0:
            return
        n = self.n
        edge, which = expand_rows(self.topo.indptr, flat % n)
        if edge.numel() == 0:
            return
        fe = (flat // n)[which]
        w = self.topo.weight[edge].float()
        if self.slot_of_edge is not None:
            s = self.slot_of_edge[edge]
            m = s >= 0
            w = torch.where(m, self.plastic.view(-1)[fe * self.n_plastic + s.clamp_min(0)], w)
        w = w * self.pre.view(-1)[flat][which]
        self._accumulate(fe * n + self.topo.indices[edge], w)

    def _accumulate(self, target: torch.Tensor, value_mv: torch.Tensor) -> None:
        """g[target] += post_gain * sum(value) for receptive targets, summed exactly in int64
        fixed point. Duplicate targets all write the same final value, so the scattered write is
        deterministic.
        """
        q = torch.round(value_mv * self._scale).to(torch.int64)
        self._acc.index_add_(0, target, q)
        add = self._acc[target].to(torch.float32) / self._scale * self.post.view(-1)[target]
        if self.modulation is not None:
            add = add * self.modulation.gain.view(-1)[target]
        gf = self.g.view(-1)
        gf[target] = torch.where(self._open[target], gf[target] + add, gf[target])
        self._acc[target] = 0

    def _update_graded(self) -> None:
        """Recompute the held graded→all coupling (BRAIN-R-015): rate-equivalent output × weight."""
        p, topo, n, b = self.params, self.topo, self.n, self.batch_size
        pre = topo.graded_pre
        # Output in Hz: gain × (v - v_thresh_graded), v = u + v_rest.
        v = self.u[:, pre] + self.vrest[:, pre]
        rate = ((v - p.graded_v_thresh) * p.graded_gain).clamp_(0.0, p.graded_max_rate)
        # Per step: weight [mV/spike] × rate [Hz] × dt [s], i.e. as if spiking at `rate`.
        w = topo.weight[topo.graded_edges].float() * (self.k.dt / MS_PER_S)
        q = torch.round(rate * w * self.pre[:, pre] * self._scale).to(torch.int64)
        tgt = torch.arange(b, device=self.device).unsqueeze(1) * n + topo.indices[topo.graded_edges]
        acc = torch.zeros(b * n, dtype=torch.int64, device=self.device)
        acc.index_add_(0, tgt.reshape(-1), q.reshape(-1))
        held = (acc.to(torch.float32) / self._scale).view(b, n) * self.post
        if self.modulation is not None:
            held = held * self.modulation.gain
        self.graded_in = held

    def _after_spikes(self, t: int, spikes: torch.Tensor) -> list[BrainEvent]:
        """Output rates, modulator release and the runaway watchdog. Never alters the brain."""
        b = self.batch_size
        f = spikes // self.n
        if self.n_groups:
            grp = self.group_of[spikes % self.n]
            m = grp >= 0
            counts = torch.bincount(f[m] * self.n_groups + grp[m], minlength=b * self.n_groups)
            self.rates = (
                self.rates * self.k.rate_decay + counts.view(b, self.n_groups) * self._rate_gain
            )
        if self.modulation is not None:
            self.modulation.release(spikes)
        self.spike_window += torch.bincount(f, minlength=b)
        events: list[BrainEvent] = []
        if (t + 1) % self.k.safety_steps == 0:
            window_s = self.k.safety_steps * self.k.dt / MS_PER_S
            rate = self.spike_window.to(torch.float64) / (self.n * window_s)
            for s in (rate > self.params.max_population_rate).nonzero().squeeze(1).tolist():
                events.append(
                    BrainEvent(
                        "brain.runaway",
                        self.fly_ids[s],
                        t,
                        {"population_rate_hz": float(rate[s]), "action": "checkpoint"},
                    )
                )
            self.spike_window.zero_()
        return events

    # --- outputs (BRAIN-R-017) ---------------------------------------------------------------------

    def group_rates(self, fly_id: str) -> dict[str, float]:
        """Filtered rates (Hz per neuron) of the DN/motor/neurosecretory groups for 005/006."""
        r = self.rates[self.slot(fly_id)].tolist()
        return {name: r[i] for i, name in enumerate(self.group_names)}

    # --- checkpointing (BRAIN-R-070, HW-R-020) -------------------------------------------------------

    def _canonical_noise(self) -> torch.Tensor:
        """Next background event per neuron at or after the current step (block-independent)."""
        nxt = self.next_noise.clone().view(-1)
        ev = self._noise_events
        if ev is not None and ev.flat.numel():
            times, flat = self._unpack(ev)
            m = times >= self.step_count
            nxt.scatter_reduce_(0, flat[m], times[m], reduce="amin")
        return nxt.view_as(self.next_noise)

    def state_dict(self) -> tuple[dict[str, torch.Tensor], dict]:
        """Complete brain state as portable CPU tensors plus JSON metadata.

        A restored batch continues bit-identically on the same hardware and software, and restores
        on any other device (HW-R-020, -021).
        """
        tensors = {
            name: getattr(self, name).detach().cpu().contiguous() for name in self.STATE_FIELDS
        }
        tensors["next_noise"] = self._canonical_noise().cpu().contiguous()
        lengths = [int(q.numel()) for q in self.queue]
        tensors["queue"] = (
            torch.cat(self.queue).cpu() if self.queue else torch.empty(0, dtype=torch.int64)
        )
        drive = {}
        for fid, (ids, p) in self.drive.items():
            tensors[f"drive.{fid}.ids"] = ids.cpu()
            tensors[f"drive.{fid}.p"] = p.cpu()
            drive[fid] = True
        meta = {
            "format": 1,
            "template_id": self.topo.template_id,
            "dt_ms": self.dt,
            "step": self.step_count,
            "fly_ids": list(self.fly_ids),
            "queue_lengths": lengths,
            "drive": sorted(drive),
            "modulated": self.modulation is not None,
        }
        tensors["sense_ids"] = self.sense_ids.cpu()
        tensors["photo_ids"] = self.photo_ids.cpu()
        if self.modulation is not None:
            m = self.modulation
            for name in m.STATE_FIELDS:
                tensors[f"mod.{name}"] = getattr(m, name).detach().cpu().contiguous()
            tensors["mod.pending"] = m.pending.cpu()
        return tensors, meta

    def load_state_dict(self, tensors: dict[str, torch.Tensor], meta: dict) -> None:
        if meta["template_id"] != self.topo.template_id:
            raise ValueError(
                f"checkpoint is for {meta['template_id']}, not {self.topo.template_id}"
            )
        if meta["dt_ms"] != self.dt:
            raise ValueError(f"checkpoint dt {meta['dt_ms']} ms != engine dt {self.dt} ms")
        if meta["modulated"] != (self.modulation is not None):
            raise ValueError("checkpoint and engine disagree on neuromodulation")
        dev = self.device
        self.fly_ids = list(meta["fly_ids"])
        if "sense_ids" in tensors:
            self.sense_ids = tensors["sense_ids"].to(dev)
            self.photo_ids = tensors["photo_ids"].to(dev)
            self._sense_salt = self._salt[self.sense_ids]
        for name in self.STATE_FIELDS:
            setattr(self, name, tensors[name].to(dev).clone())
        self.step_count = int(meta["step"])
        q = tensors["queue"].to(dev)
        self.queue = list(torch.split(q, meta["queue_lengths"])) if meta["queue_lengths"] else []
        self.queue = [x.clone() for x in self.queue]
        self.drive = {
            fid: (tensors[f"drive.{fid}.ids"].to(dev), tensors[f"drive.{fid}.p"].to(dev))
            for fid in meta["drive"]
        }
        self._acc = torch.zeros(self.batch_size * self.n, dtype=torch.int64, device=dev)
        self._noise_events = None
        self._rebuild_drive()
        if self.modulation is not None:
            m = self.modulation
            for name in m.STATE_FIELDS:
                setattr(m, name, tensors[f"mod.{name}"].to(dev).clone())
            m.pending = tensors["mod.pending"].to(dev).clone()


def save_checkpoint(batch: BrainBatch, path) -> None:
    import json

    from safetensors.torch import save_file

    tensors, meta = batch.state_dict()
    save_file(tensors, str(path), metadata={"brain": json.dumps(meta, sort_keys=True)})


def load_checkpoint(batch: BrainBatch, path) -> None:
    import json

    from safetensors import safe_open

    with safe_open(str(path), framework="pt") as f:
        meta = json.loads(f.metadata()["brain"])
        tensors = {k: f.get_tensor(k) for k in f.keys()}  # noqa: SIM118
    batch.load_state_dict(tensors, meta)
