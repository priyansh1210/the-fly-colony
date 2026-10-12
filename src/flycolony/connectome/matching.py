"""Cross-dataset cell-type matching and weight normalization (spec 001 §4.4, design §5.2).

Correspondence comes from the published MaleCNS -> FlyWire matching (`flywireType` on every
MaleCNS neuron). Output is an immutable, checksummed artifact like a template.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from flycolony.connectome.template import (
    BrainTemplate,
    TemplateError,
    _json,
    pipeline_version,
    sha256_file,
    write_parquet,
)
from flycolony.registry import Registry

MATCH_FILES = ("type_match.parquet", "type_stats.parquet", "discrepancies.parquet")


def _type_stats(tpl: BrainTemplate) -> pl.DataFrame:
    """Per cell type: neuron count and mean input/output synapses per neuron."""
    e = tpl.edges
    n = tpl.n_neurons
    out_syn = np.bincount(
        np.repeat(np.arange(n), np.diff(e["indptr"])), weights=e["syn_count"], minlength=n
    )
    in_syn = np.bincount(e["indices"], weights=e["syn_count"], minlength=n)
    return (
        tpl.neurons.select("cell_type")
        .with_columns(pl.Series("in_syn", in_syn), pl.Series("out_syn", out_syn))
        .drop_nulls("cell_type")
        .group_by("cell_type")
        .agg(
            pl.len().alias("n_neurons"),
            pl.col("in_syn").mean().alias("mean_in"),
            pl.col("out_syn").mean().alias("mean_out"),
        )
        .sort("cell_type")
    )


def _male_to_female(male: BrainTemplate) -> pl.DataFrame:
    """Each male type -> its most common flywireType (ties broken alphabetically)."""
    return (
        male.neurons.drop_nulls(["cell_type", "flywire_type"])
        .group_by("cell_type", "flywire_type")
        .agg(pl.len().alias("n"))
        .sort(["cell_type", "n", "flywire_type"], descending=[False, True, False])
        .group_by("cell_type", maintain_order=True)
        .first()
        .select(pl.col("cell_type").alias("male_type"), pl.col("flywire_type").alias("female_type"))
    )


def build_matching(
    female: BrainTemplate, male: BrainTemplate, registry: Registry, out_root: Path
) -> dict:
    match_id = f"match__{female.template_id}__{male.template_id}"
    out = Path(out_root) / match_id
    if out.exists():
        raise TemplateError(f"{out} already exists; matching artifacts are immutable")

    fstats, mstats = _type_stats(female), _type_stats(male)
    female_types = set(fstats["cell_type"].to_list())
    pairs = _male_to_female(male)
    match = (
        mstats.select(pl.col("cell_type").alias("male_type"))
        .join(pairs, on="male_type", how="left")
        .with_columns(
            pl.col("female_type").is_in(list(female_types)).fill_null(False).alias("matched"),
            pl.lit("malecns.flywireType").alias("match_source"),
        )
    )
    male_specific = set(
        male.neurons.filter(pl.col("dimorphism").str.contains("male-specific").fill_null(False))[
            "cell_type"
        ]
        .drop_nulls()
        .to_list()
    )
    match = match.with_columns(
        (pl.col("male_type").is_in(list(male_specific)) & ~pl.col("matched")).alias("male_specific")
    ).sort("male_type")

    # Female-only types: present in FAFB but no male type maps onto them.
    matched_female = set(match.filter(pl.col("matched"))["female_type"].to_list())
    female_only = sorted(female_types - matched_female)

    joined = (
        match.filter(pl.col("matched"))
        .join(mstats.rename({"cell_type": "male_type"}), on="male_type")
        .join(
            fstats.rename(
                {
                    "cell_type": "female_type",
                    "n_neurons": "f_n",
                    "mean_in": "f_in",
                    "mean_out": "f_out",
                }
            ),
            on="female_type",
        )
        .filter((pl.col("mean_in") > 0) & (pl.col("f_in") > 0))
        .with_columns((pl.col("f_in") / pl.col("mean_in")).alias("in_ratio"))
    )
    scale = float(joined["in_ratio"].median())
    factor = float(registry.get("conn.match.discrepancy_factor"))
    discrepancies = joined.filter(
        (pl.col("in_ratio") > factor * scale) | (pl.col("in_ratio") < scale / factor)
    ).sort("male_type")

    n_male_typed = male.neurons["cell_type"].is_not_null().sum()
    matched_neurons = male.neurons.filter(
        pl.col("cell_type").is_in(match.filter(pl.col("matched"))["male_type"].to_list())
    ).height
    summary = {
        "match_id": match_id,
        "pipeline_version": pipeline_version(),
        "female_template": female.template_id,
        "male_template": male.template_id,
        "female_types": len(female_types),
        "male_types": mstats.height,
        "matched_male_types": int(match["matched"].sum()),
        "male_specific_types": int(match["male_specific"].sum()),
        "female_only_types": len(female_only),
        "female_only_examples": female_only[:50],
        "male_neurons_in_matched_types": matched_neurons,
        "male_typed_neurons": int(n_male_typed),
        "normalization": {
            "method": "global scale = median over matched types of (female mean input synapses "
            "per neuron / male mean input synapses per neuron)",
            "male_scale": round(scale, 6),
            "types_used": joined.height,
        },
        "discrepancy_factor": factor,
        "discrepancies": discrepancies.height,
    }

    tmp = out.with_name(out.name + ".building")
    tmp.mkdir(parents=True, exist_ok=True)
    write_parquet(match, tmp / "type_match.parquet")
    write_parquet(joined.sort("male_type"), tmp / "type_stats.parquet")
    write_parquet(discrepancies, tmp / "discrepancies.parquet")
    summary["outputs"] = {name: sha256_file(tmp / name) for name in MATCH_FILES}
    (tmp / "manifest.json").write_text(_json(summary), encoding="utf-8", newline="\n")
    tmp.rename(out)
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))
