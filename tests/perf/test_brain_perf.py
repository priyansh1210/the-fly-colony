"""T-BRAIN-P-001 (capacity profile mechanics) and T-BRAIN-P-002 (event-driven cost)."""

from __future__ import annotations

import numpy as np
import pytest
import torch

import flycolony.brain.engine as engine_mod
from flycolony.brain.engine import FlyBrainSpec
from flycolony.hardware.capacity import limits
from tests.brain_fixtures import batch, params, tiny_template

pytestmark = pytest.mark.perf


def test_propagation_cost_scales_with_spikes_not_synapses(tmp_path, registry, monkeypatch):
    rng = np.random.default_rng(1)
    n = 200
    edges = {(int(i), int(j)): 1.0 for i, j in rng.integers(0, n, (20_000, 2)) if i != j}
    tpl = tiny_template(tmp_path, [(i, j, w) for (i, j), w in edges.items()], n, sensory=(0, 1))
    deg = np.diff(tpl.edges["indptr"])
    processed = []
    real = engine_mod.expand_rows

    def counting(indptr, rows):
        e, w = real(indptr, rows)
        processed.append((int(e.numel()), int(deg[rows.cpu().numpy()].sum())))
        return e, w

    monkeypatch.setattr(engine_mod, "expand_rows", counting)
    b = batch(tpl, params(registry))
    b.add(FlyBrainSpec("a", 1))
    b.run(500)  # no input: silent brain
    assert processed == []  # nothing propagated although the brain has ~20k synapses
    b.set_drive("a", [0, 1], 100.0)
    b.run(2000)
    assert processed and all(got == expected for got, expected in processed)


def test_capacity_limits_math(registry):
    prof = {
        "dt_ms": 0.5,
        "fit": {
            "step_fixed_s": 1e-4,
            "step_per_fly_s": 2e-5,
            "mem_fixed_bytes": 2e9,
            "mem_per_fly_bytes": 1e8,
        },
    }
    lim = limits(prof, registry, vram_total_bytes=8 * 2**30)
    budget = 8 * 2**30 * (1 - registry.get("hw.vram_reserve_frac"))
    assert lim["hard_limit"] == int((budget - 2e9) // 1e8)
    # 0.5 ms per step at RTF 1: (5e-4 - 1e-4) / 2e-5 = 20 flies
    assert lim["soft_limit"] == 20 and lim["soft_limit"] <= lim["hard_limit"]
    slow = dict(prof, fit=dict(prof["fit"], step_fixed_s=1e-3))
    lim = limits(slow, registry, vram_total_bytes=8 * 2**30)
    assert lim["soft_limit"] == 0 and "stretched" in lim["note"]


@pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA device")
def test_benchmark_profile_on_tiny_template(tmp_path, registry):
    from flycolony.brain.build import BrainSetup
    from flycolony.brain.gate import DtChoice
    from flycolony.brain.schedule import Schedule
    from flycolony.brain.topology import build_topology
    from flycolony.hardware.capacity import benchmark_template

    tpl = tiny_template(tmp_path, [(0, 1, 5.0), (1, 2, 5.0)], 3)
    p = params(registry, noise_rate=100.0, noise_w=1.5)
    dev = torch.device("cuda", 0)  # device-ok: test
    setup = BrainSetup(
        template=tpl,
        topo=build_topology(tpl, dev, w_per_synapse=p.w_syn, graded=False),
        params=p,
        choice=DtChoice(0.1, "experimental", False, "test"),
        schedule=Schedule.build(0.1, {"brain": 0.1}),
        modulated=False,
    )
    prof = benchmark_template(setup, registry, batch_sizes=[1, 2, 4])
    assert [r["flies"] for r in prof["rows"]] == [1, 2, 4]
    assert prof["fit"]["step_fixed_s"] > 0 and prof["fit"]["mem_per_fly_bytes"] >= 0


def test_fit_ignores_rows_that_oversubscribed_vram(registry):  # HW-R-011
    from types import SimpleNamespace

    from flycolony.hardware.capacity import _fit

    setup = SimpleNamespace(
        template=SimpleNamespace(template_id="t"),
        dt=0.5,
        choice=SimpleNamespace(note=""),
        topo=SimpleNamespace(graded_edges=None, nbytes=lambda: 0),
    )
    rows = [
        {"flies": f, "ms_per_step": 2.0 + 1.0 * f, "peak_bytes": 100 * f, "over_budget": False}
        for f in (1, 2, 4)
    ]
    # Paged to system RAM: wildly slow, must not bend the fit (it gave a negative fixed cost).
    rows.append({"flies": 64, "ms_per_step": 600.0, "peak_bytes": 6400, "over_budget": True})
    fit = _fit(rows, setup)["fit"]
    assert fit["step_fixed_s"] == pytest.approx(2e-3) and fit["step_per_fly_s"] == pytest.approx(
        1e-3
    )
    lim = limits({"fit": fit, "dt_ms": 0.5}, registry, None)
    assert lim["soft_limit"] == 0  # 3 ms for one fly > 0.5 ms of neural time
