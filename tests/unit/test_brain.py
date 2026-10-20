"""Brain engine unit tests (spec 002 §6) on tiny hand-built templates, CPU."""

from __future__ import annotations

import math

import numpy as np
import pytest
import torch

from flycolony.brain.engine import BrainInputError, FlyBrainSpec, PlasticSet
from flycolony.brain.gate import GateError, model_hash, resolve_dt, variant, write_record
from flycolony.brain.modulation import (
    Modulation,
    ReceptorTable,
    RouteCatalog,
    RouteError,
)
from flycolony.brain.params import membrane_propagator
from flycolony.brain.schedule import Schedule, ScheduleError
from flycolony.brain.taps import ObservationTaps
from flycolony.config.schemas import BrainConfig
from tests.brain_fixtures import batch, params, state_hash, tiny_template


def fire(b, fly, neurons):
    """Push neurons over threshold so they spike on the next step (test-only stimulation)."""
    s = b.slot(fly)
    b.u[s, list(neurons)] = 1e3


# --- T-BRAIN-U-004: LIF and synapse integration ---------------------------------------------


def test_membrane_matches_analytic_solution(tmp_path, registry):
    p = params(registry)
    tpl = tiny_template(tmp_path, [], 1)
    b = batch(tpl, p)
    b.add(FlyBrainSpec("a", 1))
    g0 = 5.0
    b.g[0, 0] = g0
    a = g0 * p.tau_syn / (p.tau_syn - p.tau_m)
    for k in range(1, 400):
        b.step()
        t = k * b.dt
        expected = a * (math.exp(-t / p.tau_syn) - math.exp(-t / p.tau_m))
        assert float(b.u[0, 0]) == pytest.approx(expected, abs=1e-5)
        assert float(b.g[0, 0]) == pytest.approx(g0 * math.exp(-t / p.tau_syn), rel=1e-5)


def test_propagator_equal_time_constants():
    e_m, c, e_s = membrane_propagator(10.0, 10.0, 0.1)
    assert e_m == e_s and c == pytest.approx(0.1 / 10.0 * e_m)


def test_delay_sign_and_weight(tmp_path, registry):
    p = params(registry)
    tpl = tiny_template(tmp_path, [(0, 1, 10.0), (0, 2, -4.0)], 3)
    b = batch(tpl, p)
    b.add(FlyBrainSpec("a", 1))
    d = b.k.delay_steps
    assert d == 18  # 1.8 ms at 0.1 ms
    fire(b, "a", [0])
    for _ in range(d):
        b.step()
        assert float(b.g[0, 1]) == 0.0
    b.step()  # delivered in the synapses slot of step `d`
    assert float(b.g[0, 1]) == pytest.approx(10 * p.w_syn, rel=1e-6)
    assert float(b.g[0, 2]) == pytest.approx(-4 * p.w_syn, rel=1e-6)


def test_refractory_blocks_input_and_spikes(tmp_path, registry):
    """Brian2 semantics: during refractoriness the neuron neither spikes nor takes input."""
    p = params(registry)
    tpl = tiny_template(tmp_path, [(0, 1, 1000.0)], 2, sensory=(0,))
    b = batch(tpl, p)
    b.add(FlyBrainSpec("a", 1))
    b.set_drive("a", [0], 9999.0)  # p ~ 1 per step
    spikes1 = []
    b.taps.append(lambda bb, t, s: spikes1.extend((s[s == 1]).tolist() and [t]))
    for _ in range(600):
        b.step()
        last = int(b.last[0, 1])
        since = b.step_count - 1 - last
        if 0 <= since < b.k.ref_steps:
            assert float(b.g[0, 1]) == 0.0  # input ignored while refractory
    isi = np.diff(spikes1)
    assert len(spikes1) > 5 and isi.min() > b.k.ref_steps


# --- T-BRAIN-U-002 / -003: shared topology, gains, plastic overrides ------------------------


def test_gain_vectors_match_explicit_weights(tmp_path, registry):
    p = params(registry)
    edges = [(0, 2, 3.0), (0, 3, -2.0), (1, 2, 5.0), (1, 3, 1.0)]
    tpl = tiny_template(tmp_path, edges, 4)
    b = batch(tpl, p)
    gains = {
        "a": (np.array([1.0, 0.5, 1, 1]), np.array([1, 1, 2.0, 0.25])),
        "b": (np.array([0.8, 1.3, 1, 1]), np.array([1, 1, 0.5, 1.5])),
    }
    for fid, (pre, post) in gains.items():
        b.add(FlyBrainSpec(fid, 3, pre_gain=pre, post_gain=post))
        fire(b, fid, [0, 1])
    b.run(b.k.delay_steps + 1)
    w = np.zeros((4, 4))
    for i, j, x in edges:
        w[i, j] = x * p.w_syn
    for fid, (pre, post) in gains.items():
        expected = (pre[:2] @ w[:2]) * post  # w_f(i->j) = p_f(i) W(i->j) q_f(j)
        got = b.g[b.slot(fid)].double().numpy()
        np.testing.assert_allclose(got[2:], expected[2:], rtol=1e-5)  # fp32


def test_plastic_block_overrides_shared_weight(tmp_path, registry):
    p = params(registry)
    tpl = tiny_template(tmp_path, [(0, 2, 3.0), (1, 2, 5.0)], 3)
    ps = PlasticSet("test", torch.tensor([0]))  # edge 0 is 0->2
    b = batch(tpl, p, plastic_sets=[ps])
    for fid in ("a", "b"):
        b.add(FlyBrainSpec(fid, 1))
        fire(b, fid, [0, 1])
    assert b.plastic.shape == (2, 1) and float(b.plastic[0, 0]) == pytest.approx(3 * p.w_syn)
    b.plastic[b.slot("a"), 0] = 0.0  # fly a has depressed this synapse
    b.run(b.k.delay_steps + 1)
    assert float(b.g[b.slot("a"), 2]) == pytest.approx(5 * p.w_syn, rel=1e-6)
    assert float(b.g[b.slot("b"), 2]) == pytest.approx(8 * p.w_syn, rel=1e-6)


# --- T-BRAIN-U-001: a brain is template + spec only ----------------------------------------


def test_brain_is_determined_by_template_and_spec(tmp_path, registry):
    p = params(registry)
    tpl = tiny_template(tmp_path, [(0, 1, 2.0)], 3)
    rng = np.random.default_rng(0)
    spec = FlyBrainSpec("a", 42, pre_gain=rng.random(3), v_thresh_offset=rng.normal(size=3))
    b1, b2 = batch(tpl, p), batch(tpl, p)
    b1.add(spec)
    b2.add(FlyBrainSpec(**vars(spec)))
    assert state_hash(b1) == state_hash(b2)
    theta = b1.theta[0].double().numpy()
    np.testing.assert_allclose(theta, p.v_thresh + spec.v_thresh_offset - p.v_rest, rtol=1e-6)


# --- T-BRAIN-U-005: Poisson input ---------------------------------------------------------


def test_background_noise_rate_and_independence(tmp_path, registry):
    p = params(registry, noise_rate=200.0, noise_w=0.0)
    tpl = tiny_template(tmp_path, [], 50)
    b = batch(tpl, p)
    for i in range(4):
        b.add(FlyBrainSpec(f"f{i}", 100 + i))
    steps = 20_000
    counts = torch.zeros(4 * 50, dtype=torch.int64)
    trains = torch.zeros(4, steps, dtype=torch.int64)
    for t in range(steps):
        ev = b._noise_at(t)
        counts.index_add_(0, ev, torch.ones_like(ev))
        trains[:, t] = torch.bincount(ev // 50, minlength=4)
        b.step_count = t + 1
    rate = counts.double().mean() / (steps * b.dt / 1000)
    assert float(rate) == pytest.approx(200.0, rel=0.03)
    c = np.corrcoef(trains.numpy())
    assert np.abs(c[np.triu_indices(4, 1)]).max() < 0.05


def test_drive_rate_and_sensory_only(tmp_path, registry):
    p = params(registry)
    tpl = tiny_template(tmp_path, [], 3, sensory=(0,))
    b = batch(tpl, p)
    b.add(FlyBrainSpec("a", 1))
    with pytest.raises(BrainInputError):
        b.set_drive("a", [1], 50.0)  # BRAIN-R-016: only sensory neurons take external input
    b.set_drive("a", [0], 50.0)
    n = [0]
    b.taps.append(lambda bb, t, s: n.__setitem__(0, n[0] + int((s == 0).sum())))
    b.run(100_000)  # 10 s
    assert n[0] / 10.0 == pytest.approx(50.0, rel=0.06)


def test_event_blocks_do_not_change_results(tmp_path, registry):
    """Counter-based draws: any block size gives the same events (BRAIN-R-054)."""
    hashes = []
    for block in (1000, 7, 1):
        p = params(registry, noise_rate=300.0, noise_w=3.0, event_block_steps=block)
        tpl = tiny_template(tmp_path, [(0, 1, 30.0), (1, 2, 30.0), (2, 0, 30.0)], 3, sensory=(0,))
        b = batch(tpl, p)
        b.add(FlyBrainSpec("a", 5))
        b.set_drive("a", [0], 40.0)
        b.run(3000)
        hashes.append(state_hash(b))
    assert hashes[0] == hashes[1] == hashes[2]


# --- T-BRAIN-U-006: graded units ----------------------------------------------------------


def test_graded_coupling_and_dynamics(tmp_path, registry):
    p = params(registry)
    tpl = tiny_template(tmp_path, [(0, 1, 10.0), (2, 3, 4.0)], 4, graded=(0, 3))
    b = batch(tpl, p, graded=True)
    b.add(FlyBrainSpec("a", 1))
    assert math.isinf(float(b.theta[0, 0])) and math.isinf(float(b.theta[0, 3]))
    # Graded 0 at 2 mV above its threshold: output = gain x 2 mV (rate-equivalent Hz).
    b.u[0, 0] = p.graded_v_thresh + 2.0 - p.v_rest
    b._update_graded()
    rate = p.graded_gain * 2.0
    expected = 10 * p.w_syn * rate * b.dt / 1000.0
    assert float(b.graded_in[0, 1]) == pytest.approx(expected, rel=1e-5)
    # Spiking 2 -> graded 3 is a synaptically filtered spike train with the graded time constant.
    fire(b, "a", [2])
    b.run(b.k.delay_steps + 1)
    g0 = float(b.g[0, 3])
    assert g0 == pytest.approx(4 * p.w_syn, rel=1e-6)
    u0 = float(b.u[0, 3])
    b.run(10)
    a = g0 * p.tau_syn / (p.tau_syn - p.graded_tau)
    t = 10 * b.dt
    expected_u = u0 * math.exp(-t / p.graded_tau) + a * (
        math.exp(-t / p.tau_syn) - math.exp(-t / p.graded_tau)
    )
    assert float(b.u[0, 3]) == pytest.approx(expected_u, rel=1e-4)
    b.u[0, 3] = 1e4  # never spikes
    b.step()
    assert int(b.last[0, 3]) < 0


def test_graded_update_is_independent_of_chunking(tmp_path, registry, monkeypatch):
    """Fly chunks of the graded update give bit-identical coupling (fixed-point integer sums)."""
    from flycolony.brain import engine

    p = params(registry)
    edges = [(0, 1, 10.0), (0, 2, -3.0), (3, 1, 7.0), (3, 2, 2.0), (2, 1, 5.0)]
    tpl = tiny_template(tmp_path, edges, 4, graded=(0, 3))
    b = batch(tpl, p, graded=True)
    for i in range(5):
        b.add(FlyBrainSpec(f"f{i}", i + 1))
    b.u[:, 0] = torch.linspace(1.0, 9.0, 5) + p.graded_v_thresh - p.v_rest
    b.u[:, 3] = torch.linspace(4.0, 0.5, 5) + p.graded_v_thresh - p.v_rest
    held = []
    for chunk in (1 << 30, 1):  # all flies at once; one fly per chunk
        monkeypatch.setattr(engine, "GRADED_CHUNK_BYTES", chunk)
        b._update_graded()
        held.append(b.graded_in.clone())
    assert torch.equal(held[0], held[1]) and bool((held[0] != 0).any())


# --- T-BRAIN-U-007: output rates ----------------------------------------------------------


def test_group_rates_filter_and_grouping(tmp_path, registry):
    p = params(registry)
    tpl = tiny_template(tmp_path, [], 4, sensory=(0, 1))
    b = batch(tpl, p, output_groups={"g01": np.array([0, 1]), "g2": np.array([2])})
    b.add(FlyBrainSpec("a", 1))
    b.set_drive("a", [0, 1], [80.0, 40.0])
    b.run(20_000)
    r = b.group_rates("a")
    assert r["g01"] == pytest.approx(60.0, rel=0.2)
    assert r["g2"] == 0.0
    with pytest.raises(ValueError):
        batch(tpl, p, output_groups={"x": np.array([0]), "y": np.array([0])})


# --- T-BRAIN-U-008: timestep gate ---------------------------------------------------------


def test_production_refuses_ungated_dt(tmp_path, registry):
    tpl = tmp_path / "t-t1"
    tpl.mkdir()
    with pytest.raises(GateError):
        resolve_dt(BrainConfig(mode="production", dt_ms=0.5), tpl, registry)
    c = resolve_dt(BrainConfig(mode="experimental", dt_ms=0.5), tpl, registry)
    assert c.mode == "experimental" and not c.gated and "EXPERIMENTAL" in c.note
    assert resolve_dt(BrainConfig(mode="reference"), tpl, registry).dt == 0.1
    write_record(
        tpl,
        "timestep-" + variant(0.5, "fp32", True),
        {
            "dt_ms": 0.5,
            "weights": "fp32",
            "graded": True,
            "passed": True,
            "model_hash": model_hash(registry),
        },
    )
    c = resolve_dt(BrainConfig(mode="production"), tpl, registry)  # dt null -> largest gated
    assert c.dt == 0.5 and c.gated
    write_record(
        tpl,
        "timestep-" + variant(0.25, "fp32", True),
        {"dt_ms": 0.25, "weights": "fp32", "graded": True, "passed": True, "model_hash": "stale"},
    )
    with pytest.raises(GateError):  # a parameter change invalidates the gate
        resolve_dt(BrainConfig(mode="production", dt_ms=0.25), tpl, registry)


# --- T-BRAIN-U-009: schedule --------------------------------------------------------------


def test_schedule_is_exact_over_long_runs():
    s = Schedule.build(0.25, {"brain": 0.25, "physics": 0.5, "senses": 1.0, "vision": 10.0})
    assert s.every == {"brain": 1, "physics": 2, "senses": 4, "vision": 40}
    steps = 1_000_000
    counts = dict.fromkeys(s.every, 0)
    for k in range(0, steps, 2):  # every physics step; others are multiples of it
        for name in s.due(k):
            counts[name] += 1
    assert counts["vision"] == steps // 40 and counts["senses"] == steps // 4
    with pytest.raises(ScheduleError):
        Schedule.build(0.2, {"physics": 0.5})


# --- T-BRAIN-U-010 / -011: traces, receptors and routes -----------------------------------


def _mod_template(tmp_path):
    return tiny_template(
        tmp_path,
        [],
        4,
        cell_types=["DAN", "KC", "IPC", "OAN"],
        neuropils=["MB_CA_L", "MB_CA_L", "SMP_L", "SMP_L"],
        neurosecretory=(2,),
        modulatory=[(0, "dopamine"), (2, "ILP")],
    )


def _tables(sens=0.5):
    receptors = ReceptorTable.model_validate(
        {
            "version": 1,
            "entries": [
                {
                    "name": "da_kc",
                    "select": {"cell_types": ["KC"]},
                    "substance": "dopamine",
                    "effect": "gain",
                    "sensitivity": sens,
                    "source": {"authors": "t", "year": 2000},
                }
            ],
        }
    )
    routes = RouteCatalog.model_validate(
        {
            "version": 1,
            "routes": [
                {
                    "id": "akh",
                    "source": "physiology.akh",
                    "target": {"trace": "AKH"},
                    "transfer": {"kind": "linear", "gain": 2.0},
                    "citation": "t",
                },
                {
                    "id": "oa_exc",
                    "source": "physiology.x",
                    "target": {"select": {"cell_types": ["OAN"]}, "effect": "excitability"},
                    "transfer": {"kind": "linear", "gain": 1.0},
                    "citation": "t",
                },
            ],
        }
    )
    return receptors, routes


def test_trace_kinetics_follow_dual_exponential(tmp_path, registry):
    p = params(registry)
    tpl = _mod_template(tmp_path)
    b = batch(tpl, p)
    receptors, routes = _tables()
    m = Modulation(tpl, receptors, routes).attach(b)
    b.add(FlyBrainSpec("a", 1))
    fire(b, "a", [0])
    b.step()  # DAN spikes at step 0 -> release counted at the next trace update
    slot = m._slot("dopamine", "MB_CA_L")
    every = m.every
    b.run(every)  # first update after the spike
    c0 = 1.0 / (p.trace_unit_rate * p.amine_tau_decay / 1000.0)  # one spike, sole releaser
    e_d = math.exp(-every * b.dt / p.amine_tau_decay)
    e_r = math.exp(-every * b.dt / p.amine_tau_rise)
    for k in range(1, 50):
        b.run(every)
        expected = c0 * (e_d**k - e_r**k)
        assert float(m.concentration()[0, slot]) == pytest.approx(expected, rel=1e-4, abs=1e-9)
    # Neurosecretory release goes to the global compartment.
    fire(b, "a", [2])
    b.run(2 * every)
    assert float(m.x_decay[0, m._slot("ILP", "global")]) > 0


def test_receptor_gain_is_bounded_and_routes_are_catalogued(tmp_path, registry):
    p = params(registry)
    tpl = _mod_template(tmp_path)
    b = batch(tpl, p)
    receptors, routes = _tables(sens=10.0)
    m = Modulation(tpl, receptors, routes).attach(b)
    b.add(FlyBrainSpec("a", 1))
    m.x_decay[0, m._slot("dopamine", "MB_CA_L")] = 1.0  # strong dopamine at the KC
    b.run(m.every)
    assert float(m.gain[0, 1]) == pytest.approx(1 + p.max_gain_change)  # clamped
    assert float(m.gain[0, 0]) == 1.0  # DAN itself has no receptor entry
    theta0 = float(b.theta[0, 3])
    m.apply_route("a", "oa_exc", 1.5)
    m.apply_route("a", "akh", 0.25)
    b.run(m.every)
    assert float(b.theta[0, 3]) == pytest.approx(theta0 - 1.5)
    assert m.trace_summary("a")["AKH"] == pytest.approx(0.5)
    with pytest.raises(RouteError):
        m.apply_route("a", "not_a_route", 1.0)  # BRAIN-R-034


# --- T-BRAIN-U-016: R-STDP off by default --------------------------------------------------


def test_rstdp_set_is_off_by_default():
    import yaml

    from flycolony.config import project_root

    sets = yaml.safe_load(
        (project_root() / "config/brain/plastic_sets.yaml").read_text(encoding="utf-8")
    )["sets"]
    by = {s["name"]: s for s in sets}
    assert by["rstdp_lh_smp"]["enabled"] is False
    assert by["mb_kc_mbon"]["enabled"] and by["cx_ring_epg"]["enabled"]


# --- T-BRAIN-U-017: taps -----------------------------------------------------------------


def test_taps_contents_and_focus_raster(tmp_path, registry):
    p = params(registry)
    iomap = [{"name": "sense.x", "kind": "sense", "neuron_ids": [0]}]
    tpl = tiny_template(
        tmp_path, [(0, 1, 100.0)], 3, sensory=(0,), neuropils=["AL_L", "AL_L", "LH_L"], iomap=iomap
    )
    b = batch(tpl, p)
    b.add(FlyBrainSpec("a", 1))
    b.add(FlyBrainSpec("b", 2))
    b.set_drive("a", [0], 100.0)
    taps = ObservationTaps(b, tpl, pathways={"p01": np.array([0, 1])}, focus={"a"})
    manual = torch.zeros(2, 3, dtype=torch.int64)
    b.taps.append(lambda bb, t, s: manual.view(-1).index_add_(0, s, torch.ones_like(s)))
    b.run(10_000)
    snap = taps.snapshot()
    w = snap["a"]["window_s"]
    assert snap["a"]["neuropil_hz"]["AL_L"] == pytest.approx(float(manual[0, :2].sum()) / 2 / w)
    assert snap["a"]["sense_hz"]["sense.x"] == pytest.approx(float(manual[0, 0]) / w)
    assert snap["b"]["neuropil_hz"]["AL_L"] == 0.0
    raster = snap["a"]["raster"]
    assert sum(len(x[1]) for x in raster) == int(manual[0].sum())
    assert "raster" not in snap["b"]
    assert snap["a"]["sleep_state"] is None


def test_graded_time_constants_per_type(tmp_path, registry):  # BRAIN-R-014 (flyvis taus)
    from flycolony.brain.engine import BrainBatch
    from flycolony.brain.topology import build_topology

    p = params(registry)
    tpl = tiny_template(tmp_path, [], 3, graded=(0, 1), cell_types=["C2", "Zz", "C2"])
    topo = build_topology(
        tpl, torch.device("cpu"), w_per_synapse=p.w_syn, graded=True, graded_tau_ms={"C2": 100.0}
    )  # device-ok: test
    b = BrainBatch(topo, p, 0.1)
    assert float(b.e_m[0]) == pytest.approx(math.exp(-0.1 / 100.0), rel=1e-6)  # flyvis type
    assert float(b.e_m[1]) == pytest.approx(
        math.exp(-0.1 / p.graded_tau), rel=1e-6
    )  # registry default
    assert float(b.e_m[2]) == pytest.approx(math.exp(-0.1 / p.tau_m), rel=1e-6)  # spiking C2


def test_agreement_excludes_driven_neurons():  # BRAIN-R-081 metric
    from flycolony.brain.assays import agreement

    rng = np.random.default_rng(0)
    ref = np.concatenate([150 + rng.normal(0, 2, 60), np.linspace(100, 2, 40), np.zeros(100)])
    test = np.concatenate(
        [150 + rng.normal(0, 2, 60), np.linspace(100, 2, 40) * 1.01, np.zeros(100)]
    )
    loose = agreement(ref, test, responsive_hz=1.0, top_k=50)
    strict = agreement(ref, test, responsive_hz=1.0, top_k=30, exclude=np.arange(60))
    assert loose.top_k_overlap < 0.9  # near-ties among driven neurons are Poisson noise
    assert strict.top_k_overlap == 1.0 and strict.n_responsive == 40


def test_per_type_male_weight_normalization(tmp_path, registry):  # CONN-R-031
    from dataclasses import replace

    import polars as pl

    from flycolony.brain.build import weight_scale
    from flycolony.brain.topology import build_topology
    from flycolony.registry import Registry

    def mode(m: str) -> Registry:
        return Registry(
            [
                e.model_copy(update={"value": m}) if e.id == "conn.norm.male_mode" else e
                for e in registry.entries()
            ]
        )

    g = float(registry.get("conn.norm.male_scale"))
    clip = float(registry.get("conn.norm.male_type_clip"))
    tpl = tiny_template(
        tmp_path, [(0, 1, 2.0), (0, 2, 3.0), (1, 2, -1.0)], 4, cell_types=["A", "B", "C", "D"]
    )
    male = replace(tpl, manifest={"template_id": "tiny-t1", "sex": "male"})
    match = tmp_path / "match__fem-t1__tiny-t1"
    match.mkdir()
    pl.DataFrame(
        {
            "male_type": ["B", "C", "C", "D"],
            "matched": [True, True, True, False],
            "in_ratio": [0.5, 0.2, 0.4, 0.9],
        }
    ).write_parquet(match / "type_stats.parquet")
    reg = mode("per_type")
    s = weight_scale(male, reg)
    # A unmatched -> global; B its ratio; C the median of its matches; D not matched -> global.
    expect = [g, 0.5, max(0.3, g / clip), g]
    assert s == pytest.approx(expect)
    topo = build_topology(
        male, torch.device("cpu"), w_per_synapse=1.0, graded=False, weight_scale=s
    )  # device-ok: test
    # Edges scale by the factor of their postsynaptic neuron.
    assert topo.weight.tolist() == pytest.approx([2.0 * s[1], 3.0 * s[2], -1.0 * s[2]])
    assert weight_scale(tpl, reg) == 1.0  # female untouched
    assert weight_scale(male, mode("global")) == g


def test_batch_with_modulation_is_freed_without_gc(tmp_path, registry):
    """No batch <-> modulation reference cycle: a finished batch's tensors go when it does."""
    import gc
    import weakref

    tpl = _mod_template(tmp_path)
    receptors, routes = _tables()
    b = batch(tpl, params(registry))
    m = Modulation(tpl, receptors, routes).attach(b)
    b.add(FlyBrainSpec("a", 1))
    b.step()
    ref = weakref.ref(b)
    gc.disable()
    try:
        del b
        assert ref() is None and m.batch is None
    finally:
        gc.enable()


def test_sensory_layout_drives_rates_independently_of_batch(tmp_path, registry):  # 004 §2
    from flycolony.brain.engine import BrainInputError

    tpl = tiny_template(tmp_path, [(0, 2, 5.0), (1, 2, 5.0)], 4, sensory=(0, 1, 3))
    p = params(registry)

    def run(flies):
        b = batch(tpl, p)
        b.attach_senses(np.array([0, 1]), np.array([3]))
        for f in flies:
            b.add(FlyBrainSpec(f, 7 if f == "a" else 9))
        counts = torch.zeros(len(flies), 4)

        def tap(bb, t, spikes):
            counts.view(-1).index_add_(0, spikes.cpu(), torch.ones(spikes.numel()))

        b.taps.append(tap)
        rates = torch.zeros(len(flies), 2)
        rates[:, 0] = 200.0  # neuron 0 driven, neuron 1 silent
        b.set_senses(rates)
        b.run(4000)
        return b, counts

    b1, c1 = run(["a"])
    _b2, c2 = run(["a", "b"])
    assert c1[0, 0] > 0 and c1[0, 1] == 0
    assert torch.equal(c1[0], c2[0])  # fly a's input events do not depend on fly b
    with pytest.raises(BrainInputError):
        b1.attach_senses(np.array([2]), np.array([]))  # neuron 2 is not sensory
    with pytest.raises(BrainInputError):
        b1.set_senses(torch.zeros(1, 3))


def test_photoreceptor_input_depolarises_and_checkpoints(tmp_path, registry):  # 004 §2
    tpl = tiny_template(tmp_path, [], 2, sensory=(0, 1), graded=(0,))
    p = params(registry)
    b = batch(tpl, p)
    b.attach_senses(np.array([1]), np.array([0]))
    b.add(FlyBrainSpec("a", 1))
    b.set_senses(torch.zeros(1, 1), torch.full((1, 1), 4.0))
    b.run(4000)
    assert float(b.potential("a")[0]) == pytest.approx(p.v_rest + 4.0, abs=0.05)
    tensors, meta = b.state_dict()
    c = batch(tpl, p)
    c.load_state_dict(tensors, meta)
    b.run(50)
    c.run(50)
    assert torch.equal(b.u, c.u) and torch.equal(c.photo_in, b.photo_in)
