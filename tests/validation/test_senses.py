"""Sense channels on the real template layout (T-SENSE-V-001, -002, -006, -007, -008)."""

from __future__ import annotations

import pytest
import torch

from flycolony.body.body import BodyBatch, BodyParams
from flycolony.brain.build import template_path
from flycolony.config import load_all
from flycolony.connectome.template import load_template
from flycolony.engine.clock import Clock
from flycolony.senses.layout import build_layout
from flycolony.senses.senses import SenseBatch
from flycolony.world.entities import PatchSpec
from flycolony.world.fields import Vent
from flycolony.world.geometry import Arena
from flycolony.world.world import WorldGroup, WorldSpec

pytestmark = pytest.mark.data
CPU = torch.device("cpu")  # device-ok: test


@pytest.fixture(scope="module")
def layout():
    path = template_path(load_all()["colony.yaml"], "female")
    if not (path / "manifest.json").exists():
        pytest.skip("female template not built")
    return build_layout(load_template(path))


def _setup(registry, layout, n=1, vents=None, media=None, heading=0.0):
    arena = Arena("box", height=30, size_x=160, size_y=50)
    w = WorldGroup(WorldSpec(arena, n_worlds=n, vents=vents or []), registry, CPU)
    c = Clock.build(0.5, 3600.0, registry)
    b = BodyBatch(arena, BodyParams.from_registry(registry), CPU)
    head = registry.get("body.size.head_offset_mm")
    for i in range(n):
        if media and media[i]:
            w.place_patch(i, 0, PatchSpec(media[i], 80.0, 25.0, 2.0, 0.4, 5.0), c)
        b.add(f"f{i}", i, (80.0 - head, 25.0), heading)
    return w, c, b, SenseBatch(layout, registry, CPU)


def _mean(rates, layout, channel, side=None):
    ch = layout.channels[channel]
    r = rates[:, ch.start : ch.stop]
    if side is None:
        return r.mean(1)
    m = torch.from_numpy(ch.side == side)
    return r[:, m].mean(1)


def test_taste_channels_are_specific(registry, layout):  # T-SENSE-V-001, SENSE-AC-01
    w, c, b, s = _setup(registry, layout, n=3, media=["sucrose_100mM", "sucrose_bitter", None])
    w.step(c, 10.0)
    r = s.step(w, b, 0.001)
    sugar, bitter = _mean(r, layout, "sugar"), _mean(r, layout, "bitter")
    spont_sugar = registry.get("senses.taste.sugar.spont_hz")
    assert sugar[0] > 5 * spont_sugar and bitter[0] == registry.get("senses.taste.bitter.spont_hz")
    assert bitter[1] > 5 * registry.get("senses.taste.bitter.spont_hz")
    assert sugar[2] == spont_sugar and bitter[2] == registry.get("senses.taste.bitter.spont_hz")
    # Water cells respond to liquid contact, less with solutes.
    water = _mean(r, layout, "water")
    assert water[0] > water[2]
    # Sugar/low-salt GRNs (Gr64f-like) answer sucrose as well as low salt.
    mixed = _mean(r, layout, "sugar_low_salt")
    spont_mixed = registry.get("senses.taste.low_salt.spont_hz")
    assert mixed[0] > 5 * spont_mixed and mixed[2] == spont_mixed


def test_hunger_raises_sugar_response(registry, layout):  # T-SENSE-V-008, SENSE-AC-08
    w, _c, b, s = _setup(registry, layout, n=2, media=["sucrose_100mM", "sucrose_100mM"])
    deficit = torch.tensor([0.0, 0.8])
    r = s.step(w, b, 0.001, intero={"physiology.energy_deficit": deficit})
    sugar, bitter = _mean(r, layout, "sugar"), _mean(r, layout, "bitter")
    assert sugar[1] > sugar[0] * 1.2
    assert bitter[1] <= bitter[0]


def test_odor_on_the_left_drives_left_orns_more(registry, layout):  # T-SENSE-V-002, SENSE-AC-02
    w, _c, b, s = _setup(registry, layout, n=1)
    # A small cloud of ethyl acetate to the fly's left (+y when heading along +x).
    sites = b.sites()
    p = sites["antenna_l"][0] + torch.tensor([0.0, 3.0, 0.0], dtype=torch.float64)
    i = w.grid.cell_of(p)
    w.fields.c[0, w.odors.index("ethyl_acetate"), i[0], i[1], i[2]] = 1e-3
    for _ in range(3):
        w.fields.step(0.01, max_cfl=0.5, max_diff=0.16)
    r = s.step(w, b, 0.001)
    dm1 = layout.channels["orn.dm1"]  # Or42b: strong ethyl acetate response (DoOR)
    left = r[0, dm1.start : dm1.stop][torch.from_numpy(dm1.side == 0)].mean()
    right = r[0, dm1.start : dm1.stop][torch.from_numpy(dm1.side == 1)].mean()
    assert left > right


def test_wind_from_one_side_is_asymmetric_in_jo(registry, layout):  # T-SENSE-V-006, SENSE-AC-06
    vents = [Vent("wall_y0", (0, 0), (160, 30), 200.0), Vent("wall_y1", (0, 0), (160, 30), -200.0)]
    w, _c, b, s = _setup(registry, layout, n=1, vents=vents)  # wind blowing toward +y (fly's left)
    r = s.step(w, b, 0.001)
    jo = layout.channels["jo_ce"]
    seg = r[0, jo.start : jo.stop]
    pol = s.jo_polarity
    l_c = seg[(torch.from_numpy(jo.side == 0)) & (pol > 0)].mean()
    r_c = seg[(torch.from_numpy(jo.side == 1)) & (pol > 0)].mean()
    assert abs(float(l_c - r_c)) > 1.0


def test_temperature_step_signs(registry, layout):  # T-SENSE-V-007, SENSE-AC-07
    w, _c, b, s = _setup(registry, layout, n=2)
    s.step(w, b, 0.01)
    t = w.fields.index("temperature")
    w.fields.c[0, t] += 1.0  # warming in world 0
    w.fields.c[1, t] -= 1.0  # cooling in world 1
    r = s.step(w, b, 0.01)
    hot, cold = _mean(r, layout, "hot"), _mean(r, layout, "cold")
    assert hot[0] > hot[1] and cold[1] > cold[0]


def _vision_setup(registry, layout):
    from flycolony.senses.vision import Vision

    arena = Arena("box", height=40, size_x=60, size_y=60)
    w = WorldGroup(WorldSpec(arena, n_worlds=1), registry, CPU)
    b = BodyBatch(arena, BodyParams.from_registry(registry), CPU)
    b.add("f", 0, (30.0, 30.0), 0.0)
    return w, b, Vision(layout, registry, CPU)


def _noon(registry):
    c = Clock.build(0.5, 3600.0, registry)
    c.advance(round(c.neural_s_for_fly_s(6 * 3600) * 1000 / c.dt_ms))  # 06:00 → 12:00
    return c


def test_vision_scene_day_night_and_preview(registry, layout):  # T-SENSE-U-002, -003
    w, b, v = _vision_setup(registry, layout)
    day = _noon(registry)
    rad = v.render(w, b, day)
    el = v.eyes.elevation
    assert rad[0, 0][el[0] > 0.3].mean() > rad[0, 0][el[0] < -0.3].mean()  # sky above floor
    mv_day = v.photoreceptors(w, b, day, 0.01)
    assert mv_day.shape == (1, layout.n_photo) and float(mv_day.mean()) > 10
    night = Clock.build(0.5, 3600.0, registry)  # 06:00, before lights-on
    v2 = _vision_setup(registry, layout)[2]
    assert abs(float(v2.photoreceptors(w, b, night, 0.01).mean())) < 1.0
    prev = v.preview(0)
    assert torch.equal(prev["radiance"], v.last_frame[0])


def test_looming_darkens_the_ipsilateral_eye(registry, layout):  # T-SENSE-U-002 (looming)
    w, b, v = _vision_setup(registry, layout)
    c = _noon(registry)
    w.start_looming(0, c, target=b.sites()["head"][0].tolist(), direction=(0.0, 1.0, 0.2))
    t_col = float(w.looming.collision_time()[0])
    left, right = [], []
    for frac in (0.0, 0.6, 0.9, 0.99):
        ck = _noon(registry)
        ck.advance(round((t_col - c.sim_ts) * frac * 1000 / ck.dt_ms))
        r = v.render(w, b, ck)
        left.append(float(r[0, 0].mean()))
        right.append(float(r[0, 1].mean()))
    assert left[0] > left[1] > left[2] > left[3]  # the left eye darkens as the disk expands
    assert left[3] < 0.8 * right[3]
