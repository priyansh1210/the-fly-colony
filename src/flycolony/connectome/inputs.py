"""Normalized build inputs: what every source adapter must produce (design §5.1).

All frames are Polars LazyFrames so adapters can stream large files.

neurons:      source_id:i64, cell_type:str?, super_class:str?, cell_class:str?, side:str (L/R/C/NA),
              nt_pred:str?, nt_conf:f32?
connections:  pre:i64, post:i64, syn_count:i64          (source ids; aggregated or not)
neuropils:    source_id:i64, neuropil:str, pre:i64, post:i64   (synapse counts per neuron and neuropil)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

NEURON_SCHEMA = {
    "source_id": pl.Int64,
    "cell_type": pl.String,
    "super_class": pl.String,
    "cell_class": pl.String,
    "side": pl.String,
    "nt_pred": pl.String,
    "nt_conf": pl.Float32,
}
CONNECTION_SCHEMA = {"pre": pl.Int64, "post": pl.Int64, "syn_count": pl.Int64}
NEUROPIL_SCHEMA = {"source_id": pl.Int64, "neuropil": pl.String, "pre": pl.Int64, "post": pl.Int64}

SIDES = ("L", "R", "C", "NA")
TRANSMITTERS = ("acetylcholine", "gaba", "glutamate", "dopamine", "serotonin", "octopamine")


@dataclass
class BuildInputs:
    """Everything the core builder needs, independent of the source dataset."""

    sex: str  # "female" | "male"
    neurons: pl.LazyFrame
    connections: pl.LazyFrame
    neuropils: pl.LazyFrame
    # dataset id -> {file name -> sha256}; recorded in the manifest (CONN-R-050)
    provenance: dict[str, dict] = field(default_factory=dict)
    # Extra facts the adapter wants in the manifest (e.g. the male brain-portion rule and counts)
    notes: dict = field(default_factory=dict)
    # Brain neuropils used for neuron-level sets (MB, CX) in this dataset's naming
    mb_neuropils: tuple[str, ...] = ()
    cx_neuropils: tuple[str, ...] = ()
    # Extra string columns copied into the neuron table (e.g. cross-dataset type names)
    extra_neuron_columns: tuple[str, ...] = ()
    # Peptidergic neurons with a citation per row (CONN-R-015):
    # source_id:i64, substance:str, source_ref:str. None = no peptide information.
    peptides: pl.LazyFrame | None = None


def conform(lf: pl.LazyFrame, schema: dict[str, pl.DataType]) -> pl.LazyFrame:
    """Select and cast exactly the schema columns (missing columns raise early)."""
    return lf.select([pl.col(name).cast(dtype) for name, dtype in schema.items()])
