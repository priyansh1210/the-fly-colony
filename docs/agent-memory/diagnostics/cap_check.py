"""Diagnostic: cap per-connection |synapse count| at K (no depression). Rest + sugar MN9."""
from dataclasses import replace
import numpy as np, torch
from flycolony.brain.build import setup_brain, template_path
from flycolony.brain.engine import BrainBatch, FlyBrainSpec
from flycolony.brain.modulation import Modulation, load_receptors, load_routes
from flycolony.brain.assays import load_assays, run_assay
from flycolony.config import load_all
from flycolony.config.schemas import project_root
from flycolony.connectome.template import load_template
from flycolony.registry import Registry

dev = torch.device("cuda")
cfg = load_all()["colony.yaml"]; reg = Registry.load(project_root() / "config" / "params")
t = load_template(template_path(cfg, "female")); setup = setup_brain(t, dev, cfg, reg)
nr = t.neurons; n = len(nr)
ct = nr["cell_type"].fill_null("").to_numpy(); cls = nr["cell_class"].fill_null("").to_numpy()
sc = nr["super_class"].fill_null("").to_numpy(); sp = setup.topo.spiking.cpu().numpy(); central = (sc == "central") & sp
W0 = setup.topo.weight.clone(); ws = setup.params.w_syn
p = replace(setup.params, depression_keep=1.0)
assays = load_assays()
for K in (None, 200, 100, 50):
    setup.topo.weight.copy_(W0 if K is None else W0.clamp(-K * ws, K * ws))
    def make():
        b = BrainBatch(setup.topo, p, setup.dt, plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
        Modulation(t, load_receptors(), load_routes()).attach(b); return b
    b = make()
    for i in range(8): b.add(FlyBrainSpec(f"f{i}", 7000 + i))
    b.run(round(3000 / setup.dt))
    c = torch.zeros(8 * n, dtype=torch.int64, device=dev)
    b.taps.append(lambda _b, _t, s: c.index_add_(0, s, torch.ones_like(s)))
    b.run(round(2000 / setup.dt))
    r = c.view(8, n).double().mean(0).cpu().numpy() / 2
    del b
    out = {}
    for name in ("sugar", "sugar_bitter"):
        rr = run_assay(assays.get(name), t, setup.topo, p, setup.dt, trials=8, seed=100, make_batch=make)
        out[name] = round(float(rr[ct == "CB0701"].mean()), 1)
    pr = replace(p, noise_rate=0.0)
    rr = run_assay(assays.get("sugar"), t, setup.topo, pr, setup.dt, trials=8, seed=100)
    print(f"cap={K}: edges capped {int((W0.abs() > (K or 1e9) * ws).sum())} | rest central {r[central].mean():.2f} KC {r[cls=='Kenyon_Cell'].mean():.2f} "
          f"LN {r[cls=='ALLN'].mean():.1f} MN9 {r[ct=='CB0701'].mean():.1f} CB0216 {r[ct=='CB0216'].mean():.1f} | "
          f"sugar MN9 {out['sugar']} sugar+bitter {out['sugar_bitter']} | sugar no-noise MN9 {float(rr[ct=='CB0701'].mean()):.1f}", flush=True)
setup.topo.weight.copy_(W0)
