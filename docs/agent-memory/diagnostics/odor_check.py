"""Odour responses with and without the electrical-pair rule: ORN spont 8 Hz, one glomerulus at 60 Hz."""
import json
from dataclasses import replace
import numpy as np, polars as pl, torch
from flycolony.brain import build as bb
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
setup = setup_brain(t, dev, cfg, reg)  # rule on (registry)
nr = t.neurons
n = len(nr)
cls = nr["cell_class"].fill_null("").to_numpy()
ct = nr["cell_type"].fill_null("").to_numpy()
sc = nr["super_class"].fill_null("").to_numpy()
sp = setup.topo.spiking.cpu().numpy()
central = (sc == "central") & sp
orn = (cls == "olfactory") & nr["is_sensory"].to_numpy()
GLOMS = {"DM1": "DM1_lPN", "DL5": "DL5_adPN", "VA2": "VA2_adPN"}
rule_w = setup.topo.weight.clone()
from flycolony.brain.topology import electrical_edges
cut = electrical_edges(t, tuple(reg.get("brain.electrical.excitatory_pairs")))
base_w = rule_w.clone()
# restore original weights on cut edges from the template
ew = np.asarray(t.edges["weight"], dtype=np.float64)[cut] * setup.params.w_syn
base_w[torch.from_numpy(cut).to(dev)] = torch.from_numpy(ew.astype(np.float32)).to(dev)
print("cut edges", cut.size)
groups = ["none"] + list(GLOMS)
per = 4
res = []
for label, W in (("base", base_w), ("rule", rule_w)):
    for w in (0.0, 1.0, 1.5):
        setup.topo.weight.copy_(W)
        b = BrainBatch(setup.topo, replace(setup.params, noise_w=w), setup.dt,
                       plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
        Modulation(t, load_receptors(), load_routes()).attach(b)
        ids = []
        for gi, g in enumerate(groups):
            for k in range(per):
                fid = f"{g}{k}"
                b.add(FlyBrainSpec(fid, 7000 + 10 * gi + k))
                rates = np.full(orn.sum(), 8.0)
                if g != "none":
                    rates[ct[orn] == f"ORN_{g}"] = 60.0
                b.set_drive(fid, np.where(orn)[0], rates)
        list(b.run(round(3000 / setup.dt)))
        c = torch.zeros(b.batch_size * n, dtype=torch.int64, device=dev)
        b.taps.append(lambda _b, _t, s, c=c: c.index_add_(0, s, torch.ones_like(s)))
        list(b.run(round(1000 / setup.dt)))
        r = c.view(b.batch_size, n).double().cpu().numpy()
        rows = {}
        for gi, g in enumerate(groups):
            rr = r[gi * per:(gi + 1) * per]
            d = {"central_hz": float(rr[:, central].mean()), "kc_hz": float(rr[:, cls == "Kenyon_Cell"].mean()),
                 "ln_hz": float(rr[:, cls == "ALLN"].mean()), "all_pn_hz": float(rr[:, cls == "ALPN"].mean()),
                 "lhn_hz": float(rr[:, (cls == "LHLN") | (cls == "LHCENT")].mean())}
            for gg, pnt in GLOMS.items():
                d[f"pn_{gg}"] = float(rr[:, ct == pnt].mean())
            rows[g] = {k: round(v, 2) for k, v in d.items()}
        row = {"weights": label, "noise_w": w, "groups": rows}
        res.append(row); print(json.dumps(row), flush=True)
        del b
setup.topo.weight.copy_(rule_w)
json.dump(res, open(__file__.replace(".py", ".json"), "w"), indent=1)
