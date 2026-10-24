"""Why does sugar -> MN9 fail with depression? 10 ms bins at onset; variants."""
import json
from dataclasses import replace
import numpy as np, torch
from flycolony.brain.build import setup_brain, template_path
from flycolony.brain.engine import BrainBatch, FlyBrainSpec
from flycolony.brain.modulation import Modulation, load_receptors, load_routes
from flycolony.brain.assays import load_assays, resolve_stimulus
from flycolony.config import load_all
from flycolony.config.schemas import project_root
from flycolony.connectome.template import load_template
from flycolony.registry import Registry

dev = torch.device("cuda")
cfg = load_all()["colony.yaml"]; reg = Registry.load(project_root() / "config" / "params")
t = load_template(template_path(cfg, "female")); setup = setup_brain(t, dev, cfg, reg)
nr = t.neurons; n = len(nr)
ct = nr["cell_type"].fill_null("").to_numpy()
sugar = resolve_stimulus(load_assays().get("sugar"), t)[0].neuron_ids
mn9 = np.where(ct == "CB0701")[0]
sens = setup.topo.sensory
BIN = 10.0; F = 8
for keep, w, excl in ((1.0, 0.0, False), (0.78, 0.0, False), (0.78, 1.4, False), (0.78, 0.0, True), (0.78, 1.4, True)):
    p = replace(setup.params, depression_keep=keep, noise_w=w, noise_rate=setup.params.noise_rate if w else 0.0)
    b = BrainBatch(setup.topo, p, setup.dt, plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
    Modulation(t, load_receptors(), load_routes()).attach(b)
    if excl:
        orig = b._efficacy
        def eff(tt, spikes, orig=orig):
            a = orig(tt, spikes)
            return torch.where(sens[spikes % n], torch.ones_like(a), a)
        b._efficacy = eff
    for i in range(F):
        b.add(FlyBrainSpec(f"f{i}", 900 + i))
    b.run(round(1000 / setup.dt))
    m = torch.zeros(n, dtype=torch.bool, device=dev); m[mn9] = True
    cnt = torch.zeros((), device=dev)
    b.taps.append(lambda _b, _t, s: cnt.add_(m[s % n].sum()))
    for i in range(F):
        b.set_drive(f"f{i}", sugar, np.full(sugar.size, 150.0))
    tr = []
    for _ in range(50):
        cnt.zero_(); b.run(round(BIN / setup.dt)); tr.append(round(float(cnt) / (F * mn9.size) / (BIN / 1000)))
    print(f"keep={keep} noise={w} sensory_excluded={excl}: first 100 ms {tr[:10]} | 100-500 ms mean {np.mean(tr[10:]):.1f}", flush=True)
    del b
