"""Real-data checks for peptidergic lists (CONN-R-015) and the I/O map (CONN-R-020..022, AC-06)."""

from __future__ import annotations

import json

import polars as pl
import pytest

from flycolony.config import load_all
from tests.conftest import ROOT

pytestmark = pytest.mark.data

_CFG = load_all()["colony.yaml"]
TEMPLATES = ROOT / _CFG.paths.templates
SEXES = {"female": _CFG.templates.female, "male": _CFG.templates.male}
NAMED_IN_002 = {"NPF", "sNPF", "Tk", "DH44", "ILP", "Crz"}  # AKH and SP: not in brain (vocab)


def _tpl(sex: str):
    path = TEMPLATES / SEXES[sex]
    if not (path / "manifest.json").exists():
        pytest.skip(f"{SEXES[sex]} not built")
    return path


@pytest.mark.parametrize("sex", ["female", "male"])
def test_peptide_lists(sex):
    path = _tpl(sex)
    mod = pl.read_parquet(path / "modulatory.parquet")
    peptides = mod.filter(~pl.col("substance").is_in(["dopamine", "serotonin", "octopamine"]))
    assert set(peptides["substance"].unique().to_list()) >= NAMED_IN_002
    assert peptides["substance"].n_unique() >= 25
    assert peptides["source_ref"].str.len_chars().min() > 3  # every row cites something
    if sex == "male":
        assert peptides["source_ref"].str.contains("inferred for MaleCNS").all()
    # is_modulatory covers aminergic and peptidergic neurons
    n = pl.read_parquet(path / "neurons.parquet", columns=["neuron_id", "is_modulatory"])
    flagged = set(n.filter(pl.col("is_modulatory"))["neuron_id"].to_list())
    assert flagged == set(mod["neuron_id"].to_list())


@pytest.mark.parametrize("sex", ["female", "male"])
def test_iomap_coverage_and_key_channels(sex):
    path = _tpl(sex)
    io = json.loads((path / "iomap.json").read_text(encoding="utf-8"))
    cov = io["coverage"]
    assert cov["sensory"]["share_mapped"] >= 0.85
    assert cov["motor_neurons"]["share_mapped"] >= 0.95
    assert cov["overlaps"] == {"sense": 0, "motor": 0, "interoceptive": 0}
    names = {e["name"]: len(e["neuron_ids"]) for e in io["entries"]}
    for key in (
        "taste.labellar.sugar",
        "taste.labellar.bitter",
        "taste.labellar.water",
        "vision.photoreceptor.r1_6",
        "vision.dorsal_rim",
        "mechano.jo.auditory",
        "thermo.heating",
        "hygro.dry",
        "escape.takeoff",
        "walk.backward",
        "feeding.proboscis_extension",
        "clock.l_lnv",
    ):
        assert names.get(key, 0) > 0, key
    assert sum(k.startswith("olfaction.orn.") for k in names) >= 50
    assert names["escape.takeoff"] == 2  # one Giant Fiber per side
    assert ("wing.song" in names) == (sex == "male")
    assert ("oviposition" in names) == (sex == "female")
    assert all(e["citation"] for e in io["entries"])
