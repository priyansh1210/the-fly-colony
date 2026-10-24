"""Phase-2 emergence gates: protocols, batched trials, statistics, reports (005 M9).

MOTOR-R-020: every trial starts from world stimuli only — arena, food and odor sources, wind,
light, the fly's starting pose and its physiological history (integrated by the physiology model
over the stated period). Seeds differ per trial; each trial is a separate individual. Nothing
here stimulates a DN or changes a parameter per trial; the only exception is AC-07, whose stated
test condition is the readout clamped to zero.

MOTOR-R-021: every run is written in full (every seed, trial and outcome) with the template,
registry, model and config versions to specs/005-motor/reports/<template>.<gate>.json.

Protocols live in config/motor/gates.yaml. Trials run as batched worlds, one fly per world, in
chunks of `max_batch`.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import yaml

from flycolony.body.body import GROUNDED
from flycolony.brain.gate import model_hash
from flycolony.config import content_hash, load_all, project_root
from flycolony.config.schemas import ColonyConfig, config_snapshot
from flycolony.connectome.template import BrainTemplate
from flycolony.engine.clock import MS_PER_S, SECONDS_PER_HOUR
from flycolony.engine.loop import ClosedLoop, FlyStart
from flycolony.engine.stats import fisher_one_sided, mannwhitney_one_sided
from flycolony.motor.readout import MotorBatch
from flycolony.registry import Registry
from flycolony.world.entities import PatchSpec
from flycolony.world.fields import Vent
from flycolony.world.geometry import Arena
from flycolony.world.world import WorldGroup, WorldSpec

ARMS = ("condition", "control")
HOURS_PER_DAY = 24.0
TRACK_EVERY_MS = 10.0  # position tracking period for the reach outcome (well below 1 mm of travel)


def gates_path() -> Path:
    return project_root() / "config" / "motor" / "gates.yaml"


def load_gates(path: Path | None = None) -> dict:
    return yaml.safe_load((path or gates_path()).read_text(encoding="utf-8"))


def report_path(template_id: str, gate: str) -> Path:
    return project_root() / "specs" / "005-motor" / "reports" / f"{template_id}.{gate}.json"


class ClampedMotor(MotorBatch):
    """AC-07 test condition: every DN output reads as zero (rates and trigger spikes)."""

    def tap(self, batch, _t: int, spikes: torch.Tensor) -> None:
        return

    def read(self, rates: torch.Tensor):
        return super().read(torch.zeros_like(rates))


@dataclass
class Trial:
    arm: str
    seed: int
    heading: float


# --- protocol pieces ---------------------------------------------------------------------------


def _arena(spec: dict) -> Arena:
    return Arena(spec["kind"], height=spec["height"], size_x=spec["size_x"], size_y=spec["size_y"])


def _vents(g: dict, arena: Arena) -> list[Vent]:
    speed = g.get("wind_mm_s")
    if not speed:
        return []
    (_, _), (y0, y1), (z0, z1) = arena.bounds
    return [
        Vent("wall_x0", (y0, z0), (y1, z1), speed),
        Vent("wall_x1", (y0, z0), (y1, z1), -speed),
    ]


def _trials(g: dict, index: int, base: dict, arms: tuple[str, ...], n: int) -> list[Trial]:
    out = []
    for a, arm in enumerate(arms):
        for i in range(n):
            seed = base["seed_base"] + 1000 * index + 500 * a + i  # registry-ok: seed layout
            heading = 0.0
            if g.get("start", {}).get("heading_deg") == "random":
                heading = float(np.random.default_rng(seed).uniform(0, 2 * math.pi))
            out.append(Trial(arm, seed, heading))
    return out


class _Outcome:
    """Collects one gate's outcome measure per fly during a batch, on the device."""

    def __init__(self, kind: str, g: dict, loop: ClosedLoop, reg: Registry):
        self.kind, self.loop = kind, loop
        n, dev = loop.n, loop.device
        f64 = torch.float64
        if kind == "feeding":
            self.max_ext = torch.zeros(n, dtype=f64, device=dev)
        elif kind == "reach":
            src = g["condition"]["source"]
            self.target = torch.tensor([src["x"], src["y"]], dtype=f64, device=dev)
            self.min_dist = torch.full((n,), math.inf, dtype=f64, device=dev)
            self.every = max(1, round(TRACK_EVERY_MS / loop.dt_ms))
        elif kind == "sleep_minutes":
            self.bout_s = float(reg.get("life.sleep.bout_fly_min")) * 60.0  # registry-ok: min→s
            self.run = torch.zeros(n, dtype=f64, device=dev)
            self.slept = torch.zeros(n, dtype=f64, device=dev)
        elif kind == "at_rest":
            self.pos0 = loop.bodies.pos.clone()
            self.active = torch.zeros(n, dtype=torch.bool, device=dev)
            self.moved = torch.zeros(n, dtype=f64, device=dev)

    def observe(self, lp: ClosedLoop) -> None:
        b = lp.bodies
        if self.kind == "feeding":
            self.max_ext = torch.maximum(self.max_ext, b.proboscis)
        elif self.kind == "reach":
            if lp.clock.tick % self.every == 0:
                d = (b.sites()["head"][:, :2] - self.target).norm(dim=-1)
                self.min_dist = torch.minimum(self.min_dist, d)
        elif self.kind == "sleep_minutes":
            dt_fly = lp.schedule.every["physics"] * lp.dt_ms / MS_PER_S * lp.clock.compression
            quiet = (
                (b.mode == GROUNDED)
                & (b.speed.abs() < lp.move_threshold)
                & (b.yaw_rate.abs() < lp.move_threshold)
            )
            ended = ~quiet & (self.run >= self.bout_s)
            self.slept = self.slept + torch.where(ended, self.run, torch.zeros_like(self.run))
            self.run = torch.where(quiet, self.run + dt_fly, torch.zeros_like(self.run))
        elif self.kind == "at_rest":
            m = lp.last_motor
            c = m.commands
            any_cmd = (
                (c.speed != 0) | (c.yaw != 0) | c.jump | c.landing | (c.proboscis != 0)
                | (m.pump != 0) | (m.groom != 0)
            )  # fmt: skip
            self.active = self.active | any_cmd
            self.moved = torch.maximum(self.moved, (b.pos - self.pos0).norm(dim=-1))

    def results(self, reg: Registry) -> list[dict]:
        lp = self.loop
        if self.kind == "feeding":
            thr = float(reg.get("gate.feed.min_extension"))
            ing = lp.physio.ingested_mm3.cpu().tolist()
            ext = self.max_ext.cpu().tolist()
            return [
                {"success": e > thr and v > 0, "max_extension": e, "ingested_mm3": v}
                for e, v in zip(ext, ing, strict=True)
            ]
        if self.kind == "reach":
            return [{"min_distance_mm": d} for d in self.min_dist.cpu().tolist()]
        if self.kind == "sleep_minutes":
            total = self.slept + torch.where(
                self.run >= self.bout_s, self.run, torch.zeros_like(self.run)
            )
            return [{"value": s / 60.0} for s in total.cpu().tolist()]  # registry-ok: s→min
        moved = self.moved.cpu().tolist()
        return [
            {"success": (not a) and m == 0, "any_primitive": a, "max_displacement_mm": m}
            for a, m in zip(self.active.cpu().tolist(), moved, strict=True)
        ]


def _run_batch(
    g: dict,
    base: dict,
    arm: str,
    trials: list[Trial],
    template: BrainTemplate,
    cfg: ColonyConfig,
    reg: Registry,
    device: torch.device,
) -> tuple[list[dict], dict]:
    spec = g[arm]
    arena = _arena(g["arena"])
    world = WorldGroup(WorldSpec(arena, n_worlds=len(trials), vents=_vents(g, arena)), reg, device)
    motor_cls = ClampedMotor if spec.get("clamp_motor") else MotorBatch
    loop = ClosedLoop(template, world, cfg, reg, device, motor_cls=motor_cls)
    clock = loop.clock
    if "fly_hour" in spec:  # light phase: the life clock starts at that hour of the fly day
        hours = (spec["fly_hour"] - clock.fly_hour_of_day) % HOURS_PER_DAY
        clock.life_s += hours * SECONDS_PER_HOUR
    (x0, x1), (y0, y1), _ = arena.bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    drop = base["drop"]
    head = float(reg.get("body.size.head_offset_mm"))
    for w, tr in enumerate(trials):
        pos = (cx, cy)
        if "medium" in spec:  # PER assay: drop under the labellum of a fly facing +x
            world.place_patch(
                w, 0,
                PatchSpec(spec["medium"], cx, cy, drop["radius_mm"], drop["height_mm"],
                          drop["volume_mm3"]),
                clock,
            )  # fmt: skip
            pos = (cx - head, cy)
        if "source" in spec:
            s = spec["source"]
            world.place_patch(
                w, 0,
                PatchSpec(s["medium"], s["x"], s["y"], drop["radius_mm"], drop["height_mm"],
                          drop["volume_mm3"]),
                clock,
            )  # fmt: skip
        for k, f in enumerate(g.get("food", [])):
            world.place_patch(
                w, 1 + k,
                PatchSpec(f["medium"], f["x"], f["y"], drop["radius_mm"], drop["height_mm"],
                          drop["volume_mm3"]),
                clock,
            )  # fmt: skip
        if "start" in g:
            pos = (g["start"]["x"], g["start"]["y"])
        energy = loop.physio.starved_fraction(spec.get("hours_since_meal", 0))
        pressure = loop.physio.pressure_after_wake(spec.get("hours_awake", 0))
        loop.add(FlyStart(f"{arm}{tr.seed}", tr.seed, w, pos, tr.heading, energy, pressure))
    outcome = _Outcome(g["outcome"], g, loop, reg)
    loop.observers.append(outcome.observe)
    loop.run_for(g["seconds"])
    meta = {"brain_dt_ms": loop.dt_ms, "vision_mode": loop.vision.mode}
    return outcome.results(reg), meta


def _summarize(g: dict, base: dict, records: list[dict]) -> dict:
    alpha = base["alpha"]
    test = g["test"]
    by = {a: [r for r in records if r["arm"] == a] for a in ARMS}
    if g["outcome"] == "reach":
        for r in records:
            r["success"] = r["min_distance_mm"] <= g["reach_mm"]
    out: dict = {"test": test, "alpha": alpha}
    if test == "all":
        ok = [r["success"] for r in by["condition"]]
        out.update(successes=sum(ok), n=len(ok), passed=all(ok))
        return out
    if test.startswith("fisher"):
        k = {a: sum(r["success"] for r in by[a]) for a in ARMS}
        n = {a: len(by[a]) for a in ARMS}
        alt = "greater" if test == "fisher_greater" else "less"
        p = fisher_one_sided(k["condition"], n["condition"], k["control"], n["control"], alt)
        frac = k["condition"] / n["condition"] if n["condition"] else 0.0
        passed = p < alpha and frac >= g.get("min_fraction", 0.0)
        out.update(
            condition={"successes": k["condition"], "n": n["condition"], "fraction": frac},
            control={
                "successes": k["control"],
                "n": n["control"],
                "fraction": k["control"] / n["control"] if n["control"] else 0.0,
            },
            p_value=p,
            min_fraction=g.get("min_fraction"),
            passed=passed,
        )
        return out
    x = [r["value"] for r in by["condition"]]
    y = [r["value"] for r in by["control"]]
    p = mannwhitney_one_sided(x, y, "greater")
    out.update(
        condition={"n": len(x), "mean": float(np.mean(x)), "median": float(np.median(x))},
        control={"n": len(y), "mean": float(np.mean(y)), "median": float(np.median(y))},
        p_value=p,
        passed=p < alpha,
    )
    return out


def run_gate(
    name: str,
    template: BrainTemplate,
    cfg: ColonyConfig,
    reg: Registry,
    device: torch.device,
    *,
    trials: int | None = None,
    write: bool = True,
    progress: Callable[[str], None] | None = None,
    protocols: dict | None = None,
) -> dict:
    """Run one gate in full and return (and by default write) its report. `protocols` replaces
    config/motor/gates.yaml (plumbing tests only; written reports always use the file)."""
    if protocols is not None and write:
        raise ValueError("reports are written only from config/motor/gates.yaml")
    base = protocols or load_gates()
    names = list(base["gates"])
    g = base["gates"][name]
    report: dict = {
        "gate": name,
        "id": g["id"],
        "template": template.template_id,
        "pipeline_version": template.manifest.get("pipeline_version"),
    }
    if g.get("blocked"):
        report.update(status="blocked", reason=g["blocked"], passed=False)
    else:
        n = trials or base["trials"]
        arms = ARMS if g.get("control") is not None else ("condition",)
        todo = _trials(g, names.index(name), base, arms, n)
        records: list[dict] = []
        meta: dict = {}
        t0 = time.perf_counter()
        for arm in arms:
            pending = [t for t in todo if t.arm == arm]
            for lo in range(0, len(pending), base["max_batch"]):
                chunk = pending[lo : lo + base["max_batch"]]
                res, meta = _run_batch(g, base, arm, chunk, template, cfg, reg, device)
                for tr, r in zip(chunk, res, strict=True):
                    records.append({"arm": arm, "seed": tr.seed, "heading": tr.heading, **r})
                if progress:
                    progress(f"{name}: {arm} {lo + len(chunk)}/{len(pending)}")
        summary = _summarize(g, base, records)
        report.update(
            status="run",
            protocol=g,
            trials_per_arm=n,
            summary=summary,
            passed=summary["passed"],
            trials=records,
            wall_s=round(time.perf_counter() - t0, 1),
            **meta,
        )
    report.update(
        registry_hash=reg.content_hash(),
        model_hash=model_hash(reg),
        config_hash=config_snapshot(load_all())[1],
        gates_hash=protocols_hash(),
    )
    if write:
        path = report_path(template.template_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
    return report


def protocols_hash() -> str:
    """Version of config/motor/gates.yaml (stored with every report)."""
    return content_hash(load_gates())
