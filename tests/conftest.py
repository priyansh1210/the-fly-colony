"""Shared fixtures: a small synthetic connectome and the real registry."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from flycolony.config.schemas import project_root
from flycolony.connectome.inputs import BuildInputs
from flycolony.registry import Registry

ROOT = project_root()
RAW = ROOT / "data" / "raw"


@pytest.fixture(scope="session")
def registry() -> Registry:
    return Registry.load(ROOT / "config" / "params")


def synthetic_inputs(seed: int = 7, n: int = 40) -> BuildInputs:
    """A random mini-connectome with every super class, transmitter and some untyped neurons."""
    rng = np.random.default_rng(seed)
    supers = [
        "central",
        "optic",
        "sensory",
        "descending",
        "ascending",
        "motor",
        "endocrine",
        "sensory_ascending",
    ]
    nts = ["acetylcholine", "gaba", "glutamate", "dopamine", "serotonin", "octopamine", None]
    types = ["KC", "MBON01", "EPG", "L1", "Mi1", "DNp01", "Gr5a", "MN1", None]
    source_ids = rng.choice(np.arange(10_000, 99_999), size=n, replace=False).astype(np.int64)
    neurons = pl.DataFrame(
        {
            "source_id": source_ids,
            "cell_type": [types[i % len(types)] for i in range(n)],
            "super_class": [supers[i % len(supers)] for i in range(n)],
            "cell_class": ["c" + str(i % 3) for i in range(n)],
            "side": [("L", "R", "C", "NA")[i % 4] for i in range(n)],
            "nt_pred": [nts[i % len(nts)] for i in range(n)],
            "nt_conf": rng.random(n).astype(np.float32),
        }
    )
    m = n * 6
    pre = rng.choice(source_ids, size=m)
    post = rng.choice(source_ids, size=m)
    # Include duplicate rows (per-neuropil splits) and one pair with an unknown neuron.
    conns = pl.DataFrame({"pre": pre, "post": post, "syn_count": rng.integers(1, 12, size=m)})
    conns = pl.concat(
        [conns, pl.DataFrame({"pre": [1], "post": [source_ids[0]], "syn_count": [50]})]
    )
    rois = ["MB_CA_L", "FB", "EB", "LO_R", "SEZ"]
    neuropils = pl.DataFrame(
        {
            "source_id": np.repeat(source_ids, 2),
            "neuropil": [rois[(i * 7 + j) % len(rois)] for i in range(n) for j in range(2)],
            "pre": rng.integers(0, 30, size=2 * n),
            "post": rng.integers(1, 30, size=2 * n),
        }
    )
    return BuildInputs(
        sex="female",
        neurons=neurons.lazy(),
        connections=conns.with_columns(pl.col("syn_count").cast(pl.Int64)).lazy(),
        neuropils=neuropils.lazy(),
        provenance={"synthetic": {"seed": seed}},
        mb_neuropils=("MB_CA_L",),
        cx_neuropils=("FB", "EB"),
    )


@pytest.fixture
def synth() -> BuildInputs:
    return synthetic_inputs()


def needs_data(*dataset_ids: str):
    """Skip a test unless the datasets have been fetched (validation tests, marker `data`)."""
    missing = [d for d in dataset_ids if not (RAW / d / "_source.json").exists()]
    return pytest.mark.skipif(bool(missing), reason=f"datasets not fetched: {missing}")


def tmp_templates(tmp_path: Path) -> Path:
    out = tmp_path / "templates"
    out.mkdir()
    return out
