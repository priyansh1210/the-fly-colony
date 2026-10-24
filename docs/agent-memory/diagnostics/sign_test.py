"""Do mis-signed antennal-lobe local neurons drive the ignited state? Silence or re-sign by rule."""
import json
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
cfg = load_all()["colony.yaml"]
reg = Registry.load(project_root() / "config" / "params")
t = load_template(template_path(cfg, "female"))
setup = setup_brain(t, dev, cfg, reg)
nr = t.neurons
n = len(nr)
sp = setup.topo.spiking.cpu().numpy()
cls = nr["cell_class"].fill_null("").to_numpy()
nt = nr["nt_pred"].fill_null("").to_numpy()
sign = nr["sign"].to_numpy()
central = (nr["super_class"] == "central").fill_null(False).to_numpy().astype(bool) & sp
kc = (cls == "Kenyon_Cell") & sp
pn = (cls == "ALPN") & sp
ln = cls == "ALLN"
rule = np.where(np.isin(nt, ["gaba", "glutamate"]), -1, 1)
rule[nt == ""] = sign[nt == ""]
w0 = setup.topo.weight.clone()
indptr = setup.topo.indptr.cpu().numpy()
i0 = int(np.where(ln & (sign == -1))[0][0]); print("weight sign check (inhib LN out):", float(w0[indptr[i0]:indptr[i0+1]].sum()))
ACTIONS = {
    "base": ({}, {}),
    "silence_ALLN_sign+1": (ln & (sign == 1), None),
    "silence_ALLN_gabaglu_sign+1": (ln & (sign == 1) & np.isin(nt, ["gaba", "glutamate"]), None),
    "silence_ALLN_DA_5HT": (ln & np.isin(nt, ["dopamine", "serotonin"]), None),
    "resign_ALLN_by_transmitter": (None, ln & (rule != sign)),
    "resign_all_by_transmitter": (None, rule != sign),
}
print({k: int(v[0].sum()) if isinstance(v[0], np.ndarray) else int(v[1].sum()) if isinstance(v[1], np.ndarray) else 0 for k, v in ACTIONS.items()})
seeds = list(range(7000, 7008)) + list(range(9100, 9108)) + list(range(11000, 11008))
B = len(seeds)
res = []
for w in (0.68, 1.5):
    for name, (sil, flip) in ACTIONS.items():
        wt = w0.clone()
        if isinstance(sil, np.ndarray):
            for i in np.where(sil)[0]:
                wt[indptr[i]:indptr[i + 1]] = 0
        if isinstance(flip, np.ndarray):
            for i in np.where(flip)[0]:
                wt[indptr[i]:indptr[i + 1]] *= -1
        setup.topo.weight.copy_(wt)
        b = BrainBatch(setup.topo, replace(setup.params, noise_w=w), setup.dt,
                       plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
        Modulation(t, load_receptors(), load_routes()).attach(b)
        for s in seeds:
            b.add(FlyBrainSpec(f"s{s}", s))
        list(b.run(round(4000 / setup.dt)))
        c = torch.zeros(B * n, dtype=torch.int64, device=dev)
        b.taps.append(lambda _b, _t, s, c=c: c.index_add_(0, s, torch.ones_like(s)))
        ev = b.run(round(1000 / setup.dt))
        r = c.view(B, n).double().cpu().numpy()
        fm = r[:, central].mean(1)
        row = dict(w=w, action=name, ignited=int((fm > 1).sum()), central_hz=round(float(fm.mean()), 2),
                   central_median_hz=float(np.median(r[:, central].mean(0))),
                   kc_hz=round(float(r[:, kc].mean()), 2), pn_hz=round(float(r[:, pn].mean()), 2),
                   ln_hz=round(float(r[:, ln & sp].mean()), 2), runaway=sum(e.kind == "brain.runaway" for e in ev))
        res.append(row); print(row, flush=True)
        del b
setup.topo.weight.copy_(w0)
json.dump(res, open(__file__.replace(".py", ".json"), "w"), indent=1)
