"""Read-only observation taps (BRAIN-R-060..062).

A tap is called after every step with the spikes of that step. It keeps its own accumulators and
never writes to the batch, so runs with taps on and off are bit-identical (tested).
Summaries cover: activity per neuropil, per key pathway (list owned by 010), per sensory channel,
DN/motor/neurosecretory group rates, modulator and peptide traces, plastic-weight summaries, and
the full spike raster of focus flies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import torch

from flycolony.brain.engine import BrainBatch
from flycolony.brain.params import MS_PER_S
from flycolony.brain.topology import expand_rows
from flycolony.connectome.template import BrainTemplate


def _membership(
    names: list[str], members: dict[str, np.ndarray], n: int
) -> tuple[torch.Tensor, torch.Tensor]:
    """(neuron, group) pairs as two int64 tensors (a neuron may be in several groups)."""
    nid, gid = [], []
    for g, name in enumerate(names):
        ids = np.asarray(members[name], dtype=np.int64)
        nid.append(ids)
        gid.append(np.full(ids.size, g, dtype=np.int64))
    if not nid:
        return torch.empty(0, dtype=torch.int64), torch.empty(0, dtype=torch.int64)
    return torch.from_numpy(np.concatenate(nid)), torch.from_numpy(np.concatenate(gid))


@dataclass
class _Groups:
    names: list[str]
    sizes: torch.Tensor
    indptr: torch.Tensor  # neuron -> groups CSR
    groups: torch.Tensor


def _groups(names: list[str], members: dict[str, np.ndarray], n: int, device) -> _Groups:
    nid, gid = _membership(names, members, n)
    order = torch.argsort(nid, stable=True)
    nid, gid = nid[order], gid[order]
    indptr = torch.zeros(n + 1, dtype=torch.int64)
    indptr[1:] = torch.cumsum(torch.bincount(nid, minlength=n), 0)
    sizes = torch.tensor([len(members[x]) for x in names] or [1], dtype=torch.float64)
    return _Groups(names, sizes.to(device), indptr.to(device), gid.to(device))


@dataclass
class ObservationTaps:
    """Accumulates per-fly summaries between `snapshot()` calls."""

    batch: BrainBatch
    template: BrainTemplate
    pathways: dict[str, np.ndarray] = field(default_factory=dict)
    focus: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        b = self.batch
        n = b.n
        neurons = self.template.neurons
        npil = neurons["primary_neuropil"].fill_null("none").to_list()
        names = sorted(set(npil) - {"none"})
        idx = {x: i for i, x in enumerate(names)}
        members: dict[str, list[int]] = {x: [] for x in names}
        for i, x in enumerate(npil):
            if x in idx:
                members[x].append(i)
        self._npil = _groups(names, {k: np.asarray(v) for k, v in members.items()}, n, b.device)
        io = json.loads((self.template.path / "iomap.json").read_text(encoding="utf-8"))
        senses = {
            e["name"]: np.asarray(e["neuron_ids"])
            for e in io["entries"]
            if e["kind"] == "sense" and e["neuron_ids"]
        }
        self._senses = _groups(sorted(senses), senses, n, b.device)
        self._paths = _groups(sorted(self.pathways), self.pathways, n, b.device)
        self.raster: dict[str, list[tuple[int, np.ndarray]]] = {}
        self._reset()
        b.taps.append(self)

    def _reset(self) -> None:
        b = self.batch
        dev = b.device
        self.steps = 0
        self.counts = {
            "neuropil": torch.zeros(
                b.batch_size * len(self._npil.names), dtype=torch.int64, device=dev
            ),
            "sense": torch.zeros(
                b.batch_size * len(self._senses.names), dtype=torch.int64, device=dev
            ),
            "pathway": torch.zeros(
                b.batch_size * len(self._paths.names), dtype=torch.int64, device=dev
            ),
        }

    def _add(self, key: str, grp: _Groups, spikes: torch.Tensor) -> None:
        ng = len(grp.names)
        if not ng or spikes.numel() == 0:
            return
        n = self.batch.n
        e, which = expand_rows(grp.indptr, spikes % n)
        flat = (spikes // n)[which] * ng + grp.groups[e]
        self.counts[key].index_add_(0, flat, torch.ones_like(flat))

    def __call__(self, batch: BrainBatch, t: int, spikes: torch.Tensor) -> None:
        if self.counts["neuropil"].numel() != batch.batch_size * len(self._npil.names):
            self._reset()  # batch composition changed: start a new window
        self.steps += 1
        self._add("neuropil", self._npil, spikes)
        self._add("sense", self._senses, spikes)
        self._add("pathway", self._paths, spikes)
        if self.focus:
            for fid in self.focus & set(batch.fly_ids):
                s = batch.slot(fid)
                own = spikes[(spikes // batch.n) == s] % batch.n
                if own.numel():
                    self.raster.setdefault(fid, []).append((t, own.cpu().numpy()))

    def snapshot(self) -> dict[str, dict]:
        """Per-fly summaries over the window since the last snapshot; starts a new window."""
        b = self.batch
        window_s = max(self.steps, 1) * b.dt / MS_PER_S
        out: dict[str, dict] = {}

        def rates(key: str, grp: _Groups) -> np.ndarray:
            ng = len(grp.names)
            if not ng:
                return np.zeros((b.batch_size, 0))
            c = self.counts[key].view(b.batch_size, ng).to(torch.float64) / grp.sizes / window_s
            return c.cpu().numpy()

        npil, sense, path = (
            rates("neuropil", self._npil),
            rates("sense", self._senses),
            rates("pathway", self._paths),
        )
        rates_out = b.rates.cpu().numpy()
        for s, fid in enumerate(b.fly_ids):
            rec = {
                "step": b.step_count,
                "window_s": window_s,
                "neuropil_hz": dict(zip(self._npil.names, npil[s].tolist(), strict=True)),
                "sense_hz": dict(zip(self._senses.names, sense[s].tolist(), strict=True)),
                "pathway_hz": dict(zip(self._paths.names, path[s].tolist(), strict=True)),
                "group_hz": dict(zip(b.group_names, rates_out[s].tolist(), strict=True)),
                "traces": b.modulation.trace_summary(fid) if b.modulation is not None else {},
                "plastic_mean": self._plastic_summary(s),
                # BRAIN-R-045 (sleep state) arrives with the sleep homeostat (Phase 2); reported as
                # unknown rather than guessed until then.
                "sleep_state": None,
            }
            if fid in self.raster:
                rec["raster"] = self.raster.pop(fid)
            out[fid] = rec
        self._reset()
        return out

    def _plastic_summary(self, s: int) -> dict[str, float]:
        b = self.batch
        out, offset = {}, 0
        for ps in b.plastic_sets:
            m = int(ps.edges.numel())
            out[ps.name] = float(b.plastic[s, offset : offset + m].double().mean()) if m else 0.0
            offset += m
        return out
