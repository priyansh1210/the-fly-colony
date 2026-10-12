"""T-CONN-U-006 (registry) and T-CONN-U-007 (config schemas)."""

from __future__ import annotations

import textwrap

import pytest

from flycolony.config import ConfigError, config_snapshot, load_all, load_config
from flycolony.config.schemas import ColonyConfig, Genesis, HardwareConfig
from flycolony.registry import Registry, RegistryError, apply_calibration
from flycolony.registry.registry import Entry

GOOD = dict(
    id="brain.lif.v_thresh",
    value=-45.0,
    units="mV",
    valid_range=(-70.0, -20.0),
    source={"authors": "Kakaria & de Bivort", "year": 2017},
    owner_spec="002",
)


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


# --- registry --------------------------------------------------------------------------------


def test_real_registry_loads(registry):
    assert len(registry) > 0
    assert len(registry.content_hash()) == 64


def test_entry_needs_exactly_one_of_source_or_assumption():
    Entry(**GOOD)
    with pytest.raises(ValueError, match="exactly one"):
        Entry(**{**GOOD, "source": None})
    with pytest.raises(ValueError, match="exactly one"):
        Entry(**GOOD, assumption={"rationale": "x", "owner": "002"})


@pytest.mark.parametrize(
    "bad",
    [
        {"value": -10.0},  # out of range
        {"scope": "fly:F012"},  # per-fly scope does not exist (CONST-1.3)
        {"id": "NoDots"},
        {"valid_range": (5.0, 1.0)},
    ],
)
def test_entry_rules(bad):
    with pytest.raises(ValueError):
        Entry(**{**GOOD, **bad})


def test_require_reports_missing_and_out_of_range():
    reg = Registry([Entry(**GOOD)])
    reg.require({"brain.lif.v_thresh"})
    with pytest.raises(RegistryError, match=r"missing: brain.lif.tau"):
        reg.require({"brain.lif.v_thresh", "brain.lif.tau"})


def test_file_errors_carry_line_numbers(tmp_path):
    write(
        tmp_path,
        "x.yaml",
        """\
        entries:
          - id: a.b
            value: 3
            units: s
            valid_range: [0, 1]
            assumption: {rationale: r, owner: o}
        """,
    )
    with pytest.raises(ConfigError, match=r"x\.yaml:\d+"):
        Registry.load(tmp_path)


def test_duplicate_ids_refused():
    with pytest.raises(RegistryError, match="duplicate"):
        Registry([Entry(**GOOD), Entry(**GOOD)])


def test_assumption_report():
    reg = Registry(
        [
            Entry(**GOOD),
            Entry(
                id="brain.x.y",
                value=1,
                units="u",
                owner_spec="002",
                assumption={"rationale": "r", "owner": "002"},
            ),
            Entry(
                id="conn.z.w",
                value=1,
                units="u",
                owner_spec="001",
                assumption={"rationale": "r", "owner": "001"},
            ),
        ]
    )
    rows = {r["owner_spec"]: r for r in reg.assumption_report()}
    assert rows["002"]["entries"] == 2 and rows["002"]["assumptions"] == 1
    assert rows["001"]["share"] == 1.0


def test_calibration_records_run_and_respects_rules():
    reg = Registry([Entry(**GOOD)])
    new = apply_calibration(reg, {"brain.lif.v_thresh": -50.0}, "cal-001", "sugar evokes feeding")
    e = new.entry("brain.lif.v_thresh")
    assert e.value == -50.0 and e.calibrated.run_id == "cal-001"
    assert reg.get("brain.lif.v_thresh") == -45.0  # original untouched
    assert new.content_hash() != reg.content_hash()
    with pytest.raises(RegistryError, match="unknown"):
        apply_calibration(reg, {"brain.nope.x": 1}, "cal", "obj")
    with pytest.raises(RegistryError, match="rejected"):
        apply_calibration(reg, {"brain.lif.v_thresh": 0.0}, "cal", "obj")
    with pytest.raises(RegistryError, match="run_id"):
        apply_calibration(reg, {"brain.lif.v_thresh": -50.0}, "", "obj")


# --- config ----------------------------------------------------------------------------------


def test_project_configs_load():
    cfgs = load_all()
    assert cfgs["genesis.yaml"].count == 100
    _text, digest = config_snapshot(cfgs)
    assert len(digest) == 64 and config_snapshot(load_all())[1] == digest


def test_unknown_key_rejected_with_line(tmp_path):
    p = write(
        tmp_path,
        "colony.yaml",
        """\
        seed: 1
        paths:
          templates: x
          florbs: y
        """,
    )
    with pytest.raises(ConfigError) as exc:
        load_config(ColonyConfig, p)
    assert "colony.yaml:4" in str(exc.value) and "florbs" in str(exc.value)


@pytest.mark.parametrize(
    "model,text,needle",
    [
        (ColonyConfig, "clock: {fly_day_neural_s: -5}\n", "fly_day_neural_s"),
        (Genesis, "count: 100\nmales: 60\nfemales: 30\n", r"males \+ females"),
        (HardwareConfig, "device: gpu7\n", "device"),
        (HardwareConfig, "tiers: {low_below_gb: 20, mid_below_gb: 12}\n", "thresholds"),
    ],
)
def test_bad_values_rejected(tmp_path, model, text, needle):
    p = write(tmp_path, "c.yaml", text)
    with pytest.raises(ConfigError, match=needle):
        load_config(model, p)
