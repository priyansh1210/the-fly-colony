"""Gate runner plumbing on the real template: every gate, 2 trials, 30 ms (005 M9)."""

from __future__ import annotations

import copy

import pytest
import torch

from flycolony.brain.build import template_path
from flycolony.config import load_all
from flycolony.connectome.template import load_template
from flycolony.engine.gates import load_gates, run_gate

pytestmark = [pytest.mark.data, pytest.mark.gpu]


def test_every_gate_runs_end_to_end(registry):
    if not torch.cuda.is_available():
        pytest.skip("needs a CUDA device")
    cfg = load_all()["colony.yaml"]
    path = template_path(cfg, "female")
    if not (path / "manifest.json").exists():
        pytest.skip("female template not built")
    tpl = load_template(path)
    protocols = copy.deepcopy(load_gates())
    for g in protocols["gates"].values():
        g["seconds"] = 0.03
    dev = torch.device("cuda")  # device-ok: gpu-marked validation test
    for name in protocols["gates"]:
        rep = run_gate(name, tpl, cfg, registry, dev, trials=2, write=False, protocols=protocols)
        if rep["status"] == "blocked":
            assert name == "looming"
            continue
        arms = 1 if name == "no_self_motion" else 2
        assert len(rep["trials"]) == 2 * arms, name
        assert len({t["seed"] for t in rep["trials"]}) == 2 * arms  # every trial its own fly
        assert rep["summary"]["passed"] in (True, False)
        assert rep["model_hash"] and rep["registry_hash"] and rep["vision_mode"]
    clamp = run_gate(
        "no_self_motion", tpl, cfg, registry, dev, trials=2, write=False, protocols=protocols
    )
    assert clamp["passed"]  # AC-07: a clamped readout moves nothing
