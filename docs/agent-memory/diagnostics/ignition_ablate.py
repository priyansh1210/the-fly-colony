"""Causal check: which population's output is needed for the ignited resting state."""
import json
from dataclasses import replace
import numpy as np, polars as pl, torch
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
central = (nr["super_class"] == "central").fill_null(False).to_numpy().astype(bool) & sp
kc = (cls == "Kenyon_Cell") & sp
pn = (cls == "ALPN") & sp
ln = cls == "ALLN"
orn = (cls == "olfactory")
print("ORN cell_class count", int(orn.sum()), "LN by nt", {k: int(((nt == k) & ln).sum()) for k in set(nt[ln])})
conds = {
    "base": np.zeros(n, bool),
    "KC_silenced": cls == "Kenyon_Cell",
    "ALLN_all_silenced": ln,
    "ALLN_excitatory_silenced": ln & (nt == "acetylcholine"),
    "ALLN_inhibitory_silenced": ln & np.isin(nt, ["gaba", "glutamate"]),
    "ALPN_silenced": cls == "ALPN",
}
w0 = setup.topo.weight.clone()
indptr = setup.topo.indptr.cpu().numpy()
seeds = list(range(7000, 7008)) + list(range(9100, 9108)) + list(range(11000, 11008))
B = len(seeds)
T_MS = 3000
res = []
for w in (0.68, 1.5):
    for name, mask in conds.items():
        wt = w0.clone()
        for i in np.where(mask)[0]:
            wt[indptr[i]:indptr[i + 1]] = 0
        setup.topo.weight.copy_(wt)
        b = BrainBatch(setup.topo, replace(setup.params, noise_w=w), setup.dt,
                       plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
        Modulation(t, load_receptors(), load_routes()).attach(b)
        for s in seeds:
            b.add(FlyBrainSpec(f"s{s}", s))
        list(b.run(round((T_MS - 1000) / setup.dt)))
        c = torch.zeros(B * n, dtype=torch.int64, device=dev)
        b.taps.append(lambda _b, _t, s, c=c: c.index_add_(0, s, torch.ones_like(s)))
        list(b.run(round(1000 / setup.dt)))
        r = c.view(B, n).double().cpu().numpy()  # last 1 s
        keep = central & ~mask
        fm = r[:, keep].mean(1)
        row = dict(w=w, cond=name, ignited=int((fm > 1).sum()), central_hz=float(fm.mean()),
                   kc_hz=float(r[:, kc & ~mask].mean()) if (kc & ~mask).any() else None,
                   pn_hz=float(r[:, pn & ~mask].mean()) if (pn & ~mask).any() else None)
        res.append(row)
        print(row, flush=True)
        del b
setup.topo.weight.copy_(w0)
# reversibility at 0.68: 8 s, per-fly central rate per second
b = BrainBatch(setup.topo, replace(setup.params, noise_w=0.68), setup.dt,
               plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
Modulation(t, load_receptors(), load_routes()).attach(b)
for s in seeds:
    b.add(FlyBrainSpec(f"s{s}", s))
cm = torch.from_numpy(central).to(dev)
traj = []
for sec in range(8):
    c = torch.zeros(B * n, dtype=torch.int64, device=dev)
    b.taps[:] = [lambda _b, _t, s, c=c: c.index_add_(0, s, torch.ones_like(s))]
    list(b.run(round(1000 / setup.dt)))
    traj.append(c.view(B, n)[:, cm].double().mean(1).cpu().numpy())
traj = np.array(traj).T
print("per-fly central Hz by second (0.68 mV, 8 s):")
for s, row in zip(seeds, traj):
    print(s, np.round(row, 1))
json.dump({"ablation": res, "traj": traj.tolist(), "seeds": seeds}, open(__file__.replace(".py", ".json"), "w"), indent=1)
