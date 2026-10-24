"""Short-term depression on/off: resting rates (MN9, CB0216, LN, PN, KC), odour and sugar responses."""
import json, sys
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
cfg = load_all()["colony.yaml"]
reg = Registry.load(project_root() / "config" / "params")
t = load_template(template_path(cfg, "female"))
setup = setup_brain(t, dev, cfg, reg)
nr = t.neurons; n = len(nr)
cls = nr["cell_class"].fill_null("").to_numpy(); ct = nr["cell_type"].fill_null("").to_numpy()
sc = nr["super_class"].fill_null("").to_numpy(); sp = setup.topo.spiking.cpu().numpy()
central = (sc == "central") & sp
orn = (cls == "olfactory") & nr["is_sensory"].to_numpy()
kicks = [float(x) for x in sys.argv[1:]] or [1.4]
assays = load_assays()
out = []
for keep in (1.0, setup.params.depression_keep):
    for w in kicks:
        p = replace(setup.params, noise_w=w, depression_keep=keep)
        def make():
            b = BrainBatch(setup.topo, p, setup.dt, plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
            Modulation(t, load_receptors(), load_routes()).attach(b)
            return b
        b = make()
        groups = ["none", "DM1"]
        for gi, g in enumerate(groups):
            for k in range(4):
                fid = f"{g}{k}"; b.add(FlyBrainSpec(fid, 7000 + 10 * gi + k))
                rates = np.full(orn.sum(), 8.0)
                if g != "none":
                    rates[ct[orn] == f"ORN_{g}"] = 60.0
                b.set_drive(fid, np.where(orn)[0], rates)
        b.run(round(3000 / setup.dt))
        c = torch.zeros(b.batch_size * n, dtype=torch.int64, device=dev)
        b.taps.append(lambda _b, _t, s, c=c: c.index_add_(0, s, torch.ones_like(s)))
        b.run(round(2000 / setup.dt))
        r = c.view(b.batch_size, n).double().cpu().numpy() / 2.0
        rest, odor = r[:4].mean(0), r[4:].mean(0)
        fly_central = r[:4][:, central].mean(1)
        row = {"keep": keep, "noise_w": w,
               "rest": {"central": rest[central].mean(), "central_flies": [round(x, 2) for x in fly_central],
                        "kc": rest[cls == "Kenyon_Cell"].mean(), "ln": rest[cls == "ALLN"].mean(),
                        "pn": rest[cls == "ALPN"].mean(), "mn9": rest[ct == "CB0701"].mean(),
                        "cb0216": rest[ct == "CB0216"].mean(), "dn": rest[sc == "descending"].mean()},
               "odour_DM1": {"pn_DM1": odor[ct == "DM1_lPN"].mean(), "pn_DM1_rest": rest[ct == "DM1_lPN"].mean(),
                             "pn_other": odor[(cls == "ALPN") & (ct != "DM1_lPN")].mean(), "ln": odor[cls == "ALLN"].mean()}}
        del b
        for name in ("sugar", "sugar_bitter"):
            a = assays.get(name)
            rr = run_assay(a, t, setup.topo, p, setup.dt, trials=8, seed=100, make_batch=make)
            row[name] = {"mn9": rr[ct == "CB0701"].mean(), "cb0216": rr[ct == "CB0216"].mean(), "central": rr[central].mean()}
        row = json.loads(json.dumps(row, default=float))
        def rnd(d):
            return {k: (rnd(v) if isinstance(v, dict) else round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}
        row = rnd(row); out.append(row); print(json.dumps(row), flush=True)
json.dump(out, open(__file__.replace(".py", ".json"), "w"), indent=1)
