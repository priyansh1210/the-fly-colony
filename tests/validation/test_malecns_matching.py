"""T-CONN-V-002 (MaleCNS brain portion) and T-CONN-V-003 (cross-dataset matching).

Runs on the real artifacts under data/templates; skipped when they have not been built.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from flycolony.config import load_all
from flycolony.connectome.template import load_template
from tests.conftest import ROOT

pytestmark = pytest.mark.data

TEMPLATES = ROOT / load_all()["colony.yaml"].paths.templates
MALE = TEMPLATES / "male-malecns1-t1"
MATCH = TEMPLATES / "match__female-fafb783-t1__male-malecns1-t1"


@pytest.fixture(scope="module")
def male():
    if not (MALE / "manifest.json").exists():
        pytest.skip("male template not built (colony template build male)")
    return load_template(MALE)


@pytest.fixture(scope="module")
def match():
    if not (MATCH / "manifest.json").exists():
        pytest.skip("matching not built (colony template match)")
    return json.loads((MATCH / "manifest.json").read_text(encoding="utf-8"))


def test_brain_portion_rule_recorded(male, registry):  # CONN-R-016, CONN-R-060
    notes = male.manifest["notes"]
    assert "brain_portion_rule" in notes
    assert notes["kept"] == male.n_neurons
    assert notes["kept"] == (
        notes["kept_by_share"] + notes["kept_as_interface_only"] + notes["kept_as_sensory_only"]
    )
    # Brain portion is a strict subset of the traced CNS, recorded beside the published figure.
    assert male.n_neurons < notes["traced_bodies"] <= notes["full_cns_neurons_published"]


def test_all_descending_and_ascending_kept(male):  # CONN-R-016
    n = male.neurons
    assert n.filter(pl.col("super_class") == "descending").height >= 1300
    assert n.filter(pl.col("super_class") == "ascending").height >= 1800


def test_male_specific_types_present(male):  # CONN-AC-02
    n = male.neurons
    male_specific = n.filter(pl.col("dimorphism").str.contains("male-specific").fill_null(False))
    assert male_specific["cell_type"].n_unique() >= 250
    p1_cluster = n.filter(pl.col("cell_type").str.starts_with("pC1_").fill_null(False))
    assert p1_cluster.height >= 100  # P1/pC1 (pMP4) cluster
    assert n.filter(pl.col("cell_type") == "pIP10").height == 2  # male song command neuron


def test_neuron_level_sets_are_populated(male):  # CONN-R-040 flags used by 014
    n = male.neurons
    assert n["in_mb"].sum() > 3000 and n["in_cx"].sum() > 2000
    kc = n.filter(pl.col("cell_class") == "Kenyon_Cell")
    assert kc["in_mb"].mean() > 0.9


def test_matching_coverage(match):  # CONN-R-030
    assert match["matched_male_types"] / match["male_types"] >= 0.8
    assert match["male_neurons_in_matched_types"] / match["male_typed_neurons"] >= 0.9
    assert match["male_specific_types"] > 0


def test_normalization_factor_recorded(match, registry):  # CONN-R-031
    scale = match["normalization"]["male_scale"]
    assert 0.2 < scale < 1.5
    assert registry.get("conn.norm.male_scale") == pytest.approx(scale, rel=1e-6)


def test_discrepancy_report(match):  # CONN-R-032
    d = pl.read_parquet(MATCH / "discrepancies.parquet")
    assert d.height == match["discrepancies"]
    factor, scale = match["discrepancy_factor"], match["normalization"]["male_scale"]
    assert ((d["in_ratio"] > factor * scale) | (d["in_ratio"] < scale / factor)).all()
