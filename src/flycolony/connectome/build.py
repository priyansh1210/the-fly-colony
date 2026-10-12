"""Source adapters (FAFB v783, MaleCNS v1.0) and the per-sex build entry point (design §5.1)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from flycolony.config import load_all, project_root
from flycolony.connectome.datasets import load_catalog, raw_dir, require_license, source_record
from flycolony.connectome.inputs import TRANSMITTERS, BuildInputs
from flycolony.connectome.iomap import load_iomap
from flycolony.connectome.template import build_template
from flycolony.registry import Registry

FAFB_SIDES = {"left": "L", "right": "R", "center": "C", "na": "NA"}
# Columns of the connection table holding mean transmitter probabilities.
FAFB_NT_COLUMNS = {
    "acetylcholine": "ach_avg",
    "gaba": "gaba_avg",
    "glutamate": "glut_avg",
    "dopamine": "da_avg",
    "serotonin": "ser_avg",
    "octopamine": "oct_avg",
}


def _provenance(dataset_ids: list[str], root: Path) -> dict:
    catalog = load_catalog()
    out = {}
    for ds_id in dataset_ids:
        lic = require_license(catalog, ds_id)  # license gate (CONN-R-003)
        rec = source_record(ds_id, root)
        out[ds_id] = {
            "version": rec["version"],
            "license": f"{lic.name} ({lic.status})",
            "files": {name: meta["sha256"] for name, meta in sorted(rec["files"].items())},
        }
    return out


# --- FAFB v783 (female) --------------------------------------------------------------------


# Fixed-point scale for transmitter probabilities. Integer sums are exact and independent of the
# (parallel) summation order, so the result is bit-identical across runs (CONN-R-052).
NT_FIXED_POINT = 10**9


def fafb_connection_nt(connections: pl.LazyFrame) -> pl.LazyFrame:
    """Per presynaptic neuron: synapse-weighted mean NT probabilities -> argmax and confidence."""
    weighted = [
        ((pl.col(col) * NT_FIXED_POINT).round().cast(pl.Int64) * pl.col("syn_count"))
        .sum()
        .alias(nt)
        for nt, col in FAFB_NT_COLUMNS.items()
    ]
    agg = connections.group_by("pre_pt_root_id").agg(
        *weighted, pl.col("syn_count").sum().alias("n")
    )
    scores = pl.concat_list([pl.col(nt) for nt in TRANSMITTERS])  # exact integers
    return agg.select(
        pl.col("pre_pt_root_id").alias("source_id"),
        scores.list.arg_max()
        .replace_strict(dict(enumerate(TRANSMITTERS)), return_dtype=pl.String)
        .alias("nt_conn"),
        (scores.list.max() / (pl.col("n") * NT_FIXED_POINT)).cast(pl.Float32).alias("nt_conn_conf"),
    )


def fafb_inputs(raw_root: Path, registry: Registry) -> BuildInputs:
    conn_dir = raw_dir("fafb783_connectome", raw_root)
    ann_path = (
        raw_dir("fafb783_annotations", raw_root) / "Supplemental_file1_neuron_annotations.tsv"
    )

    root_ids = np.load(conn_dir / "proofread_root_ids_783.npy").astype(np.int64)
    ids = pl.DataFrame({"source_id": root_ids})
    connections = pl.scan_ipc(conn_dir / "proofread_connections_783.feather")
    ann = pl.scan_csv(ann_path, separator="\t", infer_schema=False).select(
        pl.col("root_id").cast(pl.Int64).alias("source_id"),
        pl.col("cell_type"),
        pl.col("super_class"),
        pl.col("cell_class"),
        pl.col("side").replace_strict(FAFB_SIDES, default="NA"),
        pl.col("top_nt").alias("nt_ann"),
        pl.col("top_nt_conf").cast(pl.Float32).alias("nt_ann_conf"),
        pl.col("dimorphism"),
        pl.col("hemibrain_type"),
    )
    nt_source = registry.get("conn.fafb.nt_source")
    neurons = (
        ids.lazy()
        .join(ann, on="source_id", how="left")
        .join(fafb_connection_nt(connections), on="source_id", how="left")
        .with_columns(pl.col("side").fill_null("NA"))
    )
    if nt_source == "annotations":
        neurons = neurons.with_columns(
            pl.coalesce("nt_ann", "nt_conn").alias("nt_pred"),
            pl.coalesce("nt_ann_conf", "nt_conn_conf").alias("nt_conf"),
        )
    else:  # "connections"
        neurons = neurons.with_columns(
            pl.coalesce("nt_conn", "nt_ann").alias("nt_pred"),
            pl.coalesce("nt_conn_conf", "nt_ann_conf").alias("nt_conf"),
        )

    datasets = ["fafb783_connectome", "fafb783_annotations"]
    sign_source = registry.get("conn.fafb.sign_source")
    if sign_source == "reference":
        # CONN-OQ-03: follow the reference model where it defines a sign (per presynaptic neuron).
        ref = raw_dir("shiu2024_model", raw_root) / "Connectivity_783.parquet"
        ref_signs = (
            pl.scan_parquet(ref)
            .group_by("Presynaptic_ID")
            .agg(pl.col("Excitatory").first().cast(pl.Int8).alias("sign_ref"))
            .rename({"Presynaptic_ID": "source_id"})
        )
        neurons = neurons.join(ref_signs, on="source_id", how="left")
        datasets.append("shiu2024_model")

    # The count tables cover every segment (43M post rows), not just proofread neurons: filter
    # while scanning, then stack pre and post rows instead of joining them (CONN-R-053).
    proofread = pl.Series(root_ids).implode()

    def counts(name: str, id_col: str, side: str) -> pl.LazyFrame:
        other = "post" if side == "pre" else "pre"
        return (
            pl.scan_ipc(conn_dir / name)
            .filter(pl.col(id_col).is_in(proofread))
            .select(
                pl.col(id_col).alias("source_id"),
                pl.col("neuropil"),
                pl.col("count").alias(side),
                pl.lit(0, dtype=pl.Int64).alias(other),
            )
            .select("source_id", "neuropil", "pre", "post")
        )

    neuropils = pl.concat(
        [
            counts("per_neuron_neuropil_count_pre_783.feather", "pre_pt_root_id", "pre"),
            counts("per_neuron_neuropil_count_post_783.feather", "post_pt_root_id", "post"),
        ]
    )

    return BuildInputs(
        sex="female",
        neurons=neurons,
        connections=connections.select(
            pl.col("pre_pt_root_id").alias("pre"),
            pl.col("post_pt_root_id").alias("post"),
            pl.col("syn_count"),
        ),
        neuropils=neuropils,
        provenance=_provenance(datasets, raw_root),
        notes={
            "nt_source": nt_source,
            "sign_source": sign_source,
            "neuron_set": "proofread_root_ids_783.npy",
        },
        mb_neuropils=tuple(registry.get("conn.fafb.mb_neuropils")),
        cx_neuropils=tuple(registry.get("conn.fafb.cx_neuropils")),
        extra_neuron_columns=("dimorphism", "hemibrain_type"),
    )


# --- entry point ---------------------------------------------------------------------------


def build_for_sex(sex: str, template_id: str | None = None, log=print) -> dict:
    cfgs = load_all()
    colony = cfgs["colony.yaml"]
    root = project_root()
    raw_root = root / colony.paths.data_raw
    out_root = root / colony.paths.templates
    registry = Registry.load()
    iomap_dir = root / "config" / "iomap" / sex
    iomap = load_iomap(iomap_dir) if iomap_dir.exists() else None

    if sex == "female":
        template_id = template_id or colony.templates.female
        log(f"building {template_id} from FAFB v783")
        inputs = fafb_inputs(raw_root, registry)
        expected = {
            "neurons": int(registry.get("conn.expected.fafb783.neurons")),
            "synapses": int(registry.get("conn.expected.fafb783.synapses")),
            "tolerance": float(registry.get("conn.expected.tolerance")),
        }
    elif sex == "male":
        from flycolony.connectome.male import malecns_inputs

        template_id = template_id or colony.templates.male
        log(f"building {template_id} from MaleCNS v1.0 (brain portion)")
        inputs = malecns_inputs(raw_root, registry)
        expected = None  # recorded beside the full-CNS figure, not enforced (CONN-R-060)
    else:
        raise ValueError("sex must be 'female' or 'male'")
    return build_template(inputs, registry, template_id, out_root, iomap=iomap, expected=expected)
