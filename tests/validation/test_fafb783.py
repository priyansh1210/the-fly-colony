"""T-CONN-V-001: the female FAFB v783 template against published counts and the Shiu reference.

Runs on the real template under data/templates (built with `colony template build female`);
skipped when the template or the reference data is absent.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from flycolony.config import load_all
from flycolony.connectome.template import load_template
from tests.conftest import RAW, ROOT

pytestmark = pytest.mark.data

_CFG = load_all()["colony.yaml"]
TEMPLATE = ROOT / _CFG.paths.templates / _CFG.templates.female
SHIU = RAW / "shiu2024_model" / "Connectivity_783.parquet"


@pytest.fixture(scope="module")
def tpl():
    if not (TEMPLATE / "manifest.json").exists():
        pytest.skip("female template not built (colony template build female)")
    return load_template(TEMPLATE)


@pytest.fixture(scope="module")
def shiu():
    if not SHIU.exists():
        pytest.skip("shiu2024_model not fetched")
    return pl.read_parquet(
        SHIU, columns=["Presynaptic_ID", "Postsynaptic_ID", "Connectivity", "Excitatory"]
    )


def test_neuron_count_exact(tpl, registry):  # CONN-AC-01
    assert tpl.n_neurons == registry.get("conn.expected.fafb783.neurons")


def test_synapse_count_within_tolerance(tpl, registry):  # CONN-AC-01
    expected = registry.get("conn.expected.fafb783.synapses")
    got = int(tpl.edges["syn_count"].sum(dtype=np.int64))
    assert abs(got - expected) / expected <= registry.get("conn.expected.tolerance")


def _edges(tpl) -> pl.DataFrame:
    src = tpl.neurons["source_id"].to_numpy()
    e = tpl.edges
    pre = np.repeat(np.arange(tpl.n_neurons), np.diff(e["indptr"]))
    return pl.DataFrame(
        {
            "pre": src[pre],
            "post": src[e["indices"]],
            "syn": e["syn_count"],
            "sign": np.sign(e["weight"]).astype(np.int64),
        }
    )


def test_edges_match_reference(tpl, shiu):
    """Same (pre, post) pairs and synapse counts as the Shiu et al. 2024 model inputs."""
    ours = _edges(tpl)
    joined = ours.join(
        shiu,
        left_on=["pre", "post"],
        right_on=["Presynaptic_ID", "Postsynaptic_ID"],
        how="full",
        coalesce=True,
    )
    only_ours = joined.filter(pl.col("Connectivity").is_null()).height
    only_ref = joined.filter(pl.col("syn").is_null()).height
    both = joined.drop_nulls(["syn", "Connectivity"])
    assert only_ours == 0 and only_ref == 0, (
        f"pairs only in template={only_ours}, only in ref={only_ref}"
    )
    assert (both["syn"] == both["Connectivity"]).all()


def test_signs_agree_with_reference(tpl, shiu):
    """Per-presynaptic-neuron sign agreement with the reference (target >= 99%)."""
    ours = _edges(tpl).group_by("pre").agg(pl.col("sign").first())
    ref = shiu.group_by("Presynaptic_ID").agg(pl.col("Excitatory").first())
    j = ours.join(ref, left_on="pre", right_on="Presynaptic_ID", how="inner")
    agreement = (j["sign"] == j["Excitatory"]).mean()
    assert agreement >= 0.99, f"sign agreement {agreement:.4f}"


def test_every_neuron_has_fractions_and_primary_neuropil(tpl):
    fr = pl.read_parquet(tpl.path / "neuropil_fractions.parquet")
    assert fr["neuron_id"].n_unique() >= 0.99 * tpl.n_neurons
    assert tpl.neurons["primary_neuropil"].null_count() <= 0.01 * tpl.n_neurons
