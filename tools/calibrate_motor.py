"""Global calibration of the motor transfer thresholds against spontaneous activity (005 M8).

    python tools/calibrate_motor.py [--flies 32] [--warmup 0.5] [--seconds 2.0]

Rule (fixed before looking at data, design 005 §7): resting flies — sated, daylight, empty box,
no food, odor or wind — run in the closed loop. For every rate-driven primitive, the threshold is
the 99th percentile of its groups' filtered rate over flies and physics steps after the warm-up,
rounded up to 0.5 Hz. Spike-triggered primitives (escape) are not rate-calibrated. The same
threshold applies to every fly, trial and gate.

Writes specs/005-motor/reports/<template>.motor-calibration.json; the registry values are then
updated by hand from that report (each entry cites it).
"""

from __future__ import annotations

import argparse
import json
import math

import torch

from flycolony.brain.build import template_path
from flycolony.config import load_all
from flycolony.config.schemas import project_root
from flycolony.connectome.template import load_template
from flycolony.engine.loop import ClosedLoop, FlyStart
from flycolony.registry import Registry
from flycolony.world.geometry import Arena
from flycolony.world.world import WorldGroup, WorldSpec

QUANTILE = 0.99
ROUND_HZ = 0.5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flies", type=int, default=32)
    ap.add_argument("--warmup", type=float, default=0.5)
    ap.add_argument("--seconds", type=float, default=2.0)
    a = ap.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")  # device-ok: tool
    cfg = load_all()["colony.yaml"]
    reg = Registry.load(project_root() / "config" / "params")
    path = template_path(cfg, "female")
    template = load_template(path)
    arena = Arena("box", height=30, size_x=20, size_y=20)
    world = WorldGroup(WorldSpec(arena, n_worlds=a.flies), reg, device)
    loop = ClosedLoop(template, world, cfg, reg, device)
    for i in range(a.flies):
        loop.add(FlyStart(f"r{i}", seed=5000 + i, world=i, xy=(10.0, 10.0), heading=0.0))
    loop.run_for(a.warmup)
    samples: list[torch.Tensor] = []
    moving: list[torch.Tensor] = []
    loop.observers.append(lambda lp: samples.append(lp.brain.rates.clone()))
    loop.observers.append(lambda lp: moving.append(lp.bodies.speed.abs() > 0))
    loop.run_for(a.seconds)
    rates = torch.stack(samples).cpu().double()  # [T, N, G]
    names = loop.brain.group_names
    out = {}
    for p in loop.motor.prims:
        cols = rates[..., p.cols].reshape(-1)
        entry = {
            "groups": [names[c] for c in p.cols],
            "mean_hz": float(cols.mean()),
            "p50_hz": float(cols.quantile(0.5)),
            "p99_hz": float(cols.quantile(QUANTILE)),
            "max_hz": float(cols.max()),
            "current_threshold_hz": p.threshold,
        }
        if p.trigger_spikes:
            entry["calibrated_threshold_hz"] = None
            entry["note"] = "spike-triggered (one GF spike); not rate-calibrated"
        else:
            entry["calibrated_threshold_hz"] = math.ceil(entry["p99_hz"] / ROUND_HZ) * ROUND_HZ
        out[p.name] = entry
    report = {
        "spec": "005 M8 global threshold calibration",
        "template": path.name,
        "rule": f"threshold = q{QUANTILE:.2f} of resting group rate, rounded up to {ROUND_HZ} Hz",
        "condition": {
            "flies": a.flies,
            "seeds": [5000, 5000 + a.flies - 1],
            "arena": "20 x 20 x 30 mm box per fly, no food, odor or wind, daylight, sated",
            "warmup_s": a.warmup,
            "measured_s": a.seconds,
            "brain_dt_ms": loop.dt_ms,
        },
        "fraction_of_steps_moving": float(torch.stack(moving).double().mean()),
        "primitives": out,
    }
    dest = (
        project_root() / "specs" / "005-motor" / "reports" / f"{path.name}.motor-calibration.json"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    for name, e in out.items():
        print(
            f"{name:15s} mean {e['mean_hz']:6.2f}  p99 {e['p99_hz']:6.2f}  max {e['max_hz']:6.2f}"
            f"  -> {e['calibrated_threshold_hz']}  (now {e['current_threshold_hz']})"
        )
    print(f"moving fraction {report['fraction_of_steps_moving']:.3f}; wrote {dest}")


if __name__ == "__main__":
    main()
