"""Tiny hand-built brain templates for engine unit tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
import torch

from flycolony.brain.engine import BrainBatch
from flycolony.brain.params import NeuronParams
from flycolony.brain.topology import build_topology
from flycolony.connectome.template import BrainTemplate

CPU = torch.device("cpu")  # device-ok: tests pick devices explicitly


def tiny_template(
    tmp_path: Path,
    edges: list[tuple[int, int, float]],
    n: int,
    *,
    sensory: tuple[int, ...] = (),
    graded: tuple[int, ...] = (),
    cell_types: list[str] | None = None,
    neuropils: list[str | None] | None = None,
    neurosecretory: tuple[int, ...] = (),
    iomap: list[dict] | None = None,
    modulatory: list[tuple[int, str]] | None = None,
) -> BrainTemplate:
    """A template with `n` neurons and signed synapse-count `edges` (pre, post, weight)."""
    path = tmp_path / "tiny-t1"
    path.mkdir(parents=True, exist_ok=True)
    edges = sorted(edges)
    pre = np.array([e[0] for e in edges], dtype=np.int64)
    post = np.array([e[1] for e in edges], dtype=np.int32)
    w = np.array([e[2] for e in edges], dtype=np.float32)
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(pre, minlength=n), out=indptr[1:])
    cell_types = cell_types or [f"T{i}" for i in range(n)]
    neuropils = neuropils or ["SEZ"] * n
    neurons = pl.DataFrame(
        {
            "neuron_id": np.arange(n, dtype=np.int32),
            "source_id": np.arange(1000, 1000 + n, dtype=np.int64),
            "cell_type": cell_types,
            "side": ["L"] * n,
            "model": ["graded" if i in graded else "spiking" for i in range(n)],
            "is_sensory": [i in sensory for i in range(n)],
            "is_neurosecretory": [i in neurosecretory for i in range(n)],
            "primary_neuropil": neuropils,
        }
    )
    (path / "iomap.json").write_text(json.dumps({"entries": iomap or []}), encoding="utf-8")
    mod = modulatory or []
    pl.DataFrame(
        {
            "neuron_id": [m[0] for m in mod],
            "substance": [m[1] for m in mod],
            "source_ref": ["t"] * len(mod),
        },
        schema={"neuron_id": pl.Int32, "substance": pl.String, "source_ref": pl.String},
    ).write_parquet(path / "modulatory.parquet")
    pl.DataFrame(
        {
            "neuron_id": np.arange(n, dtype=np.int32),
            "neuropil": [p or "SEZ" for p in neuropils],
            "pre_frac": np.ones(n, dtype=np.float32),
        }
    ).write_parquet(path / "neuropil_fractions.parquet")
    return BrainTemplate(
        path=path,
        manifest={"template_id": "tiny-t1"},
        neurons=neurons,
        edges={"indptr": indptr, "indices": post, "weight": w},
    )


def params(registry, **over) -> NeuronParams:
    return replace(NeuronParams.from_registry(registry, reference=True), **over)


def batch(
    template: BrainTemplate, p: NeuronParams, dt: float = 0.1, device=CPU, graded=False, **kw
) -> BrainBatch:
    topo = build_topology(template, device, w_per_synapse=p.w_syn, graded=graded)
    return BrainBatch(topo, p, dt, **kw)


def state_hash(b: BrainBatch, fly_ids=None) -> dict[str, str]:
    """Per-fly hash of every state tensor row (for bit-identity checks)."""
    import hashlib

    out = {}
    for fid in fly_ids or b.fly_ids:
        s = b.slot(fid)
        h = hashlib.sha256()
        canonical = {"next_noise": b._canonical_noise()}
        for name in b.STATE_FIELDS:
            t = canonical.get(name, getattr(b, name))
            h.update(t[s].detach().cpu().contiguous().numpy().tobytes())
        if b.modulation is not None:
            for name in b.modulation.STATE_FIELDS:
                h.update(
                    getattr(b.modulation, name)[s].detach().cpu().contiguous().numpy().tobytes()
                )
        out[fid] = h.hexdigest()
    return out
