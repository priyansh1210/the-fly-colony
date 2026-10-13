"""Neuromodulator and neuropeptide traces, receptor effects and interoceptive routes
(BRAIN-R-030..034).

- Releasing neurons are ordinary spiking neurons (the template's modulatory list, CONN-R-015).
  Each spike adds to the trace of its substance in every neuropil where the neuron has output
  synapses, weighted by its output fraction there. Neurosecretory cells release into a global
  compartment (BRAIN-OQ-03: regional where release sites are known, otherwise global).
- A trace is a dual exponential of release: ``c = x_decay - x_rise``. Amines and peptides have
  their own registry constants.
- The receptor table (`config/brain/receptors.yaml`) turns the concentration a neuron sees
  (its primary neuropil + global) into an input-gain or threshold change.
- Interoceptive routes (`config/senses/routes.yaml`) are the only way body state reaches the brain.

Releases are summed in int64 fixed point, like synaptic input, so traces are deterministic and
batch-independent.
"""

from __future__ import annotations

import math
import weakref
from typing import Literal

import numpy as np
import polars as pl
import torch
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from flycolony.brain.params import MS_PER_S
from flycolony.brain.select import Select, resolve_select
from flycolony.brain.topology import expand_rows
from flycolony.config import project_root
from flycolony.connectome.template import BrainTemplate
from flycolony.registry.registry import Source

AMINES = ("dopamine", "serotonin", "octopamine")
GLOBAL = "global"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReceptorEntry(_Strict):
    name: str
    select: Select
    substance: str
    effect: Literal["gain", "excitability"]
    sensitivity: float
    source: Source


class ReceptorTable(_Strict):
    version: int
    entries: list[ReceptorEntry]


class Transfer(_Strict):
    kind: Literal["linear", "sigmoid"]
    gain: float = 1.0
    offset: float = 0.0
    max: float = 1.0
    half: float = 0.0
    slope: float = 1.0

    def __call__(self, x: float) -> float:
        if self.kind == "linear":
            return self.gain * x + self.offset
        return self.max / (1.0 + math.exp(-(x - self.half) / self.slope))


class RouteTarget(_Strict):
    trace: str | None = None
    select: Select | None = None
    effect: Literal["gain", "excitability"] | None = None
    sense_channel: str | None = None  # a sensory-layer gain (004 §8), applied by flycolony.senses

    @model_validator(mode="after")
    def _one(self) -> RouteTarget:
        kinds = (self.trace, self.select, self.sense_channel)
        if sum(k is not None for k in kinds) != 1:
            raise ValueError("a route targets one of: a trace, a neuron selection, a sense channel")
        if self.select is not None and self.effect is None:
            raise ValueError("a neuron-targeting route needs an effect")
        return self


class Route(_Strict):
    id: str
    source: str
    target: RouteTarget
    transfer: Transfer
    citation: str = Field(min_length=1)


class RouteCatalog(_Strict):
    version: int
    routes: list[Route]

    def get(self, route_id: str) -> Route:
        for r in self.routes:
            if r.id == route_id:
                return r
        raise KeyError(f"route {route_id!r} is not in the interoceptive route catalog")


class RouteError(KeyError):
    """A body-to-brain change outside the catalogued routes (BRAIN-R-034)."""


def load_receptors(path=None) -> ReceptorTable:
    path = path or project_root() / "config" / "brain" / "receptors.yaml"
    return ReceptorTable.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_routes(path=None) -> RouteCatalog:
    path = path or project_root() / "config" / "senses" / "routes.yaml"
    return RouteCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class Modulation:
    """Trace and receptor state for every fly of a BrainBatch."""

    def __init__(
        self,
        template: BrainTemplate,
        receptors: ReceptorTable,
        routes: RouteCatalog,
        *,
        fractions: pl.DataFrame | None = None,
        modulatory: pl.DataFrame | None = None,
    ):
        self.template = template
        self.receptors = receptors
        self.routes = routes
        neurons = template.neurons
        self.n = neurons.height
        if modulatory is None:
            modulatory = pl.read_parquet(template.path / "modulatory.parquet")
        if fractions is None:
            fractions = pl.read_parquet(
                template.path / "neuropil_fractions.parquet",
                columns=["neuron_id", "neuropil", "pre_frac"],
            )
        substances = set(modulatory["substance"].to_list())
        substances |= {e.substance for e in receptors.entries}
        substances |= {r.target.trace for r in routes.routes if r.target.trace}
        self.substances = sorted(substances)
        self.regions = [*sorted(set(fractions["neuropil"].to_list())), GLOBAL]
        self.n_regions = len(self.regions)
        self.k_slots = len(self.substances) * self.n_regions
        s_idx = {s: i for i, s in enumerate(self.substances)}
        r_idx = {r: i for i, r in enumerate(self.regions)}
        self._slot = lambda s, r: s_idx[s] * self.n_regions + r_idx[r]
        self.is_amine = np.array(
            [s in AMINES for s in self.substances for _ in self.regions], dtype=bool
        )
        # Release table: (neuron, slot, fraction).
        neurosecretory = set(neurons.filter(pl.col("is_neurosecretory"))["neuron_id"].to_list())
        rel = (
            modulatory.select("neuron_id", "substance")
            .unique()
            .join(fractions.filter(pl.col("pre_frac") > 0), on="neuron_id", how="left")
        )
        rows: list[tuple[int, int, float]] = []
        for nid, sub, npil, frac in rel.iter_rows():
            if nid in neurosecretory or npil is None:
                rows.append((nid, self._slot(sub, GLOBAL), 1.0))
            else:
                rows.append((nid, self._slot(sub, npil), float(frac)))
        rows = sorted(set(rows))
        self.release_rows = rows
        # Receptor and route effects on neurons.
        primary = neurons["primary_neuropil"].to_list()
        self.effects: list[
            tuple[int, int, int, float, str]
        ] = []  # neuron, reg slot, glob slot, sens, kind
        self.unmatched: list[str] = []
        for e in receptors.entries:
            ids = resolve_select(e.select, template, allow_empty=True).neuron_ids
            if ids.size == 0:
                self.unmatched.append(e.name)
            for j in ids.tolist():
                reg = primary[j]
                reg_slot = self._slot(e.substance, reg) if reg in r_idx and reg != GLOBAL else -1
                self.effects.append(
                    (j, reg_slot, self._slot(e.substance, GLOBAL), e.sensitivity, e.effect)
                )
        self.route_ids = [r.id for r in routes.routes]
        self.route_effects: list[tuple[int, int, str]] = []  # neuron, route index, kind
        for ri, r in enumerate(routes.routes):
            if r.target.select is not None:
                ids = resolve_select(r.target.select, template, allow_empty=True).neuron_ids
                if ids.size == 0:
                    self.unmatched.append(f"route:{r.id}")
                self.route_effects += [(j, ri, r.target.effect) for j in ids.tolist()]
        self._batch = None

    # --- wiring into a batch ---------------------------------------------------------------------

    @property
    def batch(self):
        """The bound BrainBatch. Held weakly: the batch owns its modulation, and a strong
        back-reference would form a cycle that keeps a finished batch's GPU tensors alive until
        Python's cyclic GC happens to run."""
        return self._batch() if self._batch is not None else None

    def attach(self, batch) -> Modulation:
        """Bind to a BrainBatch (which then calls back on every step)."""
        if batch.n != self.n:
            raise ValueError("template size mismatch")
        self._batch = weakref.ref(batch)
        p, dev = batch.params, batch.device
        self.dev = dev
        self.scale = batch._scale
        self.every = max(1, round(p.trace_update_interval / batch.dt))
        h = self.every * batch.dt
        amine = torch.from_numpy(self.is_amine).to(dev)
        self.e_rise = torch.where(
            amine, math.exp(-h / p.amine_tau_rise), math.exp(-h / p.peptide_tau_rise)
        ).float()
        self.e_decay = torch.where(
            amine, math.exp(-h / p.amine_tau_decay), math.exp(-h / p.peptide_tau_decay)
        ).float()
        # A steady trace of 1 = releasers firing at brain.trace.unit_rate (fraction-weighted mean).
        tau_decay_s = np.where(self.is_amine, p.amine_tau_decay, p.peptide_tau_decay) / MS_PER_S
        self.per_spike = torch.from_numpy(1.0 / (p.trace_unit_rate * tau_decay_s)).float().to(dev)
        self.max_gain = p.max_gain_change
        n = self.n
        rel = np.array(self.release_rows, dtype=np.float64).reshape(-1, 3)  # registry-ok: row width
        nid = rel[:, 0].astype(np.int64)
        indptr = np.zeros(n + 1, dtype=np.int64)
        np.cumsum(np.bincount(nid, minlength=n), out=indptr[1:])
        self.rel_indptr = torch.from_numpy(indptr).to(dev)
        self.rel_slot = torch.from_numpy(rel[:, 1].astype(np.int64)).to(dev)
        slot = rel[:, 1].astype(np.int64)
        capacity = np.bincount(slot, weights=rel[:, 2], minlength=self.k_slots)
        share = rel[:, 2] / capacity[slot]  # each releaser's share of its compartment
        self.rel_q = torch.from_numpy(np.round(share * self.scale).astype(np.int64)).to(dev)
        self.is_releaser = torch.from_numpy(np.diff(indptr) > 0).to(dev)
        # Effects. Concentration columns: K slots, one zero column, then one per route.
        zero_col = self.k_slots
        cols_reg, cols_glob, sens, neuron, kind = [], [], [], [], []
        for j, rs, gs, s, kd in self.effects:
            neuron.append(j)
            cols_reg.append(rs if rs >= 0 else zero_col)
            cols_glob.append(gs)
            sens.append(s)
            kind.append(kd)
        for j, ri, kd in self.route_effects:
            neuron.append(j)
            cols_reg.append(zero_col + 1 + ri)
            cols_glob.append(zero_col)
            sens.append(1.0)
            kind.append(kd)
        neuron = np.array(neuron, dtype=np.int64)
        kind = np.array(kind)
        self.gain_neurons, gain_inv = np.unique(neuron[kind == "gain"], return_inverse=True)
        self.exc_neurons, exc_inv = np.unique(neuron[kind == "excitability"], return_inverse=True)
        self._pairs = {}
        for name, mask, inv in (
            ("gain", kind == "gain", gain_inv),
            ("excitability", kind == "excitability", exc_inv),
        ):
            self._pairs[name] = (
                torch.from_numpy(np.array(cols_reg, dtype=np.int64)[mask]).to(dev),
                torch.from_numpy(np.array(cols_glob, dtype=np.int64)[mask]).to(dev),
                torch.tensor(np.array(sens, dtype=np.float32)[mask], device=dev),
                torch.from_numpy(inv.astype(np.int64)).to(dev),
            )
        self.gain_idx = torch.from_numpy(self.gain_neurons).to(dev)
        self.exc_idx = torch.from_numpy(self.exc_neurons).to(dev)
        self._alloc(batch.batch_size)
        if batch.batch_size:
            self.theta_base = batch.theta[:, self.exc_idx].clone()
        batch.modulation = self
        return self

    def _alloc(self, b: int) -> None:
        dev, f32 = self.dev, torch.float32
        self.x_decay = torch.zeros(b, self.k_slots, dtype=f32, device=dev)
        self.x_rise = torch.zeros(b, self.k_slots, dtype=f32, device=dev)
        self.body = torch.zeros(b, self.k_slots, dtype=f32, device=dev)
        self.route_level = torch.zeros(b, len(self.route_ids), dtype=f32, device=dev)
        self.pending = torch.zeros(b * self.k_slots, dtype=torch.int64, device=dev)
        self.gain = torch.ones(b, self.n, dtype=f32, device=dev)
        self.theta_base = torch.zeros(b, self.exc_idx.numel(), dtype=f32, device=dev)

    STATE_FIELDS = ("x_decay", "x_rise", "body", "route_level", "gain", "theta_base")

    def on_add(self) -> None:
        b = self.batch
        rows = {
            "x_decay": torch.zeros(self.k_slots, device=self.dev),
            "x_rise": torch.zeros(self.k_slots, device=self.dev),
            "body": torch.zeros(self.k_slots, device=self.dev),
            "route_level": torch.zeros(len(self.route_ids), device=self.dev),
            "gain": torch.ones(self.n, device=self.dev),
            "theta_base": b.theta[-1, self.exc_idx].clone(),
        }
        for name, v in rows.items():
            setattr(self, name, torch.cat([getattr(self, name), v.unsqueeze(0)]))
        self.pending = torch.cat(
            [self.pending, torch.zeros(self.k_slots, dtype=torch.int64, device=self.dev)]
        )

    def on_remove(self, keep: torch.Tensor) -> None:
        for name in self.STATE_FIELDS:
            setattr(self, name, getattr(self, name).index_select(0, keep))
        self.pending = self.pending.view(-1, self.k_slots).index_select(0, keep).reshape(-1)

    # --- per step ----------------------------------------------------------------------------------

    def release(self, spikes: torch.Tensor) -> None:
        if spikes.numel() == 0:
            return
        n = self.n
        rel = spikes[self.is_releaser[spikes % n]]
        if rel.numel() == 0:
            return
        edge, which = expand_rows(self.rel_indptr, rel % n)
        flat = (rel // n)[which] * self.k_slots + self.rel_slot[edge]
        self.pending.index_add_(0, flat, self.rel_q[edge])

    def before_step(self, t: int) -> None:
        if t % self.every:
            return
        b = self.batch.batch_size
        released = (
            self.pending.view(b, self.k_slots).to(torch.float32) / self.scale * self.per_spike
        )
        self.pending.zero_()
        self.x_decay = self.x_decay * self.e_decay + released
        self.x_rise = self.x_rise * self.e_rise + released
        conc = self.concentration()
        cols = torch.cat([conc, torch.zeros(b, 1, device=self.dev), self.route_level], dim=1)
        if self.gain_idx.numel():
            m = self._effect(cols, "gain", self.gain_idx.numel()).clamp_(
                -self.max_gain, self.max_gain
            )
            self.gain[:, self.gain_idx] = m + 1.0
        if self.exc_idx.numel():
            shift = self._effect(cols, "excitability", self.exc_idx.numel())
            self.batch.theta[:, self.exc_idx] = self.theta_base - shift

    def _effect(self, cols: torch.Tensor, kind: str, n_out: int) -> torch.Tensor:
        reg, glob, sens, inv = self._pairs[kind]
        val = (cols[:, reg] + cols[:, glob]) * sens
        b = cols.shape[0]
        q = torch.round(val * self.scale).to(torch.int64)
        acc = torch.zeros(b * n_out, dtype=torch.int64, device=self.dev)
        flat = (torch.arange(b, device=self.dev).unsqueeze(1) * n_out + inv).reshape(-1)
        acc.index_add_(0, flat, q.reshape(-1))
        return acc.view(b, n_out).to(torch.float32) / self.scale

    def concentration(self) -> torch.Tensor:
        """Trace concentrations [B, substances x regions] (brain release + body routes)."""
        return self.x_decay - self.x_rise + self.body

    # --- interoceptive routes (BRAIN-R-033) -------------------------------------------------------

    def apply_route(self, fly_id: str, route_id: str, value: float) -> None:
        """Set a catalogued body→brain route's source value for one fly."""
        try:
            route = self.routes.get(route_id)
        except KeyError as e:
            raise RouteError(str(e)) from None
        if route.target.sense_channel is not None:
            raise RouteError(f"route {route_id!r} acts at the sensory layer (flycolony.senses)")
        b = self.batch.slot(fly_id)
        level = float(route.transfer(float(value)))
        if route.target.trace is not None:
            self.body[b, self._slot(route.target.trace, GLOBAL)] = level
        else:
            self.route_level[b, self.route_ids.index(route_id)] = level

    def trace_summary(self, fly_id: str) -> dict[str, float]:
        """Per-substance concentration summed over regions (an observation-tap summary)."""
        c = self.concentration()[self.batch.slot(fly_id)].view(len(self.substances), self.n_regions)
        return dict(zip(self.substances, c.sum(1).tolist(), strict=True))
