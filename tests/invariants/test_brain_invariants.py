"""Brain invariants (spec 002 §6): T-BRAIN-I-001..006."""

from __future__ import annotations

import ast

import numpy as np
import pytest
import torch

from flycolony.brain.engine import FlyBrainSpec, PlasticSet, load_checkpoint, save_checkpoint
from flycolony.brain.modulation import Modulation, load_receptors, load_routes
from flycolony.brain.taps import ObservationTaps
from flycolony.config import project_root
from tests.brain_fixtures import batch, params, state_hash, tiny_template

DEVICES = [torch.device("cpu")]  # device-ok: tests enumerate devices explicitly
if torch.cuda.is_available():
    DEVICES.append(torch.device("cuda", 0))  # device-ok: tests enumerate devices explicitly

N = 60


def _template(tmp_path):
    rng = np.random.default_rng(3)
    edges = {}
    for _ in range(600):
        i, j = (int(x) for x in rng.integers(0, N, 2))
        if i != j:
            edges[(i, j)] = float(rng.integers(-15, 30))
    types = ["KC" if i < 10 else ("MBON01" if i < 14 else f"T{i}") for i in range(N)]
    return tiny_template(
        tmp_path,
        [(i, j, w) for (i, j), w in edges.items()],
        N,
        sensory=tuple(range(50, 60)),
        graded=(20, 21, 22),
        cell_types=types,
        neuropils=["MB_CA_L"] * 20 + ["SMP_L"] * 40,
        modulatory=[(30, "dopamine"), (31, "sNPF")],
    )


def _setup(tpl, registry, device, *, modulated=True, **over):
    p = params(registry, noise_rate=150.0, noise_w=3.0, **over)
    kc_mbon = np.flatnonzero(
        [
            (i < 10 and 10 <= j < 14)
            for i in range(N)
            for j in tpl.edges["indices"][tpl.edges["indptr"][i] : tpl.edges["indptr"][i + 1]]
        ]
    )
    ps = [PlasticSet("mb", torch.from_numpy(kc_mbon).to(device))]
    b = batch(
        tpl, p, device=device, graded=True, plastic_sets=ps, output_groups={"dn": np.arange(40, 45)}
    )
    if modulated:
        Modulation(tpl, load_receptors(), load_routes()).attach(b)
    return b


def _add(b, fid, seed):
    rng = np.random.default_rng(seed)
    b.add(
        FlyBrainSpec(
            fid, seed, pre_gain=1 + 0.1 * rng.normal(size=N), v_thresh_offset=rng.normal(size=N)
        )
    )
    b.set_drive(fid, list(range(50, 60)), 60.0 + seed)


@pytest.mark.parametrize("device", DEVICES, ids=str)
def test_bit_identical_runs(tmp_path, registry, device):  # T-BRAIN-I-001 / BRAIN-AC-03
    tpl = _template(tmp_path)
    hashes = []
    for _ in range(2):
        b = _setup(tpl, registry, device)
        for i in range(3):
            _add(b, f"f{i}", i)
        b.run(3000)
        hashes.append(state_hash(b))
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize("device", DEVICES, ids=str)
def test_adding_or_removing_a_fly_does_not_perturb_others(
    tmp_path, registry, device
):  # T-BRAIN-I-002
    tpl = _template(tmp_path)
    alone = _setup(tpl, registry, device)
    _add(alone, "a", 1)
    alone.run(2500)

    crowd = _setup(tpl, registry, device)
    _add(crowd, "x", 7)
    _add(crowd, "a", 1)
    _add(crowd, "y", 8)
    crowd.run(1000)
    crowd.remove("x")  # a death
    crowd.run(700)
    _add(crowd, "z", 9)  # a birth, mid-block
    crowd.run(800)
    assert state_hash(crowd, ["a"]) == state_hash(alone, ["a"])


@pytest.mark.parametrize("device", DEVICES, ids=str)
def test_taps_do_not_disturb(tmp_path, registry, device):  # T-BRAIN-I-003 / BRAIN-AC-05
    tpl = _template(tmp_path)
    runs = []
    for with_taps in (False, True):
        b = _setup(tpl, registry, device)
        _add(b, "a", 1)
        _add(b, "b", 2)
        if with_taps:
            taps = ObservationTaps(b, tpl, pathways={"p": np.arange(0, 30)}, focus={"a"})
        for _ in range(4):
            b.run(500)
            if with_taps:
                taps.snapshot()
        runs.append(state_hash(b))
    assert runs[0] == runs[1]


@pytest.mark.parametrize("device", DEVICES, ids=str)
def test_checkpoint_round_trip(tmp_path, registry, device):  # T-BRAIN-I-006 / BRAIN-AC-04
    tpl = _template(tmp_path)
    straight = _setup(tpl, registry, device)
    _add(straight, "a", 1)
    _add(straight, "b", 2)
    straight.run(1234)
    path = tmp_path / "brain.safetensors"
    save_checkpoint(straight, path)
    straight.run(1500)

    restored = _setup(tpl, registry, device)
    load_checkpoint(restored, path)
    restored.run(1500)
    assert state_hash(restored) == state_hash(straight)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA device")
def test_checkpoint_is_device_portable(tmp_path, registry):  # HW-R-020
    tpl = _template(tmp_path)
    gpu = _setup(tpl, registry, torch.device("cuda", 0))  # device-ok: test
    _add(gpu, "a", 1)
    gpu.run(800)
    path = tmp_path / "brain.safetensors"
    save_checkpoint(gpu, path)
    cpu = _setup(tpl, registry, torch.device("cpu"))  # device-ok: test
    load_checkpoint(cpu, path)
    assert state_hash(cpu) == state_hash(gpu)
    cpu.run(10)  # and it runs


def test_runaway_detection_does_not_modify_the_brain(tmp_path, registry):  # T-BRAIN-I-005
    tpl = _template(tmp_path)
    out = []
    for limit in (0.001, 1e6):  # every window flags a runaway vs never
        b = _setup(tpl, registry, torch.device("cpu"), max_population_rate=limit)  # device-ok: test
        _add(b, "a", 1)
        events = b.run(3000)
        out.append((state_hash(b), [e.kind for e in events]))
    assert out[0][0] == out[1][0]
    assert out[0][1] and set(out[0][1]) == {"brain.runaway"} and not out[1][1]


STATE_ATTRS = {
    "u", "g", "last", "next_noise", "theta", "vrest", "pre", "post", "ref", "graded_in", "rates",
    "plastic", "keys", "gain", "x_decay", "x_rise", "body", "route_level", "theta_base",
}  # fmt: skip


def test_no_brain_state_writes_outside_the_brain():  # T-BRAIN-I-004 (static part)
    """Only flycolony.brain assigns brain state; everyone else goes through set_drive/apply_route."""
    src = project_root() / "src" / "flycolony"
    problems = []
    for path in sorted(src.rglob("*.py")):
        if path.relative_to(src).parts[0] == "brain":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            targets = []
            if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                while isinstance(t, ast.Subscript):
                    t = t.value
                if isinstance(t, ast.Attribute) and t.attr in STATE_ATTRS:
                    problems.append(f"{path.relative_to(src)}:{node.lineno} writes .{t.attr}")
    assert not problems, problems
