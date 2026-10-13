"""Clock, world and body (specs 003 and 009, Phase-2 subset)."""

from __future__ import annotations

import math

import pytest
import torch

from flycolony.body.body import AIRBORNE, GROUNDED, BodyBatch, BodyParams, Commands
from flycolony.engine.clock import Clock, ClockError
from flycolony.world.entities import DEPLETED, STAGES, PatchSpec
from flycolony.world.fields import FieldError, Fields, Grid, SpeciesSpec, Vent, solve_wind
from flycolony.world.geometry import Arena, rotate_frame
from flycolony.world.world import WorldGroup, WorldSpec

CPU = torch.device("cpu")  # device-ok: test


def tunnel() -> Arena:
    return Arena("box", height=30, size_x=160, size_y=50)


def tunnel_vents(speed: float = 300.0) -> list[Vent]:
    return [Vent("wall_x0", (0, 0), (50, 30), speed), Vent("wall_x1", (0, 0), (50, 30), -speed)]


# --- clock (CLOCK-R-001, -003, -004) --------------------------------------------------------------


def test_clock_life_time_and_timestamps(registry):  # T-CLOCK-U-002, -003
    c = Clock.build(0.5, 3600.0, registry)
    assert c.fly_ts == "Day 1, 06:00:00"
    c.advance(2 * 3600 * 1000)  # one neural hour = one fly day at D = 3600
    assert c.sim_ts == pytest.approx(3600.0)
    assert c.fly_ts == "Day 2, 06:00:00"
    life = c.life_s
    c.set_fly_day(7200.0)  # half the compression: continuous, no jump
    assert c.life_s == life
    c.advance(2000)  # 1 neural s → 12 fly s
    assert c.life_s - life == pytest.approx(12.0)
    with pytest.raises(ClockError):
        c.set_fly_day(1.0)


# --- geometry -------------------------------------------------------------------------------------


def test_geometry_faces_normals_and_projection():  # T-WORLD-U-002
    dome = Arena("cylinder", height=300, radius=250)
    assert dome.face_names == ["floor", "ceiling", "wall"]
    p = torch.tensor([[260.0, 0.0, 10.0], [0.0, 0.0, 150.0]], dtype=torch.float64)
    v = dome.violation(p)
    assert v[0, 2] > 0 and (v[1] <= 0).all()
    n = dome.normal(torch.tensor([2, 0]), p)
    assert torch.allclose(n[0], torch.tensor([-1.0, 0, 0], dtype=torch.float64))
    assert torch.allclose(
        dome.project(torch.tensor([2, 0]), p)[0, 0], torch.tensor(250.0, dtype=torch.float64)
    )
    # Rotating the heading from the floor onto a wall turns "forward" upward.
    fwd = torch.tensor([[1.0, 0, 0]], dtype=torch.float64)
    up = torch.tensor([[0.0, 0, 1]], dtype=torch.float64)
    wall_n = torch.tensor([[-1.0, 0, 0]], dtype=torch.float64)
    assert torch.allclose(
        rotate_frame(fwd, up, wall_n), torch.tensor([[0.0, 0, 1]], dtype=torch.float64), atol=1e-12
    )


# --- fields (WORLD-R-033, -040; WORLD-AC-02) -------------------------------------------------------


def test_wind_tunnel_flow_and_vent_balance():  # T-WORLD-U-008
    g = Grid(tunnel(), 2.5, CPU)
    w = solve_wind(g, tunnel_vents(), tol=1e-10, max_iter=2000)
    assert torch.allclose(w.u[1:-1], torch.full_like(w.u[1:-1], 300.0))
    assert float(w.v.abs().max()) == 0 and float(w.w.abs().max()) == 0
    with pytest.raises(FieldError):
        solve_wind(g, tunnel_vents()[:1], tol=1e-10, max_iter=10)


def test_odor_downwind_not_upwind_and_mass_conserved():  # T-WORLD-U-010, WORLD-AC-02
    g = Grid(tunnel(), 2.5, CPU)
    w = solve_wind(g, tunnel_vents(), tol=1e-10, max_iter=2000)
    f = Fields(g, [SpeciesSpec("odor", 10.0)], 1, w)
    i = g.cell_of(torch.tensor([60.0, 25.0, 10.0], dtype=torch.float64))
    f.source[0, 0, i[0], i[1], i[2]] = 1.0
    for _ in range(100):
        f.step(0.01, max_cfl=0.5, max_diff=0.16)
    pts = torch.tensor([[20.0, 25, 10], [100.0, 25, 10]], dtype=torch.float64)
    up, down = f.sample(torch.zeros(2, dtype=torch.long), pts)[:, 0].tolist()
    assert down > 1e3 * max(up, 1e-30)
    # Closed box, no wind: total amount is exactly conserved apart from rounding.
    still = Fields(g, [SpeciesSpec("odor", 10.0)], 1, solve_wind(g, [], tol=1e-9, max_iter=1))
    still.c[0, 0, 10, 10, 5] = 1.0 / g.volume
    for _ in range(50):
        still.step(0.01, max_cfl=0.5, max_diff=0.16)
    assert float(still.total()[0, 0]) == pytest.approx(1.0, rel=1e-12)
    # Decay removes mass at the declared rate.
    dec = Fields(
        g, [SpeciesSpec("odor", 10.0, decay_per_s=1.0)], 1, solve_wind(g, [], tol=1e-9, max_iter=1)
    )
    dec.c[0, 0, 10, 10, 5] = 1.0 / g.volume
    dec.step(0.5, max_cfl=0.5, max_diff=0.16)
    assert float(dec.total()[0, 0]) == pytest.approx(math.exp(-0.5), rel=1e-9)


# --- world group: sky, food, looming, checkpoint ------------------------------------------------------


def _world(registry, n=2, vents=None) -> WorldGroup:
    return WorldGroup(WorldSpec(tunnel(), n_worlds=n, vents=vents or []), registry, CPU)


def test_light_follows_life_clock_and_d(registry):  # T-WORLD-U-006, WORLD-AC-03
    w = _world(registry)
    noon, night = Clock.build(0.5, 3600.0, registry), Clock.build(0.5, 7200.0, registry)
    # Genesis is 06:00 (before lights-on at 08:00): dark.
    assert w.sky.illuminance(noon) == pytest.approx(registry.get("world.light.night_lux"))
    for c in (noon, night):  # 8 fly hours later = 14:00, same light whatever D is
        c.advance(round(c.neural_s_for_fly_s(8 * 3600) * 1000 / c.dt_ms))
        assert c.fly_hour_of_day == pytest.approx(14.0)
        assert w.sky.illuminance(c) == pytest.approx(registry.get("world.light.day_lux"))
    assert noon.sim_ts == pytest.approx(night.sim_ts / 2)  # D doubles the neural time needed
    dirs = torch.tensor([[0.0, 0, 1], [1.0, 0, 0]], dtype=torch.float64)
    rad = w.sky.radiance(dirs, noon)
    assert rad.shape == (2, 3) and (rad > 0).all()
    e, deg = w.sky.polarization(dirs, noon)
    assert (
        (deg >= 0).all()
        and (deg <= 1).all()
        and torch.allclose(e.norm(dim=-1), torch.ones(2, dtype=torch.float64))
    )


def test_looming_angular_size_grows_until_collision(registry):  # T-WORLD-U-009
    w = _world(registry)
    c = Clock.build(0.5, 3600.0, registry)
    w.start_looming(1, c, target=(80.0, 25.0, 1.0), direction=(0.0, 1.0, 1.0))
    t_col = float(w.looming.collision_time()[1])
    sizes = []
    for t in (0.0, t_col * 0.5, t_col * 0.95):
        centre, r, act = w.looming.spheres(t)
        d = float((centre[1] - torch.tensor([80.0, 25.0, 1.0], dtype=torch.float64)).norm())
        sizes.append(2 * math.atan(float(r[1]) / max(d, 1e-9)))
        assert bool(act[1]) and not bool(act[0])
    assert sizes[0] < sizes[1] < sizes[2]
    w.looming.update(t_col + 1e-6)
    assert not bool(w.looming.active[1])


def test_food_stages_emission_and_depletion(registry):  # T-WORLD-U-003, WORLD-AC-04
    w = _world(registry)
    c = Clock.build(0.5, 3600.0, registry)
    w.place_patch(0, 0, PatchSpec("fruit", 80, 25, 5, 1, 50, stage="unripe"), c)
    seen = []
    for _ in range(12):
        w.patches.advance(c.life_s)
        seen.append(STAGES[int(w.patches.stage[0, 0])])
        c.advance(round(c.neural_s_for_fly_s(24 * 3600) * 1000 / c.dt_ms))
    order = [s for i, s in enumerate(seen) if i == 0 or s != seen[i - 1]]
    assert order == ["unripe", "ripe", "fermenting", "rotting", "depleted"]
    # Each stage emits its own profile.
    w2 = _world(registry)
    c2 = Clock.build(0.5, 3600.0, registry)
    c2.advance(round(c2.neural_s_for_fly_s(24 * 3600) * 1000 / c2.dt_ms))  # past the ramp
    w2.patches.place(0, 0, PatchSpec("fruit", 80, 25, 5, 1, 50, stage="fermenting"), 0.0)
    em = w2.patches.emission(c2.life_s)[0, 0]
    assert float(em[w2.odors.index("ethanol")]) > 0
    assert float(em[w2.odors.index("ammonia")]) == 0
    # Ingestion removes exactly what is taken, then the patch is depleted.
    w2.place_patch(1, 0, PatchSpec("sucrose_100mM", 80, 25, 5, 1, 2.0), c2)
    took = w2.patches.ingest(
        torch.tensor([1, 1]), torch.tensor([0, 0]), torch.tensor([1.5, 1.5], dtype=torch.float64)
    )
    assert took.tolist() == [1.5, 0.5] and int(w2.patches.stage[1, 0]) == DEPLETED


def test_world_step_is_deterministic_and_checkpoints(registry):  # T-WORLD-I-001, -002
    def run(restore_at=None):
        w = _world(registry, vents=tunnel_vents())
        c = Clock.build(0.5, 3600.0, registry)
        w.place_patch(0, 0, PatchSpec("vinegar_source", 20, 25, 5, 1, 50), c)
        w.place_patch(1, 0, PatchSpec("water", 40, 25, 5, 1, 50), c)
        saved = None
        for k in range(30):
            if k == restore_at:
                saved = (w.state_dict(), c.state_dict())
            w.step(c, 10.0)
            c.advance(20)
        return w, saved

    a, saved = run(restore_at=15)
    b, _ = run()
    assert torch.equal(a.fields.c, b.fields.c)
    w = _world(registry, vents=tunnel_vents())
    w.load_state_dict(saved[0])
    c = Clock.build(0.5, 3600.0, registry)
    c.load_state_dict(saved[1])
    for _ in range(15):
        w.step(c, 10.0)
        c.advance(20)
    assert torch.equal(w.fields.c, a.fields.c)
    hum = w.fields.index("humidity")
    assert float(w.fields.c[1, hum].max()) > registry.get("world.air.humidity")  # spring humidifies


# --- body (BODY-R-001..004, -008; WORLD-AC-01, -07) ---------------------------------------------------


def _bodies(registry, arena=None) -> BodyBatch:
    return BodyBatch(
        arena or Arena("cylinder", height=300, radius=250), BodyParams.from_registry(registry), CPU
    )


def test_walking_crosses_the_dome_in_25_s(registry):  # WORLD-AC-01, T-BODY-U-002
    b = _bodies(registry)
    b.add("f", 0, (-249.0, 0.0), 0.0)
    cmd = Commands.zeros(1, CPU)
    cmd.speed[:] = 20.0
    for _ in range(int(24.8 / 0.01)):
        b.step(cmd, 0.01)
    assert int(b.face[0]) == 0 and float(b.pos[0, 0]) == pytest.approx(247.0, abs=0.1)
    for _ in range(100):  # reaches the wall and walks up it
        b.step(cmd, 0.01)
    assert int(b.face[0]) == 2 and float(b.pos[0, 2]) > 0.5
    assert torch.allclose(b.up[0], torch.tensor([-1.0, 0, 0], dtype=torch.float64), atol=1e-6)


def test_no_motion_without_commands(registry):  # T-BODY-I-001, WORLD-AC-07
    b = _bodies(registry)
    b.add("a", 0, (0.0, 0.0), 0.3)
    b.add("b", 0, (50.0, 10.0), 1.0)
    before = b.pos.clone(), b.fwd.clone()
    cmd = Commands.zeros(2, CPU)
    for _ in range(2000):
        b.step(cmd, 0.0005)
    assert torch.equal(b.pos, before[0]) and torch.equal(b.fwd, before[1])


def test_escape_jump_flies_and_lands(registry):  # T-BODY-U-003
    b = _bodies(registry, Arena("box", height=40, size_x=60, size_y=60))
    b.add("f", 0, (30.0, 30.0), 0.0)
    cmd = Commands.zeros(1, CPU)
    cmd.jump[:] = True
    b.step(cmd, 0.0005)
    assert int(b.mode[0]) == AIRBORNE
    cmd.jump[:] = False
    peak = 0.0
    for _ in range(4000):
        b.step(cmd, 0.0005)
        peak = max(peak, float(b.pos[0, 2]))
        if int(b.mode[0]) == GROUNDED:
            break
    assert int(b.mode[0]) == GROUNDED and peak > 2.0
    assert float(b.injury[0]) == 0.0


def test_labellum_touches_a_drop_when_standing_at_it(registry):  # T-BODY-U-004
    w = _world(registry, n=1)
    c = Clock.build(0.5, 3600.0, registry)
    w.place_patch(0, 0, PatchSpec("sucrose_100mM", 80.0, 25.0, 1.5, 0.4, 5.0), c)
    b = _bodies(registry, tunnel())
    b.add("f", 0, (80.0 - registry.get("body.size.head_offset_mm"), 25.0), 0.0)
    s = b.sites()
    assert int(w.patches.contains(b.world, s["labellum"])[0]) == 0
    assert int(w.patches.contains(b.world, s["antenna_l"])[0]) == -1
