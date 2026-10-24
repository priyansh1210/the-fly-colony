"""The open-loop stimulation harness (005 §5): its input and its isolation (T-MOTOR-I-002)."""

from __future__ import annotations

import math
import tomllib

import pytest
from tools import lint

from flycolony.brain.engine import FlyBrainSpec
from flycolony.config import project_root
from tests.brain_fixtures import batch, params, tiny_template
from tests.harness.stimulation import StimulatedBrain, stimulable


def test_stimulation_holds_the_steady_depolarisation(tmp_path, registry):
    p = params(registry)
    tpl = tiny_template(tmp_path, [], 3, sensory=(2,), graded=(0,))
    b = stimulable(batch(tpl, p, graded=True))
    assert isinstance(b, StimulatedBrain)
    b.add(FlyBrainSpec("a", 1))
    b.add(FlyBrainSpec("b", 2))
    b.stimulate("a", [0], 3.0)  # graded unit: never spikes, settles at +3 mV
    b.run(4000)
    assert float(b.u[0, 0]) == pytest.approx(3.0, rel=1e-3)
    assert float(b.u[1, 0]) == pytest.approx(0.0, abs=1e-6)  # the other fly is untouched
    b.stimulate("a", [], 0.0)
    b.run(4000)
    assert abs(float(b.u[0, 0])) < 1e-3


def test_stimulation_above_threshold_fires_spiking_neurons(tmp_path, registry):
    p = params(registry)
    tpl = tiny_template(tmp_path, [], 3, sensory=(2,))
    b = stimulable(batch(tpl, p))
    b.add(FlyBrainSpec("a", 1))
    theta = float(b.threshold_mv("a", [1])[0])
    assert math.isfinite(theta)
    b.stimulate("a", [1], 2 * theta)
    spikes = []
    b.taps.append(lambda batch, t, s: spikes.append(int(s.numel())))
    b.run(round(200 / b.dt))  # 200 ms
    assert sum(spikes) >= 5
    with pytest.raises(ValueError, match="non-sensory"):
        b.stimulate("a", [2], 10.0)


def test_harness_is_absent_from_production():  # T-MOTOR-I-002, MOTOR-R-012
    cfg = tomllib.loads((project_root() / "pyproject.toml").read_text(encoding="utf-8"))
    # The wheel ships only the production package...
    assert cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/flycolony"]
    # ...and an import contract forbids production code from importing the tests package.
    contracts = cfg["tool"]["importlinter"]["contracts"]
    assert any(
        c["source_modules"] == ["flycolony"] and "tests" in c["forbidden_modules"]
        for c in contracts
    )
    assert lint.import_contracts() == []
    assert not any((project_root() / "src").rglob("stimulation.py"))
