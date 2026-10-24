"""Which neurons keep firing after background noise is switched off (self-sustained), per cap K."""
import sys
from collections import Counter
from dataclasses import replace
import numpy as np, torch
from flycolony.brain.build import setup_brain, template_path
from flycolony.brain.engine import BrainBatch, FlyBrainSpec
from flycolony.brain.modulation import Modulation, load_receptors, load_routes
from flycolony.config import load_all
from flycolony.config.schemas import project_root
from flycolony.connectome.template import load_template
from flycolony.registry import Registry

dev = torch.device("cuda")
cfg = load_all()["colony.yaml"]; reg = Registry.load(project_root() / "config" / "params")
t = load_template(template_path(cfg, "female")); setup = setup_brain(t, dev, cfg, reg)
nr = t.neurons; n = len(nr)
ct = nr["cell_type"].fill_null("?").to_numpy(); cls = nr["cell_class"].fill_null("?").to_numpy()
W0 = setup.topo.weight.clone(); ws = setup.params.w_syn
p = replace(setup.params, depression_keep=1.0)
F = 8
for K in [None if a == "none" else float(a) for a in sys.argv[1:]]:
    setup.topo.weight.copy_(W0 if K is None else W0.clamp(-K * ws, K * ws))
    b = BrainBatch(setup.topo, p, setup.dt, plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
    Modulation(t, load_receptors(), load_routes()).attach(b)
    for i in range(F): b.add(FlyBrainSpec(f"f{i}", 7000 + i))
    b.run(round(3000 / setup.dt))
    b.k = replace(b.k, p_noise=0.0)  # switch background input off
    b.run(round(500 / setup.dt))
    c = torch.zeros(F * n, dtype=torch.int64, device=dev)
    b.taps.append(lambda _b, _t, s: c.index_add_(0, s, torch.ones_like(s)))
    b.run(round(500 / setup.dt))
    r = c.view(F, n).double().cpu().numpy() / 0.5
    lat = r >= 10.0
    ids = np.where(lat.any(0))[0]
    print(f"K={K}: latched neurons (>=10 Hz, any fly) {ids.size}, per fly {lat.sum(1).tolist()}, total spikes/s {r.sum(1).round().tolist()}")
    print("   by class", Counter(cls[ids]).most_common(8))
    print("   by type ", Counter(ct[ids]).most_common(12), flush=True)
    del b
setup.topo.weight.copy_(W0)
