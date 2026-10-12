"""MaleCNS v1.0 adapter: brain portion of the male CNS (spec 001 CONN-R-016/017, design §5.1 step 9).

Sources (all CC BY 4.0, male-cns.janelia.org):
- Neuprint_Neurons.feather: per-body annotations, NT predictions and `roiInfo` (per-ROI counts).
- Neuprint_Meta.csv: ROI hierarchy and `primaryRois` (the non-overlapping neuropil set).
- connectome-weights ... traced-only.feather: body-to-body synapse counts between traced bodies.

Units: neuPrint `pre` counts presynaptic sites (T-bars); FlyWire counts synapse pairs. To match
FAFB, neuropil counts use `downstream` (output synapse pairs) and `upstream` (input pairs).
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc

from flycolony.connectome.datasets import raw_dir
from flycolony.connectome.inputs import TRANSMITTERS, BuildInputs
from flycolony.registry import Registry

# MaleCNS superclass -> the FlyWire super_class vocabulary used by FLAG_RULES (data normalization).
SUPERCLASS = {
    "ol_intrinsic": "optic",
    "cb_intrinsic": "central",
    "vnc_intrinsic": "vnc_intrinsic",
    "visual_projection": "visual_projection",
    "visual_projection_tbc": "visual_projection",
    "visual_centrifugal": "visual_centrifugal",
    "ol_sensory": "sensory",
    "cb_sensory": "sensory",
    "cb_sensory_tbc": "sensory",
    "vnc_sensory": "sensory",
    "vnc_sensory_tbc": "sensory",
    "sensory_descending": "sensory",
    "sensory_ascending": "sensory_ascending",
    "sensory_ascending_tbc": "sensory_ascending",
    "ascending_neuron": "ascending",
    "efferent_ascending": "ascending",
    "descending_neuron": "descending",
    "efferent_descending": "descending",
    "cb_motor": "motor",
    "vnc_motor": "motor",
    "cb_efferent": "efferent",
    "vnc_efferent": "efferent",
    "cb_endocrine": "endocrine",
    "vnc_endocrine": "endocrine",
    "ENS": "enteric",
}
ALWAYS_KEEP = ("descending", "ascending", "sensory_ascending")  # brain<->body interface
SIDES = {"L": "L", "R": "R", "M": "C"}
NEURON_COLUMNS = {  # neuPrint column -> our name
    ":ID(Body-ID)": "source_id",
    "status:string": "status",
    "superclass:string": "superclass",
    "class:string": "cell_class",
    "type:string": "cell_type",
    "somaSide:string": "soma_side",
    "rootSide:string": "root_side",
    "predictedNt:string": "predicted_nt",
    "predictedNtConfidence:float": "predicted_nt_conf",
    "consensusNt:string": "consensus_nt",
    "flywireType:string": "flywire_type",
    "dimorphism:string": "dimorphism",
    "synonyms:string": "synonyms",
    "roiInfo:string": "roi_info",
}


def read_meta(path: Path) -> dict:
    """primaryRois and the top-level ROI groups from Neuprint_Meta.csv."""
    csv.field_size_limit(1 << 30)
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    meta = dict(zip(rows[0], rows[1], strict=True))
    hierarchy = json.loads(meta["roiHierarchy:string"])
    primary = [r for r in meta["primaryRois:string[]"].split(";") if r]
    top = {child["name"]: _leaves(child) for child in hierarchy["children"]}
    return {"primary_rois": primary, "top_level": top}


def _leaves(node: dict) -> list[str]:
    out = [node["name"]]
    for child in node.get("children") or []:
        out += _leaves(child)
    return out


def _read_traced(path: Path) -> pl.DataFrame:
    """Traced bodies only, read batch by batch so memory stays small (CONN-R-053).

    Uses the core IPC reader rather than pyarrow.dataset, whose native module is blocked by
    Windows Application Control on some machines (portability, spec 014 HW-R-001).
    """
    with pa.memory_map(str(path)) as source:
        reader = ipc.open_file(source)
        names = reader.schema.names
        picked = [names.index(c) for c in NEURON_COLUMNS]
        status = names.index("status:string")
        batches = []
        for i in range(reader.num_record_batches):
            batch = reader.get_batch(i)
            mask = pc.equal(batch.column(status).cast(pa.string()), "Traced")
            kept = batch.filter(mask).select(picked)
            if kept.num_rows:
                batches.append(kept)
    table = pa.Table.from_batches(batches)
    cols = {
        NEURON_COLUMNS[name]: (col.cast(pa.string()) if pa.types.is_dictionary(col.type) else col)
        for name, col in zip(table.column_names, table.columns, strict=True)
    }
    return pl.from_arrow(pa.table(cols))


def _roi_counts(neurons: pl.DataFrame, rois: set[str]) -> pl.DataFrame:
    """Long (source_id, roi, pre, post) table from roiInfo JSON, for the given ROIs."""
    ids, names, pres, posts = [], [], [], []
    for body, info in neurons.select("source_id", "roi_info").iter_rows():
        if not info:
            continue
        for roi, c in json.loads(info).items():
            if roi in rois:
                ids.append(body)
                names.append(roi)
                pres.append(int(c.get("downstream", 0)))
                posts.append(int(c.get("upstream", 0)))
    return pl.DataFrame(
        {"source_id": ids, "neuropil": names, "pre": pres, "post": posts},
        schema={"source_id": pl.Int64, "neuropil": pl.String, "pre": pl.Int64, "post": pl.Int64},
    )


def malecns_inputs(raw_root: Path, registry: Registry) -> BuildInputs:
    from flycolony.connectome.build import _provenance

    d = raw_dir("malecns_v1", raw_root)
    meta = read_meta(d / "Neuprint_Meta.csv")
    brain_groups = list(registry.get("conn.male.brain_rois"))
    body_groups = list(registry.get("conn.male.vnc_rois"))
    missing = [g for g in brain_groups + body_groups if g not in meta["top_level"]]
    if missing:
        raise ValueError(f"ROI groups not in the MaleCNS hierarchy: {missing}")

    traced = _read_traced(d / "Neuprint_Neurons.feather")
    groups = _roi_counts(traced, set(brain_groups + body_groups))
    share = groups.group_by("source_id").agg(
        (
            (pl.col("pre") + pl.col("post")).filter(pl.col("neuropil").is_in(brain_groups)).sum()
            / (pl.col("pre") + pl.col("post")).sum()
        ).alias("brain_share"),
        (pl.col("pre") + pl.col("post"))
        .filter(pl.col("neuropil").is_in(brain_groups))
        .sum()
        .alias("brain_synapses"),
    )
    min_share = float(registry.get("conn.male.brain_fraction_min"))
    traced = traced.with_columns(
        pl.col("superclass")
        .replace_strict(SUPERCLASS, default=pl.col("superclass"))
        .alias("super_class")
    ).join(share, on="source_id", how="left")
    by_share = pl.col("brain_share").fill_null(0.0).fill_nan(0.0) > min_share
    interface = pl.col("super_class").is_in(list(ALWAYS_KEEP))
    sensory_in_brain = (pl.col("super_class") == "sensory") & (
        pl.col("brain_synapses").fill_null(0) > 0
    )
    keep = traced.filter(by_share | interface | sensory_in_brain)

    nt_col = {"predicted": "predicted_nt", "consensus": "consensus_nt"}[
        registry.get("conn.male.nt_source")
    ]
    neurons = keep.select(
        "source_id",
        "cell_type",
        "super_class",
        "cell_class",
        pl.coalesce(
            pl.col("soma_side").replace_strict(SIDES, default=None),
            pl.col("root_side").replace_strict(SIDES, default=None),
            pl.lit("NA"),
        ).alias("side"),
        pl.when(pl.col(nt_col).is_in(list(TRANSMITTERS))).then(pl.col(nt_col)).alias("nt_pred"),
        pl.col("predicted_nt_conf").cast(pl.Float32).alias("nt_conf"),
        "flywire_type",
        "dimorphism",
        "synonyms",
    )
    primary = set(meta["primary_rois"])
    neuropils = _roi_counts(keep, primary)
    weights = pl.scan_ipc(d / "connectome-weights-male-cns-v1.0-minconf-0.5-traced-only.feather")

    notes = {
        "neuron_set": "status == Traced, brain portion",
        "brain_portion_rule": (
            f"keep if share of synapses (downstream+upstream) in {brain_groups} > {min_share}, "
            f"or super_class in {list(ALWAYS_KEEP)}, or sensory with brain synapses"
        ),
        "traced_bodies": traced.height,
        "kept": keep.height,
        "kept_by_share": keep.filter(by_share).height,
        "kept_as_interface_only": keep.filter(interface & ~by_share).height,
        "kept_as_sensory_only": keep.filter(sensory_in_brain & ~by_share & ~interface).height,
        "full_cns_neurons_published": registry.get("conn.expected.malecns1.neurons_full_cns"),
        "primary_rois": len(primary),
        "nt_source": nt_col,
        "synapse_units": "downstream/upstream synapse pairs (matches FAFB)",
    }
    return BuildInputs(
        sex="male",
        neurons=neurons.lazy(),
        connections=weights.select(
            pl.col("body_pre").alias("pre"),
            pl.col("body_post").alias("post"),
            pl.col("weight").alias("syn_count"),
        ),
        neuropils=neuropils.lazy(),
        provenance=_provenance(["malecns_v1"], raw_root),
        notes=notes,
        mb_neuropils=tuple(registry.get("conn.male.mb_neuropils")),
        cx_neuropils=tuple(registry.get("conn.male.cx_neuropils")),
        extra_neuron_columns=("flywire_type", "dimorphism", "synonyms"),
    )
