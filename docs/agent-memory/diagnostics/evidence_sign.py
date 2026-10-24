"""Evidence-ranked transmitter -> sign: known_nt (experimental) > cell-type consensus > current sign."""
import json, re
from dataclasses import replace
import numpy as np, polars as pl, torch
from flycolony.brain.build import setup_brain, template_path
from flycolony.brain.engine import BrainBatch, FlyBrainSpec
from flycolony.brain.modulation import Modulation, load_receptors, load_routes
from flycolony.config import load_all
from flycolony.config.schemas import project_root
from flycolony.connectome.template import load_template
from flycolony.registry import Registry

SIGN = {"acetylcholine": 1, "gaba": -1, "glutamate": -1, "histamine": -1,
        "dopamine": 1, "serotonin": 1, "octopamine": 1}
cfg = load_all()["colony.yaml"]
t = load_template(template_path(cfg, "female"))
nr = t.neurons
a = pl.read_csv(project_root() / "data/raw/fafb783_annotations/Supplemental_file1_neuron_annotations.tsv",
                separator="\t", infer_schema_length=0, columns=["root_id", "known_nt", "top_nt", "top_nt_conf", "cell_type"])
def known(s):
    if s is None: return None
    toks = {x.strip() for x in re.split(r"[;,]", s)}
    fast = {x for x in toks if x in SIGN}
    return fast.pop() if len(fast) == 1 else None
a = a.with_columns(pl.col("known_nt").map_elements(known, return_dtype=pl.String).alias("known"),
                   pl.col("top_nt_conf").cast(pl.Float64, strict=False).alias("conf"))
# type consensus: confidence-weighted vote of per-neuron predictions within a cell type
cons = (a.filter(pl.col("cell_type").is_not_null(), pl.col("top_nt").is_not_null())
        .group_by("cell_type", "top_nt").agg(pl.col("conf").sum().alias("w"), pl.len().alias("k"))
        .with_columns((pl.col("w") / pl.col("w").sum().over("cell_type")).alias("share"))
        .sort("w", descending=True).group_by("cell_type").first()
        .filter(pl.col("share") >= 0.5).select("cell_type", pl.col("top_nt").alias("consensus")))
a = a.join(cons, on="cell_type", how="left")
m = nr.select("source_id", "cell_type", "cell_class", "super_class", "nt_pred", "sign", "sign_source").with_columns(
    pl.col("source_id").cast(pl.String)).join(a.select("root_id", "known", "consensus"), left_on="source_id", right_on="root_id", how="left")
assert len(m) == len(nr)
m = m.with_columns(
    pl.when(pl.col("known").is_not_null()).then(pl.col("known"))
      .when(pl.col("consensus").is_not_null()).then(pl.col("consensus")).otherwise(None).alias("evidence_nt"))
m = m.with_columns(
    pl.when(pl.col("sign_source") == "exception").then(pl.col("sign"))
      .when(pl.col("evidence_nt").is_not_null()).then(pl.col("evidence_nt").replace_strict(SIGN, default=None, return_dtype=pl.Int8))
      .otherwise(pl.col("sign")).alias("sign_new"))
print("neurons with known_nt:", m["known"].is_not_null().sum(), " consensus only:", (m["known"].is_null() & m["consensus"].is_not_null()).sum())
ch = m.filter(pl.col("sign_new") != pl.col("sign"))
print("sign changes:", len(ch))
print(ch.group_by("super_class", "sign", "sign_new").len().sort("len", descending=True).head(12))
print("ALLN changes:", ch.filter(pl.col("cell_class") == "ALLN").group_by("nt_pred", "sign", "sign_new").len())
print("ALLN DA/5HT now:", m.filter(pl.col("cell_class") == "ALLN", pl.col("nt_pred").is_in(["dopamine", "serotonin"])).group_by("evidence_nt", "sign_new").len())
sign_new = m["sign_new"].to_numpy()
np.save(__file__.replace(".py", "_signs.npy"), sign_new)

dev = torch.device("cuda")
reg = Registry.load(project_root() / "config" / "params")
setup = setup_brain(t, dev, cfg, reg)
n = len(nr)
sp = setup.topo.spiking.cpu().numpy()
cls = nr["cell_class"].fill_null("").to_numpy()
central = (nr["super_class"] == "central").fill_null(False).to_numpy().astype(bool) & sp
kc, pn, ln = (cls == "Kenyon_Cell") & sp, (cls == "ALPN") & sp, (cls == "ALLN") & sp
flip = sign_new != nr["sign"].to_numpy()
zero = sign_new == 0
w0 = setup.topo.weight.clone()
indptr = setup.topo.indptr.cpu().numpy()
wt = w0.clone()
for i in np.where(flip)[0]:
    seg = wt[indptr[i]:indptr[i + 1]]
    old = int(nr["sign"][int(i)])
    wt[indptr[i]:indptr[i + 1]] = seg.abs() * int(sign_new[i]) if old != 0 else seg  # old==0 has no magnitude info
setup.topo.weight.copy_(wt)
seeds = list(range(7000, 7008)) + list(range(9100, 9108))
B = len(seeds)
res = []
for w in (0.68, 1.0, 1.5, 2.0):
    b = BrainBatch(setup.topo, replace(setup.params, noise_w=w), setup.dt,
                   plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
    Modulation(t, load_receptors(), load_routes()).attach(b)
    for s in seeds:
        b.add(FlyBrainSpec(f"s{s}", s))
    cm = torch.from_numpy(central).to(dev)
    traj = []
    tot = torch.zeros(B * n, dtype=torch.int64, device=dev)
    ev = []
    for sec in range(6):
        c = torch.zeros(B * n, dtype=torch.int64, device=dev)
        b.taps[:] = [lambda _b, _t, s, c=c: c.index_add_(0, s, torch.ones_like(s))]
        ev += b.run(round(1000 / setup.dt))
        traj.append(c.view(B, n)[:, cm].double().mean(1).cpu().numpy())
        if sec >= 3: tot += c
    r = tot.view(B, n).double().cpu().numpy() / 3
    fm = r[:, central].mean(1)
    row = dict(w=w, per_fly_central_last3s=np.round(fm, 2).tolist(),
               central_hz=round(float(fm.mean()), 2), central_median_hz=float(np.median(r[:, central].mean(0))),
               silent=round(float((r[:, central].mean(0) == 0).mean()), 2),
               kc_hz=round(float(r[:, kc].mean()), 2), pn_hz=round(float(r[:, pn].mean()), 2), ln_hz=round(float(r[:, ln].mean()), 2),
               runaway=sum(e.kind == "brain.runaway" for e in ev),
               traj_fly_sec=np.round(np.array(traj).T, 1).tolist())
    res.append(row)
    print({k: v for k, v in row.items() if k != "traj_fly_sec"}, flush=True)
    del b
setup.topo.weight.copy_(w0)
json.dump(res, open(__file__.replace(".py", ".json"), "w"), indent=1)
