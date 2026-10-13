"""Validation assays (BRAIN-R-080..082) and the engine-side assay runner.

An assay drives sensory neurons with Poisson input for a fixed duration, repeated over trials,
and reports trial-mean firing rates per neuron. Trials run as a batch of brains with different
seeds, so a 30-trial assay is one batched run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import yaml
from pydantic import BaseModel, ConfigDict, Field

from flycolony.brain.engine import BrainBatch, FlyBrainSpec
from flycolony.brain.params import MS_PER_S, NeuronParams
from flycolony.brain.select import Resolved, Select, resolve_select
from flycolony.brain.topology import Topology
from flycolony.config import project_root
from flycolony.connectome.template import BrainTemplate


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Drive(_Strict):
    select: Select
    rate_hz: float


class Expect(_Strict):
    readout: str
    op: str = Field(pattern=r"^[<>]$")
    vs: str  # "baseline" or another assay name


class Assay(_Strict):
    name: str
    description: str
    citation: str
    drive: list[Drive]
    readout: list[Select]
    expect: list[Expect] = Field(default_factory=list)
    duration_ms: float = 0.0
    trials: int = 0


class AssaySet(_Strict):
    version: int
    defaults: dict
    assays: list[Assay]

    def get(self, name: str) -> Assay:
        for a in self.assays:
            if a.name == name:
                return a
        raise KeyError(f"no assay {name!r}; have {[a.name for a in self.assays]}")


def load_assays(path: Path | None = None) -> AssaySet:
    path = path or project_root() / "config" / "brain" / "assays.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    s = AssaySet.model_validate(raw)
    for a in s.assays:
        a.duration_ms = a.duration_ms or float(s.defaults["duration_ms"])
        a.trials = a.trials or int(s.defaults["trials"])
    return s


def resolve_stimulus(assay: Assay, template: BrainTemplate) -> list[Resolved]:
    out = []
    for d in assay.drive:
        r = resolve_select(d.select, template)
        r.rate_hz = d.rate_hz
        out.append(r)
    return out


def resolve_readouts(assay: Assay, template: BrainTemplate) -> dict[str, np.ndarray]:
    return {s.name: resolve_select(s, template).neuron_ids for s in assay.readout}


def run_assay(
    assay: Assay,
    template: BrainTemplate,
    topo: Topology,
    params: NeuronParams,
    dt: float,
    *,
    trials: int | None = None,
    seed: int = 0,
    batch: int | None = None,
    stimulus: list[Resolved] | None = None,
    make_batch: Callable[[], BrainBatch] | None = None,
) -> np.ndarray:
    """Trial-mean firing rate (Hz) of every neuron. Trials are flies with seeds seed..seed+T-1.

    `stimulus` overrides the assay's own (e.g. mapped to the other sex); `make_batch` builds the
    engine (default: a plain BrainBatch, i.e. no modulation, as in the reference model).
    """
    stim = stimulus if stimulus is not None else resolve_stimulus(assay, template)
    trials = trials or assay.trials
    batch = batch or trials
    steps = round(assay.duration_ms / dt)
    ids = np.concatenate([r.neuron_ids for r in stim])
    rates = np.concatenate([np.full(r.neuron_ids.size, r.rate_hz) for r in stim])
    total = torch.zeros(topo.n, dtype=torch.int64, device=topo.device)
    for start in range(0, trials, batch):
        bb = make_batch() if make_batch is not None else BrainBatch(topo, params, dt)
        for s in range(start, min(trials, start + batch)):
            fid = f"trial{s}"
            bb.add(FlyBrainSpec(fid, seed + s))
            bb.set_drive(fid, ids, rates)
        counts = torch.zeros(bb.batch_size * topo.n, dtype=torch.int64, device=topo.device)

        def tap(_b, _t, spikes, counts=counts):
            counts.index_add_(0, spikes, torch.ones_like(spikes))

        bb.taps.append(tap)
        bb.run(steps)
        total += counts.view(bb.batch_size, topo.n).sum(0)
    return (total.double() / (trials * steps * dt / MS_PER_S)).cpu().numpy()


@dataclass
class Agreement:
    pearson: float
    n_responsive: int
    top_k: int
    top_k_overlap: float


def agreement(
    ref: np.ndarray,
    test: np.ndarray,
    *,
    responsive_hz: float,
    top_k: int,
    exclude: np.ndarray | None = None,
) -> Agreement:
    """BRAIN-R-081: Pearson r over neurons responsive in either run, and overlap of the top-k
    activated sets. `exclude` drops the stimulated neurons: their rates are the drive itself, and
    a near-tie among them would make the top-k comparison measure Poisson noise, not the network."""
    keep = np.ones(ref.shape, dtype=bool)
    if exclude is not None and len(exclude):
        keep[np.asarray(exclude, dtype=np.int64)] = False
    resp = ((ref >= responsive_hz) | (test >= responsive_hz)) & keep
    r = float(np.corrcoef(ref[resp], test[resp])[0, 1]) if resp.sum() > 1 else float("nan")
    k = min(top_k, int(resp.sum()))
    masked_ref, masked_test = np.where(keep, ref, -np.inf), np.where(keep, test, -np.inf)
    top_ref = set(np.argsort(-masked_ref, kind="stable")[:k].tolist())
    top_test = set(np.argsort(-masked_test, kind="stable")[:k].tolist())
    overlap = len(top_ref & top_test) / k if k else float("nan")
    return Agreement(r, int(resp.sum()), k, overlap)
