"""Time course of MN9 (sugar 150 Hz) and DM1 PNs (ORN_DM1 60 Hz) at stimulus onset, depression off/on."""
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
cls = nr["cell_class"].fill_null("").to_numpy(); ct = nr["cell_type"].fill_null("").to_numpy()
orn = np.where((cls == "olfactory") & nr["is_sensory"].to_numpy())[0]
sugar = resolve_stimulus(load_assays().get("sugar"), t)[0].neuron_ids
mn9 = np.where(ct == "CB0701")[0]; dm1 = np.where(ct == "DM1_lPN")[0]
BIN = 50.0; F = 8
out = {}
for keep in (1.0, setup.params.depression_keep):
    p = replace(setup.params, depression_keep=keep)
    b = BrainBatch(setup.topo, p, setup.dt, plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
    Modulation(t, load_receptors(), load_routes()).attach(b)
    for i in range(F):
        b.add(FlyBrainSpec(f"f{i}", 900 + i))
        b.set_drive(f"f{i}", orn, np.full(orn.size, 8.0))
    b.run(round(2000 / setup.dt))
    steps_bin = round(BIN / setup.dt)
    traces = {"mn9": [], "dm1": []}
    mask_m = torch.zeros(n, dtype=torch.bool, device=dev); mask_m[mn9] = True
    mask_d = torch.zeros(n, dtype=torch.bool, device=dev); mask_d[dm1] = True
    cnt = {"mn9": torch.zeros((), device=dev), "dm1": torch.zeros((), device=dev)}
    def tap(_b, _t, s):
        loc = s % n
        cnt["mn9"] += mask_m[loc].sum(); cnt["dm1"] += mask_d[loc].sum()
    b.taps.append(tap)
    def run_bins(k):
        for _ in range(k):
            for key in cnt: cnt[key].zero_()
            b.run(steps_bin)
            traces["mn9"].append(float(cnt["mn9"]) / (F * mn9.size) / (BIN / 1000))
            traces["dm1"].append(float(cnt["dm1"]) / (F * dm1.size) / (BIN / 1000))
    run_bins(4)  # 200 ms baseline
    for i in range(F):
        rates = np.full(orn.size, 8.0); rates[ct[orn] == "ORN_DM1"] = 60.0
        ids = np.concatenate([orn, sugar]); r = np.concatenate([rates, np.full(sugar.size, 150.0)])
        b.set_drive(f"f{i}", ids, r)
    run_bins(20)  # 1 s stimulus
    out[str(keep)] = {k: [round(x, 1) for x in v] for k, v in traces.items()}
    print(keep, json.dumps(out[str(keep)]), flush=True)
    del b
json.dump(out, open(__file__.replace(".py", ".json"), "w"))
