"""T-CONN-U-001/002/003/008 and T-CONN-I-001/002 on a synthetic connectome."""

from __future__ import annotations

import json

import numpy as np
import polars as pl
import pytest

from flycolony.connectome.inputs import BuildInputs
from flycolony.connectome.template import (
    OUTPUT_FILES,
    TemplateError,
    TemplateIntegrityError,
    build_template,
    load_template,
)
from flycolony.registry import apply_calibration
from tests.conftest import synthetic_inputs

REQUIRED_COLUMNS = {
    "neuron_id",
    "source_id",
    "cell_type",
    "super_class",
    "cell_class",
    "side",
    "primary_neuropil",
    "nt_pred",
    "nt_conf",
    "sign",
    "model",
    "is_sensory",
    "is_descending",
    "is_ascending",
    "is_motor",
    "is_modulatory",
    "is_neurosecretory",
}


@pytest.fixture
def built(tmp_path, synth, registry):
    report = build_template(synth, registry, "test-t1", tmp_path)
    return load_template(tmp_path / "test-t1"), report


def _edge_list(inputs: BuildInputs, min_syn: int) -> pl.DataFrame:
    """Reference edge list computed independently of the builder."""
    ids = inputs.neurons.collect()["source_id"].sort()
    dense = {int(s): i for i, s in enumerate(ids)}
    c = inputs.connections.collect().group_by("pre", "post").agg(pl.col("syn_count").sum())
    c = c.filter(pl.col("pre").is_in(ids.implode()) & pl.col("post").is_in(ids.implode()))
    c = c.filter(pl.col("syn_count") >= min_syn)
    return c.with_columns(
        pl.col("pre").replace_strict(dense).alias("pre_id"),
        pl.col("post").replace_strict(dense).alias("post_id"),
    ).sort("pre_id", "post_id")


def test_neuron_table_schema(built):  # T-CONN-U-001
    tpl, _ = built
    assert set(tpl.neurons.columns) >= REQUIRED_COLUMNS
    assert tpl.neurons["neuron_id"].to_list() == list(range(tpl.n_neurons))
    assert tpl.neurons["source_id"].is_sorted()


def test_csr_round_trip(built, synth, registry):  # T-CONN-U-001
    tpl, _ = built
    e = tpl.edges
    pre = np.repeat(np.arange(tpl.n_neurons), np.diff(e["indptr"]))
    ref = _edge_list(synth, registry.get("conn.min_synapses"))
    assert np.array_equal(pre, ref["pre_id"].to_numpy())
    assert np.array_equal(e["indices"], ref["post_id"].to_numpy())
    assert np.array_equal(e["syn_count"], ref["syn_count"].to_numpy())
    signs = tpl.neurons["sign"].to_numpy()
    assert np.array_equal(e["weight"], (e["syn_count"] * signs[pre]).astype(np.float32))
    # Transposed index points back at the same edges.
    t_post = np.repeat(np.arange(tpl.n_neurons), np.diff(e["t_indptr"]))
    assert np.array_equal(e["indices"][e["t_perm"]], t_post)
    assert np.array_equal(pre[e["t_perm"]], e["t_indices"])


def test_neuropil_fractions_sum_to_one(built):  # T-CONN-U-001
    tpl, _ = built
    fr = pl.read_parquet(tpl.path / "neuropil_fractions.parquet")
    sums = fr.group_by("neuron_id").agg(
        pl.col("pre_frac").sum(), pl.col("post_frac").sum(), pl.col("pre_count").sum()
    )
    post = sums["post_frac"].to_numpy()
    assert np.allclose(post, 1.0, atol=1e-5)
    with_pre = sums.filter(pl.col("pre_count") > 0)["pre_frac"].to_numpy()
    assert np.allclose(with_pre, 1.0, atol=1e-5)


def test_sign_and_model_rules(built, registry):  # T-CONN-U-002
    tpl, _ = built
    n = tpl.neurons
    for nt in ("acetylcholine", "gaba", "glutamate", "dopamine", "serotonin", "octopamine"):
        assert set(n.filter(pl.col("nt_pred") == nt)["sign"].to_list()) <= {
            registry.get(f"conn.sign.{nt}")
        }
    assert set(n.filter(pl.col("nt_pred").is_null())["sign"].to_list()) == {
        registry.get("conn.sign.unknown")
    }
    graded = set(registry.get("conn.graded_cell_types"))
    for ct, model in n.select("cell_type", "model").iter_rows():
        assert model == ("graded" if ct in graded else "spiking")


def test_sign_exception(tmp_path, synth, registry):  # T-CONN-U-002
    reg = apply_calibration(
        registry, {"conn.sign_exceptions": ["MBON01=-1"]}, "t", "test exception"
    )
    build_template(synth, reg, "exc-t1", tmp_path)
    n = load_template(tmp_path / "exc-t1").neurons
    assert set(n.filter(pl.col("cell_type") == "MBON01")["sign"].to_list()) == {-1}


def test_threshold_applied_and_recorded(tmp_path, registry):  # T-CONN-U-003
    synth = synthetic_inputs()
    reg = apply_calibration(registry, {"conn.min_synapses": 8}, "t", "threshold test")
    report = build_template(synth, reg, "thr-t1", tmp_path)
    tpl = load_template(tmp_path / "thr-t1")
    assert tpl.edges["syn_count"].min() >= 8
    assert tpl.manifest["parameters"]["conn.min_synapses"] == 8
    assert report["counts"]["min_synapses"] == 8
    assert len(tpl.edges["indices"]) == _edge_list(synth, 8).height


def test_type_graph_conserves_weight(built):  # T-CONN-U-008
    tpl, _ = built
    mem = pl.read_parquet(tpl.path / "type_membership.parquet")
    te = pl.read_parquet(tpl.path / "type_edges.parquet")
    nodes = pl.read_parquet(tpl.path / "type_nodes.parquet")
    assert mem["neuron_id"].to_list() == list(range(tpl.n_neurons))  # complete membership
    assert nodes["n_neurons"].sum() == tpl.n_neurons
    node_of = mem["node_id"].to_numpy()
    e = tpl.edges
    pre = np.repeat(np.arange(tpl.n_neurons), np.diff(e["indptr"]))
    ref = (
        pl.DataFrame(
            {"a": node_of[pre], "b": node_of[e["indices"]], "w": e["weight"].astype(np.float64)}
        )
        .group_by("a", "b")
        .agg(pl.col("w").sum())
        .sort("a", "b")
    )
    assert np.allclose(te["weight"].to_numpy(), ref["w"].to_numpy())
    assert np.isclose(te["weight"].sum(), e["weight"].astype(np.float64).sum())
    # Untyped neurons are singleton nodes.
    untyped = nodes.filter(pl.col("node_type").str.starts_with("untyped:"))
    assert (untyped["n_neurons"] == 1).all()


def test_tamper_is_detected(built):  # T-CONN-I-001 / CONN-AC-03
    tpl, _ = built
    for name in OUTPUT_FILES:
        f = tpl.path / name
        data = bytearray(f.read_bytes())
        data[len(data) // 2] ^= 0x01
        f.write_bytes(bytes(data))
        with pytest.raises(TemplateIntegrityError, match=name):
            load_template(tpl.path)
        data[len(data) // 2] ^= 0x01
        f.write_bytes(bytes(data))
    load_template(tpl.path)  # restored -> loads again


def test_manifest_contents(built, registry):  # T-CONN-I-001
    tpl, _ = built
    m = tpl.manifest
    assert m["registry_hash"] == registry.content_hash()
    assert set(m["outputs"]) == set(OUTPUT_FILES)
    assert m["inputs"] == {"synthetic": {"seed": 7}}
    assert m["counts"]["neurons"] == tpl.n_neurons
    assert "retrieved" not in json.dumps(m)  # no timestamps -> deterministic


def test_rebuild_is_byte_identical(tmp_path, registry):  # T-CONN-I-002 / CONN-AC-04
    build_template(synthetic_inputs(), registry, "a-t1", tmp_path)
    build_template(synthetic_inputs(), registry, "b-t1", tmp_path)
    for name in (*OUTPUT_FILES,):
        assert (tmp_path / "a-t1" / name).read_bytes() == (tmp_path / "b-t1" / name).read_bytes(), (
            name
        )
    ma = json.loads((tmp_path / "a-t1" / "manifest.json").read_text())
    mb = json.loads((tmp_path / "b-t1" / "manifest.json").read_text())
    ma.pop("template_id"), mb.pop("template_id")
    assert ma == mb


def test_templates_are_immutable(built, synth, registry, tmp_path):  # CONN-R-054
    with pytest.raises(TemplateError, match="immutable"):
        build_template(synth, registry, "test-t1", tmp_path)


def test_count_validation(tmp_path, synth, registry):  # CONN-R-060
    with pytest.raises(TemplateError, match="count validation"):
        build_template(synth, registry, "cnt-t1", tmp_path, expected={"neurons": 41})
    report = build_template(
        synthetic_inputs(), registry, "cnt-t2", tmp_path, expected={"neurons": 40}
    )
    assert report["counts"]["neurons"] == 40


def test_peak_rss_reported(built):  # T-CONN-P-001 (mechanism)
    _, report = built
    assert 0 < report["peak_rss_gb"] < report["max_rss_gb"]


def test_sign_precedence_reference_then_transmitter(tmp_path, registry):  # T-CONN-U-002
    synth = synthetic_inputs()
    ids = synth.neurons.collect()["source_id"].to_list()
    # Reference covers the first half of the neurons and says "inhibitory" for all of them.
    ref = pl.DataFrame({"source_id": ids[:20], "sign_ref": [-1] * 20}).lazy()
    synth.neurons = synth.neurons.join(ref, on="source_id", how="left")
    reg = apply_calibration(registry, {"conn.sign_exceptions": ["MBON01=1"]}, "t", "precedence")
    build_template(synth, reg, "ref-t1", tmp_path)
    n = load_template(tmp_path / "ref-t1").neurons
    exc = n.filter(pl.col("cell_type") == "MBON01")
    assert set(exc["sign"].to_list()) == {1} and set(exc["sign_source"].to_list()) == {"exception"}
    covered = n.filter(pl.col("source_id").is_in(ids[:20]) & (pl.col("cell_type") != "MBON01"))
    assert set(covered["sign"].to_list()) == {-1}
    assert set(covered["sign_source"].to_list()) == {"reference"}
    rest = n.filter(~pl.col("source_id").is_in(ids[:20]) & (pl.col("cell_type") != "MBON01"))
    assert set(rest["sign_source"].to_list()) == {"transmitter"}


def test_text_outputs_use_lf_on_every_os(built):  # portability: same bytes on Windows and Linux
    tpl, _ = built
    for name in ("iomap.json", "manifest.json"):
        assert b"\r" not in (tpl.path / name).read_bytes(), name
