"""Open-loop DN → primitive mapping on the real template (T-MOTOR-V-001, MOTOR-AC-06).

Each mapped group in turn is held depolarised by the test-only harness, with the whole closed
loop running, at three stimulus levels (like light intensities in an optogenetic experiment), 20
flies per level with different seeds. A trial is positive when the expected primitive is active
in most physics steps of the second half of the stimulation window. Pass: ≥ 90% of trials per
group at the saturating level PASS_LEVEL (fixed in advance); the lower levels are reported as a
dose series. The run writes specs/005-motor/reports/<template>.openloop.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
import torch

from flycolony.body.body import AIRBORNE
from flycolony.brain.build import template_path
from flycolony.config import load_all, project_root
from flycolony.connectome.template import load_template
from flycolony.engine.loop import ClosedLoop, FlyStart
from flycolony.registry import Registry
from flycolony.world.geometry import Arena
from flycolony.world.world import WorldGroup, WorldSpec
from tests.harness.stimulation import stimulable

pytestmark = [pytest.mark.data, pytest.mark.gpu]

TRIALS = 20
STIM_S = 0.3  # stimulation window (s neural); the second half is scored
LEVELS = (2.0, 4.0, 8.0)  # steady depolarisation as a multiple of each neuron's threshold
PASS_LEVEL = 8.0  # saturating level the pass criterion uses
PASS_FRAC = 0.9  # MOTOR-AC-06
START_HEIGHT_MM = 35.0  # airborne start for the landing check


@dataclass
class Check:
    label: str
    group: str
    primitive: str
    airborne: bool = False


CHECKS = [
    Check("MDN -> backward walking", "walk.backward", "walk_backward"),
    Check("GF -> takeoff", "escape.takeoff", "escape"),
    Check("BDN2 -> forward walking", "walk.forward", "walk_forward"),
    Check("DNa02 L -> left turn", "walk.steer.L", "steer_left"),
    Check("MN9 -> proboscis extension", "feeding.proboscis_extension", "proboscis"),
    Check("pharyngeal MNs -> pumping", "feeding.ingestion", "ingestion"),
    Check("aDN -> antennal grooming", "groom.antenna", "groom_antenna"),
    Check("landing DNs (airborne) -> extension", "flight.landing", "landing", airborne=True),
]


def _active(out, primitive: str) -> torch.Tensor:
    """Per fly: is the expected primitive's command active this physics step?"""
    c = out.commands
    return {
        "walk_backward": c.speed < 0,
        "walk_forward": c.speed > 0,
        "steer_left": c.yaw > 0,  # left turn > 0
        "escape": c.jump,
        "proboscis": c.proboscis > 0,
        "ingestion": out.pump > 0,
        "groom_antenna": out.groom > 0,
        "landing": c.landing,
    }[primitive]


def _run_check(check: Check, template, cfg, reg, device) -> dict:
    arena = Arena("box", height=40, size_x=20, size_y=20)
    n = TRIALS * len(LEVELS)
    world = WorldGroup(WorldSpec(arena, n_worlds=n), reg, device)
    loop = ClosedLoop(template, world, cfg, reg, device)
    level = torch.tensor([lv for lv in LEVELS for _ in range(TRIALS)])
    for i in range(n):
        loop.add(FlyStart(f"t{i}", seed=1000 + i, world=i, xy=(10.0, 10.0), heading=0.0))
    if check.airborne:
        b = loop.bodies
        b.mode = torch.full_like(b.mode, AIRBORNE)
        b.pos = b.pos + b.up * START_HEIGHT_MM
    brain = stimulable(loop.brain)
    ids = loop.setup.output_groups[check.group]
    for i, fid in enumerate(brain.fly_ids):
        brain.stimulate(fid, ids, float(level[i]) * brain.threshold_mv(fid, ids))
    steps = round(STIM_S * 1000 / loop.dt_ms)
    half = steps // 2
    active, airborne = [], []

    def observe(lp: ClosedLoop) -> None:
        if lp.clock.tick >= half:
            active.append(_active(lp.last_motor, check.primitive))
            airborne.append(lp.bodies.mode == AIRBORNE)

    loop.observers.append(observe)
    loop.run(steps)
    frac = torch.stack(active).double().mean(0).cpu()  # fraction of scored steps active
    positive = frac > 0.5
    if check.primitive == "escape":  # one GF spike → ballistic jump: score the takeoff itself
        positive = (torch.stack(active).any(0) & torch.stack(airborne).any(0)).cpu()
    rates = loop.brain.rates[:, loop.brain.group_names.index(check.group)].cpu()
    by_level = {}
    for lv in LEVELS:
        m = level == lv
        by_level[str(lv)] = {
            "positive": int(positive[m].sum()),
            "fraction": float(positive[m].double().mean()),
            "per_trial_active_fraction": [round(float(x), 3) for x in frac[m]],
            "group_rate_hz_at_end": [round(float(x), 1) for x in rates[m]],
        }
    at_pass = by_level[str(PASS_LEVEL)]
    return {
        "check": check.label,
        "group": check.group,
        "n_neurons": len(ids),
        "primitive": check.primitive,
        "trials_per_level": TRIALS,
        "positive": at_pass["positive"],
        "fraction": at_pass["fraction"],
        "pass": at_pass["fraction"] >= PASS_FRAC,
        "levels": by_level,
    }


def test_open_loop_dn_mapping():
    if not torch.cuda.is_available():
        pytest.skip("needs a CUDA device")
    cfg = load_all()["colony.yaml"]
    path = template_path(cfg, "female")
    if not (path / "manifest.json").exists():
        pytest.skip("female template not built")
    reg = Registry.load(project_root() / "config" / "params")
    template = load_template(path)
    device = torch.device("cuda")  # device-ok: gpu-marked validation test
    results = [_run_check(c, template, cfg, reg, device) for c in CHECKS]
    report = {
        "spec": "005 MOTOR-AC-06 / T-MOTOR-V-001",
        "template": path.name,
        "stimulation": {
            "window_s": STIM_S,
            "levels_x_threshold": list(LEVELS),
            "pass_level": PASS_LEVEL,
            "scored": "second half of the window",
        },
        "pass_fraction": PASS_FRAC,
        "results": results,
    }
    out = project_root() / "specs" / "005-motor" / "reports" / f"{path.name}.openloop.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    failed = [f"{r['check']}: {r['positive']}/{TRIALS}" for r in results if not r["pass"]]
    assert not failed, f"open-loop mapping below {PASS_FRAC:.0%}: {failed}"
