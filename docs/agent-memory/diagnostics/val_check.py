"""Validation of the capped production model (registry): rest at 1.4/1.5 mV, odour, Shiu assays."""
import json
from dataclasses import replace
import numpy as np, torch
from flycolony.brain.assays import load_assays, run_assay
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
print("noise_w", setup.params.noise_w, "keep", setup.params.depression_keep, "max |w|/w_syn", float(setup.topo.weight.abs().max()) / setup.params.w_syn)
nr = t.neurons; n = len(nr)
cls = nr["cell_class"].fill_null("").to_numpy(); ct = nr["cell_type"].fill_null("").to_numpy()
sc = nr["super_class"].fill_null("").to_numpy(); sp = setup.topo.spiking.cpu().numpy(); central = (sc == "central") & sp
orn = (cls == "olfactory") & nr["is_sensory"].to_numpy()
assays = load_assays()
for w in (1.5, 1.4):
    p = replace(setup.params, noise_w=w)
    def make(p=p):
        b = BrainBatch(setup.topo, p, setup.dt, plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
        Modulation(t, load_receptors(), load_routes()).attach(b); return b
    b = make()
    for gi, g in enumerate(("none", "DM1")):
        for k in range(4):
            fid = f"{g}{k}"; b.add(FlyBrainSpec(fid, 7000 + 10 * gi + k))
            rates = np.full(orn.sum(), 8.0)
            if g != "none": rates[ct[orn] == f"ORN_{g}"] = 60.0
            b.set_drive(fid, np.where(orn)[0], rates)
    b.run(round(3000 / setup.dt))
    c = torch.zeros(b.batch_size * n, dtype=torch.int64, device=dev)
    b.taps.append(lambda _b, _t, s, c=c: c.index_add_(0, s, torch.ones_like(s)))
    b.run(round(2000 / setup.dt))
    r = c.view(b.batch_size, n).double().cpu().numpy() / 2.0
    rest, odor = r[:4].mean(0), r[4:].mean(0)
    row = {"noise_w": w, "rest_central": rest[central].mean(), "rest_kc": rest[cls == "Kenyon_Cell"].mean(),
           "rest_ln": rest[cls == "ALLN"].mean(), "rest_mn9": rest[ct == "CB0701"].mean(), "rest_cb0216": rest[ct == "CB0216"].mean(),
           "odour_pn_DM1": odor[ct == "DM1_lPN"].mean(), "rest_pn_DM1": rest[ct == "DM1_lPN"].mean(),
           "odour_pn_other": odor[(cls == "ALPN") & (ct != "DM1_lPN")].mean()}
    del b
    if w == 1.4:
        for name in ("sugar", "sugar_bitter", "water"):
            rr = run_assay(assays.get(name), t, setup.topo, p, setup.dt, trials=16, seed=100, make_batch=make)
            row[f"{name}_mn9"] = rr[ct == "CB0701"].mean()
            r0 = run_assay(assays.get(name), t, setup.topo, replace(p, noise_rate=0.0), setup.dt, trials=4, seed=100)
            row[f"{name}_mn9_nonoise"] = r0[ct == "CB0701"].mean()
    print(json.dumps({k: round(float(v), 2) for k, v in row.items()}), flush=True)
