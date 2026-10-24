"""Sugar -> MN9 ablation: which global production component weakens the response?"""
import itertools, json, sys, time
from dataclasses import replace
import numpy as np, torch
from flycolony.brain.assays import load_assays, resolve_readouts, run_assay
from flycolony.brain.build import template_path, topology, setup_brain
from flycolony.brain.modulation import load_receptors, load_routes
from flycolony.brain.engine import BrainBatch
from flycolony.brain.modulation import Modulation
from flycolony.brain.params import NeuronParams
from flycolony.config import load_all
from flycolony.connectome.template import load_template
from flycolony.registry import Registry

dev = torch.device("cuda")
cfg = load_all()["colony.yaml"]; reg = Registry.load()
tpl = load_template(template_path(cfg, "female"))
assays = load_assays()
sugar = assays.get("sugar")
mn9 = resolve_readouts(sugar, tpl)["mn9"]
prod_dt = setup_brain(tpl, dev, cfg, reg).dt
TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 8
def run(noise, graded, modulated, dt, rate=150.0):
    p = NeuronParams.from_registry(reg, reference=not noise)
    topo = topology(tpl, dev, reg, w_syn=p.w_syn, graded=graded, weights="fp32")
    a = sugar.model_copy(deep=True); a.drive[0].rate_hz = rate
    def mk():
        b = BrainBatch(topo, p, dt)
        if modulated:
            Modulation(tpl, load_receptors(), load_routes()).attach(b)
        return b
    t = time.perf_counter()
    r = run_assay(a, tpl, topo, p, dt, trials=TRIALS, make_batch=mk)
    return r[mn9].mean(), time.perf_counter() - t
rows = []
configs = [
    ("production", True, True, True, prod_dt),
    ("reference", False, False, False, 0.1),
    ("prod - noise", False, True, True, prod_dt),
    ("prod - graded", True, False, True, prod_dt),
    ("prod - modulation", True, True, False, prod_dt),
    ("prod @ dt 0.1", True, True, True, 0.1),
    ("ref + noise", True, False, False, 0.1),
    ("ref + graded", False, True, False, 0.1),
    ("ref + modulation", False, False, True, 0.1),
    ("ref @ prod dt", False, False, False, prod_dt),
]
for name, *c in configs:
    hz, s = run(*c)
    rows.append({"config": name, "noise": c[0], "graded": c[1], "modulated": c[2], "dt": c[3], "mn9_hz": float(hz)})
    print(f"{name:20s} MN9 {hz:6.1f} Hz   ({s:.0f} s)", flush=True)
json.dump(rows, open(sys.argv[2] if len(sys.argv) > 2 else "mn9_diag.json", "w"), indent=1)
