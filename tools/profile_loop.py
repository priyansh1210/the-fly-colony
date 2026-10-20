"""Wall time per stage of the closed loop on the real female template (005 M6 performance).

    python tools/profile_loop.py --flies 2 --seconds 0.2 [--cprofile]

Prints wall seconds per neural second for each loop stage (CUDA-synchronised around each stage,
so stage times add up but the total is a little slower than an unsynchronised run).
"""

from __future__ import annotations

import argparse
import cProfile
import pstats
import time
from collections import defaultdict

import torch

from flycolony.brain.build import template_path
from flycolony.config import load_all
from flycolony.config.schemas import ColonyConfig, project_root
from flycolony.connectome.template import load_template
from flycolony.engine.clock import MS_PER_S
from flycolony.engine.loop import ClosedLoop, FlyStart
from flycolony.registry import Registry
from flycolony.world.entities import PatchSpec
from flycolony.world.geometry import Arena
from flycolony.world.world import WorldGroup, WorldSpec


def build(n: int, device: torch.device) -> ClosedLoop:
    cfgs = load_all()
    cfg: ColonyConfig = cfgs["colony.yaml"]
    reg = Registry.load(project_root() / "config" / "params")
    template = load_template(template_path(cfg, "female"))
    arena = Arena("box", height=30, size_x=160, size_y=50)
    world = WorldGroup(WorldSpec(arena, n_worlds=n), reg, device)
    loop = ClosedLoop(template, world, cfg, reg, device)
    for i in range(n):
        world.place_patch(i, 0, PatchSpec("sucrose_100mM", 80.0, 25.0, 2.0, 0.4, 5.0), loop.clock)
        loop.add(FlyStart(f"f{i}", seed=i, world=i, xy=(60.0, 25.0), heading=0.0))
    return loop


def timed_step(loop: ClosedLoop, acc: dict[str, float], sync) -> None:
    """ClosedLoop.step with a timer around each stage (kept in step with engine/loop.py)."""
    due = set(loop.schedule.due(loop.clock.tick))
    ms = lambda k: loop.schedule.every[k] * loop.dt_ms  # noqa: E731

    def stage(name, fn):
        sync()
        t = time.perf_counter()
        fn()
        sync()
        acc[name] += time.perf_counter() - t

    if "fields" in due:
        stage("fields", lambda: loop.world.step(loop.clock, ms("fields")))
    if "vision" in due:

        def vis():
            loop._photo = loop.vision.photoreceptors(
                loop.world, loop.bodies, loop.clock, ms("vision") / MS_PER_S
            )

        stage("vision", vis)
    if "senses" in due:

        def sen():
            intero = {"physiology.energy_deficit": loop.physio.deficit}
            rates = loop.senses.step(loop.world, loop.bodies, ms("senses") / MS_PER_S, intero)
            loop.brain.set_senses(rates, loop._photo)

        stage("senses", sen)
    stage("brain", loop.brain.step)
    if "physics" in due:
        stage("physics", lambda: loop._physics(ms("physics") / MS_PER_S))
    if "physio" in due:
        stage("physio", loop._routes)
    loop.clock.advance(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flies", type=int, default=2)
    ap.add_argument("--seconds", type=float, default=0.2)
    ap.add_argument("--warmup", type=float, default=0.02)
    ap.add_argument("--cprofile", action="store_true")
    ap.add_argument("--plain", action="store_true", help="time loop.run without per-stage syncs")
    a = ap.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")  # device-ok: tool
    sync = torch.cuda.synchronize if device.type == "cuda" else (lambda: None)
    loop = build(a.flies, device)
    loop.run_for(a.warmup)
    sync()
    steps = round(a.seconds * MS_PER_S / loop.dt_ms)
    acc: dict[str, float] = defaultdict(float)
    prof = cProfile.Profile() if a.cprofile else None
    t0 = time.perf_counter()
    if prof:
        prof.enable()
    if a.plain:
        loop.run(steps)
    else:
        for _ in range(steps):
            timed_step(loop, acc, sync)
    sync()
    if prof:
        prof.disable()
    total = time.perf_counter() - t0
    print(f"{a.flies} flies, dt {loop.dt_ms} ms, {steps} steps, {a.seconds} neural s")
    for k, v in sorted(acc.items(), key=lambda kv: -kv[1]):
        print(f"  {k:8s} {v / a.seconds:8.2f} s/neural-s  ({100 * v / total:5.1f}%)")
    print(f"  {'total':8s} {total / a.seconds:8.2f} s/neural-s")
    if prof:
        pstats.Stats(prof).sort_stats("cumulative").print_stats(40)


if __name__ == "__main__":
    main()
