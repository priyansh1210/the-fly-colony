"""Phase-1 gate checks on the real FAFB/MaleCNS templates (T-BRAIN-V-001..004).

V-001 and V-004 recompute (GPU, a few minutes). V-002 and V-003 check that the stored gate and
male-assay records exist, passed, and still match the current brain parameters, so changing a
parameter without re-running `colony brain gate` / `colony brain male` fails the suite.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from flycolony.brain.assays import agreement, load_assays, run_assay
from flycolony.brain.build import template_path, topology
from flycolony.brain.gate import model_hash, passed_dts, read_record, resolve_dt
from flycolony.brain.params import NeuronParams
from flycolony.brain.validation import reference_rates, validate_reference
from flycolony.config import load_all
from flycolony.connectome.template import load_template

pytestmark = pytest.mark.data
CFG = load_all()["colony.yaml"]
gpu = pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA device")


def _female():
    path = template_path(CFG, "female")
    if not (path / "manifest.json").exists():
        pytest.skip("female template not built")
    return load_template(path)


@gpu
def test_engine_matches_brian2_reference(registry):  # T-BRAIN-V-001 / BRAIN-AC-01
    tpl = _female()
    if reference_rates(tpl, "sugar") is None:
        pytest.skip("Brian2 reference not run (tools/reference_brian2.py)")
    rec = validate_reference(
        tpl, torch.device("cuda", 0), registry, load_assays()
    )  # device-ok: test
    for name, a in rec["assays"].items():
        assert a["pass"], (name, a)
        assert a["agreement"]["pearson"] >= 0.9
    sugar = rec["assays"]["sugar"]
    assert sugar["readout_engine_hz"]["mn9"] > 10  # sugar -> MN9 reproduced


def test_production_dt_passed_the_gate(registry):  # T-BRAIN-V-002 / BRAIN-AC-02
    tpl = _female()
    bc = CFG.brain
    dts = passed_dts(tpl.path, bc.weights, bc.graded, model_hash(registry))
    assert dts, "no timestep passed the gate for the current parameters; run `colony brain gate`"
    choice = resolve_dt(bc, tpl.path, registry)
    assert choice.gated and choice.dt == max(dts) and choice.dt >= 0.25


def test_male_assays_and_cross_sex_comparability(registry):  # T-BRAIN-V-003
    male = load_template(template_path(CFG, "male"))
    rec = read_record(male.path, "male-assays")
    assert rec is not None, "run `colony brain male`"
    assert rec["model_hash"] == model_hash(registry), (
        "brain parameters changed; re-run `colony brain male`"
    )
    assert rec["passed"], rec["assays"]
    min_corr = float(registry.get("brain.male.min_type_side_corr"))
    for a in rec["assays"].values():
        assert a["type_side_pearson"] >= min_corr
    # MaleCNS MN9 R is truncated (~10% of its homolog's inputs): the MN9 assays run mirror-image.
    assert rec["assays"]["sugar"]["mirrored"]


@gpu
def test_cpu_and_gpu_paths_agree(registry):  # T-BRAIN-V-004 / BRAIN-AC-06
    tpl = _female()
    p = NeuronParams.from_registry(registry, reference=True)
    assay = load_assays().get("sugar")
    rates = {}
    for dev in (torch.device("cpu"), torch.device("cuda", 0)):  # device-ok: test
        topo = topology(tpl, dev, registry, w_syn=p.w_syn, graded=False)
        rates[dev.type] = run_assay(assay, tpl, topo, p, p.dt_reference, trials=4)
    ag = agreement(rates["cpu"], rates["cuda"], responsive_hz=1.0, top_k=50)
    assert ag.pearson >= 0.9 and ag.top_k_overlap >= 0.8
    # Same counter-based random streams and exact integer sums: the paths agree to the spike.
    assert np.array_equal(rates["cpu"], rates["cuda"])
