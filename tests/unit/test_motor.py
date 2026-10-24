"""Motor readout and minimal physiology (T-MOTOR-U-001..003, -005; T-LIFE-U-002, -005)."""

from __future__ import annotations

import numpy as np
import pytest
import torch

from flycolony.engine.clock import Clock
from flycolony.motor.readout import MotorBatch, load_primitives
from flycolony.physiology.minimal import PhysioBatch, PhysioParams

CPU = torch.device("cpu")  # device-ok: test


def _motor(registry):
    table = load_primitives()
    names, members = [], {}
    for p in table["primitives"]:
        for g in p["groups"]:
            for n in [f"{g}.L", f"{g}.R"] if p.get("side") == "LR" else [g]:
                names.append(n)
                members[n] = np.array([len(members)], dtype=np.int64)
    names.append("descending.unmapped")
    members["descending.unmapped"] = np.array([99], dtype=np.int64)
    return MotorBatch(names, members, registry, 0.5, CPU, table), names


def test_transfer_latency_and_superposition(registry):  # T-MOTOR-U-001, -002
    m, names = _motor(registry)
    rates = torch.zeros(1, len(names))
    rates[0, names.index("walk.forward")] = 200.0
    rates[0, names.index("walk.backward")] = 200.0
    lat = round(registry.get("motor.walk_forward.latency_ms") / 0.5)
    outs = [m.read(rates).commands.speed.item() for _ in range(lat + 1)]
    assert all(v == 0 for v in outs[:lat])  # nothing before the latency has elapsed
    fwd = registry.get("motor.walk_forward.max")
    back = registry.get("motor.walk_backward.max")

    def sat(r, k):
        x = (r - registry.get(f"motor.{k}.threshold_hz")) / registry.get(f"motor.{k}.half_hz")
        return x / (1 + x)

    assert outs[-1] == pytest.approx(
        fwd * sat(200, "walk_forward") - back * sat(200, "walk_backward")
    )
    # Steering: left minus right.
    m2, _ = _motor(registry)
    r2 = torch.zeros(1, len(names))
    r2[0, names.index("walk.steer.L")] = 100.0
    for _ in range(50):
        yaw = m2.read(r2).commands.yaw.item()
    assert yaw > 0


def test_unmapped_dns_and_zero_rates_drive_nothing(registry):  # T-MOTOR-U-003, MOTOR-AC-07
    m, names = _motor(registry)
    rates = torch.zeros(2, len(names))
    rates[:, names.index("descending.unmapped")] = 500.0
    for _ in range(100):
        out = m.read(rates)
    c = out.commands
    assert (c.speed == 0).all() and (c.yaw == 0).all() and not c.jump.any()
    assert (c.proboscis == 0).all() and (out.pump == 0).all() and (out.effort == 0).all()


def test_escape_is_triggered_by_one_gf_spike(registry):  # MOTOR-R-002
    m, names = _motor(registry)
    gf = int(m.trigger_ids[0])

    class B:
        n = 100

    m.resize(2)
    m.tap(B, 0, torch.tensor([1 * 100 + gf]))  # fly 1 spikes once
    lat = round(registry.get("motor.escape.latency_ms") / 0.5)
    outs = [m.read(torch.zeros(2, len(names))).commands.jump.tolist() for _ in range(lat + 1)]
    assert outs[lat] == [False, True]


def test_ingestion_energy_and_sleep_pressure(registry):  # T-LIFE-U-002, -005
    p = PhysioParams.from_registry(registry)
    ph = PhysioBatch(p, CPU)
    ph.add(energy_frac=0.5)
    ph.add(energy_frac=0.5)
    c = Clock.build(0.5, 3600.0, registry)
    want = ph.intake(
        c,
        1.0,
        torch.tensor([6.0, 6.0], dtype=torch.float64),
        torch.tensor([1.0, 0.0], dtype=torch.float64),
    )
    assert want[0] > 0 and want[1] == 0
    e0 = ph.energy.clone()
    quiet = torch.tensor([False, False])
    ph.step(
        c,
        1.0,
        torch.zeros(2, dtype=torch.float64),
        quiet,
        want,
        torch.tensor([0.1, 0.1], dtype=torch.float64),
    )
    assert ph.energy[0] > e0[0] and ph.energy[1] < e0[1]
    assert ph.deficit[0] < ph.deficit[1]
    # Pressure rises while awake; after a quiescent bout the fly is asleep and pressure falls.
    p_wake = float(ph.pressure[0])
    assert p_wake > 0
    bout_neural = c.neural_s_for_fly_s(p.bout_fly_s)
    for _ in range(int(bout_neural / 0.5) + 2):
        c.advance(1000)
        ph.step(
            c,
            0.5,
            torch.zeros(2, dtype=torch.float64),
            torch.tensor([True, False]),
            torch.zeros(2, dtype=torch.float64),
            torch.zeros(2, dtype=torch.float64),
        )
    assert bool(ph.asleep[0]) and not bool(ph.asleep[1])
    before = float(ph.pressure[0])
    c.advance(1000)
    ph.step(
        c,
        0.5,
        torch.zeros(2, dtype=torch.float64),
        torch.tensor([True, False]),
        torch.zeros(2, dtype=torch.float64),
        torch.zeros(2, dtype=torch.float64),
    )
    assert float(ph.pressure[0]) < before and float(ph.pressure[1]) > before
    assert ph.starved_fraction(24) < 1 and ph.pressure_after_wake(12) > ph.pressure_after_wake(1)
