"""Cell-type-level graph for HYBRID and COARSE fidelity (spec 001 §4.5, design §5.3)."""

from __future__ import annotations

import numpy as np
import polars as pl


def build_type_graph(
    neurons: pl.DataFrame, edges: dict[str, np.ndarray]
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Return (type_nodes, type_edges, type_membership).

    Node key = (cell_type, side); untyped neurons become singleton nodes `untyped:<source_id>`.
    Edge weight = sum of signed neuron-level weights between the two nodes, so total signed
    weight between any node pair is conserved by construction (CONN-R-041).
    """
    keyed = neurons.select(
        "neuron_id",
        pl.coalesce(
            pl.col("cell_type"), pl.lit("untyped:") + pl.col("source_id").cast(pl.String)
        ).alias("node_type"),
        pl.col("side").fill_null("NA"),
        "in_mb",
        "in_cx",
        "is_io",
    )
    nodes = (
        keyed.group_by("node_type", "side")
        .agg(
            pl.len().alias("n_neurons").cast(pl.Int32),
            pl.col("in_mb").sum().alias("n_in_mb").cast(pl.Int32),
            pl.col("in_cx").sum().alias("n_in_cx").cast(pl.Int32),
            pl.col("is_io").sum().alias("n_io").cast(pl.Int32),
        )
        .sort("node_type", "side")
        .with_row_index("node_id")
        .with_columns(pl.col("node_id").cast(pl.Int32))
    )
    membership = (
        keyed.join(nodes.select("node_type", "side", "node_id"), on=["node_type", "side"])
        .select("neuron_id", "node_id")
        .sort("neuron_id")
    )

    node_of = membership["node_id"].to_numpy()
    indptr = edges["indptr"]
    pre = np.repeat(np.arange(len(indptr) - 1, dtype=np.int32), np.diff(indptr))
    type_edges = (
        pl.DataFrame(
            {
                "pre_node": node_of[pre],
                "post_node": node_of[edges["indices"]],
                "weight": edges["weight"].astype(np.float64),
                "syn_count": edges["syn_count"].astype(np.int64),
            }
        )
        .group_by("pre_node", "post_node")
        .agg(pl.col("weight").sum(), pl.col("syn_count").sum(), pl.len().alias("n_pairs"))
        .sort("pre_node", "post_node")
    )
    return nodes, type_edges, membership
