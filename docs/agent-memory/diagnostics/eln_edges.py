"""Remove chemical edges from excitatory AL local neurons onto projection neurons (Yaksi & Wilson 2010)."""
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
sc = nr["super_class"].fill_null("").to_numpy()
sign = nr["sign"].to_numpy()
central = (sc == "central") & sp
kc, pn, ln = (cls == "Kenyon_Cell") & sp, (cls == "ALPN") & sp, (cls == "ALLN") & sp
eln = (cls == "ALLN") & (sign == 1)
indptr = setup.topo.indptr.cpu().numpy()
post = setup.topo.indices.cpu().numpy()
w0 = setup.topo.weight.clone()
wn = w0.cpu().numpy()
pre = np.repeat(np.arange(n), np.diff(indptr))
# output composition of excitatory LNs
m = eln[pre]
tgt = np.where(cls[post[m]] != "", cls[post[m]], sc[post[m]])
tot = np.abs(wn[m]).sum()
comp = {}
for k in np.unique(tgt):
    comp[k] = float(np.abs(wn[m][tgt == k]).sum() / tot)
print("eLN output share by target:", dict(sorted(comp.items(), key=lambda x: -x[1])[:8]))
# ORN->PN vs eLN->PN excitatory weight onto PNs
to_pn = pn[post] | ((cls == "ALPN")[post])
orn = cls == "olfactory"
print("summed weight onto PNs: from ORNs %.0f, from eLNs %.0f, from iLNs %.0f" % (
    wn[orn[pre] & to_pn].sum(), wn[eln[pre] & to_pn].sum(), wn[((cls == "ALLN") & (sign == -1))[pre] & to_pn].sum()))
cuts = {
    "base": np.zeros_like(m),
    "drop_eLN_to_PN": eln[pre] & (cls == "ALPN")[post],
    "drop_eLN_to_PN_and_eLN": eln[pre] & ((cls == "ALPN")[post] | eln[post]),
}
seeds = list(range(7000, 7008)) + list(range(9100, 9108))
B = len(seeds)
res = []
for w in (0.68, 1.0, 1.5):
    for name, cut in cuts.items():
        wt = w0.clone()
        wt[torch.from_numpy(np.where(cut)[0]).to(dev)] = 0
        setup.topo.weight.copy_(wt)
        b = BrainBatch(setup.topo, replace(setup.params, noise_w=w), setup.dt,
                       plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
        Modulation(t, load_receptors(), load_routes()).attach(b)
        for s in seeds:
            b.add(FlyBrainSpec(f"s{s}", s))
        list(b.run(round(5000 / setup.dt)))
        c = torch.zeros(B * n, dtype=torch.int64, device=dev)
        b.taps.append(lambda _b, _t, s, c=c: c.index_add_(0, s, torch.ones_like(s)))
        ev = b.run(round(1000 / setup.dt))
        r = c.view(B, n).double().cpu().numpy()
        fm = r[:, central].mean(1)
        row = dict(w=w, cut=name, edges_cut=int(cut.sum()), ignited=int((fm > 1).sum()),
                   central_hz=round(float(fm.mean()), 2), per_fly=np.round(fm, 1).tolist(),
                   central_median=float(np.median(r[:, central].mean(0))),
                   kc_hz=round(float(r[:, kc].mean()), 2), pn_hz=round(float(r[:, pn].mean()), 2),
                   ln_hz=round(float(r[:, ln].mean()), 2), runaway=sum(e.kind == "brain.runaway" for e in ev))
        res.append(row); print(row, flush=True)
        del b
setup.topo.weight.copy_(w0)
json.dump({"composition": comp, "runs": res}, open(__file__.replace(".py", ".json"), "w"), indent=1)
