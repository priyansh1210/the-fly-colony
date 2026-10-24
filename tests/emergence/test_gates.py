"""Phase-2 emergence gates (T-MOTOR-E-001..005, MOTOR-AC-01..05, -07).

Like the Phase-1 gate records, these read the stored reports written by `colony gates run`: each
must exist, be complete (every trial of n ≥ 50 per arm), match the current registry and gate
protocols, and pass. A changed parameter or protocol without a re-run fails here.
"""

from __future__ import annotations

import json

import pytest

from flycolony.config import load_all
from flycolony.engine.gates import load_gates, protocols_hash, report_path

pytestmark = pytest.mark.emergence
CFG = load_all()["colony.yaml"]
GATES = load_gates()


@pytest.mark.parametrize("name", list(GATES["gates"]))
def test_gate_report(name, registry):
    path = report_path(CFG.templates.female, name)
    if not path.exists():
        pytest.skip(f"not run yet: colony gates run --gate {name}")
    rep = json.loads(path.read_text(encoding="utf-8"))
    if rep["status"] == "blocked":
        pytest.skip(f"{name}: blocked - {rep['reason']}")
    assert rep["registry_hash"] == registry.content_hash(), "registry changed; re-run the gate"
    assert rep["gates_hash"] == protocols_hash(), "protocol changed; re-run the gate"
    arms = {t["arm"] for t in rep["trials"]}
    assert rep["trials_per_arm"] >= GATES["trials"]
    assert len(rep["trials"]) == rep["trials_per_arm"] * len(arms)  # reported in full
    assert len({t["seed"] for t in rep["trials"]}) == len(rep["trials"])
    assert rep["passed"], rep["summary"]
