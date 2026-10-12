"""T-CONN-U-004 (I/O map), T-CONN-U-005 (license gate), T-CONN-U-009 (credentials)."""

from __future__ import annotations

import json
import textwrap

import pytest

from flycolony.config.schemas import project_root
from flycolony.connectome.datasets import (
    Catalog,
    LicenseError,
    load_catalog,
    redact,
    render_licenses_md,
    require_license,
)
from flycolony.connectome.iomap import IoMap, IoMapError, load_iomap
from flycolony.connectome.template import build_template, load_template

ROOT = project_root()


def iomap(entries) -> IoMap:
    return IoMap.model_validate({"version": "test", "entries": entries})


SUGAR = {
    "name": "taste.sugar",
    "kind": "sense",
    "select": {"cell_type": ["Gr5a"]},
    "citation": "test",
}
GF = {
    "name": "escape.takeoff",
    "kind": "motor",
    "select": {"cell_type": ["DNp01"]},
    "citation": "test",
}


def test_valid_map_resolves_with_coverage(tmp_path, synth, registry):
    report = build_template(synth, registry, "io-t1", tmp_path, iomap=iomap([SUGAR, GF]))
    tpl = load_template(tmp_path / "io-t1")
    data = json.loads((tpl.path / "iomap.json").read_text())
    by_name = {e["name"]: e for e in data["entries"]}
    gr5a = set(tpl.neurons.filter(tpl.neurons["cell_type"] == "Gr5a")["neuron_id"].to_list())
    assert set(by_name["taste.sugar"]["neuron_ids"]) == gr5a
    cov = report["coverage"]
    assert cov["descending"]["total"] == int(tpl.neurons["is_descending"].sum())
    assert cov["descending"]["mapped"] + cov["descending"]["unmapped"] == cov["descending"]["total"]


def test_bad_reference_fails_listing_all(tmp_path, synth, registry):
    bad = [
        SUGAR,
        {**GF, "select": {"cell_type": ["DNp01", "NotAType"]}},
        {"name": "x.y", "kind": "sense", "select": {"source_id": [123]}, "citation": "test"},
    ]
    with pytest.raises(IoMapError) as exc:
        build_template(synth, registry, "io-t2", tmp_path, iomap=iomap(bad))
    msg = str(exc.value)
    assert "NotAType" in msg and "source_id=123" in msg
    assert not (tmp_path / "io-t2").exists()  # nothing published


def test_selector_needs_exactly_one_kind():
    with pytest.raises(ValueError, match="exactly one"):
        iomap([{**SUGAR, "select": {"cell_type": ["a"], "cell_class": ["b"]}}])
    with pytest.raises(ValueError):
        iomap([{**SUGAR, "citation": ""}])


def test_iomap_files_load(tmp_path):
    (tmp_path / "senses.yaml").write_text(
        textwrap.dedent("""\
        version: "0.1"
        entries:
          - {name: taste.sugar, kind: sense, select: {cell_type: [Gr5a]}, citation: test}
        """),
        encoding="utf-8",
    )
    assert load_iomap(tmp_path).entries[0].name == "taste.sugar"


# --- licenses (T-CONN-U-005) -----------------------------------------------------------------


def test_every_catalog_dataset_has_a_license():
    cat = load_catalog()
    for ds_id in cat.datasets:
        require_license(cat, ds_id)


def test_missing_license_refused():
    cat = Catalog.model_validate(
        {
            "datasets": {
                "x": {
                    "title": "t",
                    "version": "1",
                    "homepage": "h",
                    "files": [{"name": "a", "url": "u"}],
                }
            }
        }
    )
    with pytest.raises(LicenseError, match="no license"):
        require_license(cat, "x")
    with pytest.raises(LicenseError, match="not in the catalog"):
        require_license(cat, "y")
    assert "MISSING" in render_licenses_md(cat)


def test_licenses_md_is_up_to_date():
    rendered = render_licenses_md(load_catalog())
    assert (ROOT / "data" / "LICENSES.md").read_text(encoding="utf-8") == rendered, (
        "run `colony data licenses` to regenerate data/LICENSES.md"
    )


# --- credentials (T-CONN-U-009) --------------------------------------------------------------


def test_credentials_are_redacted(monkeypatch):
    monkeypatch.setenv("NEUPRINT_APPLICATION_CREDENTIALS", "s3cr3t-value-123")
    text = "GET https://x?token=abc123 Authorization: Bearer zzz with s3cr3t-value-123"
    out = redact(text)
    assert "s3cr3t-value-123" not in out and "abc123" not in out and "zzz" not in out


def test_no_credentials_in_catalog_or_sources():
    text = (ROOT / "config" / "datasets.yaml").read_text(encoding="utf-8")
    assert redact(text) == text
    for src in (ROOT / "data" / "raw").glob("*/_source.json"):
        body = src.read_text(encoding="utf-8")
        assert redact(body) == body
