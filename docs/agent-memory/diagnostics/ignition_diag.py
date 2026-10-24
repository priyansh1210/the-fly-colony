"""Which populations carry and seed the ignited resting state at brain.noise.w = 0.68 mV."""
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
seeds = list(range(7000, 7008)) + list(range(9100, 9108)) + list(range(11000, 11008))
B = len(seeds)
b = BrainBatch(setup.topo, replace(setup.params, noise_w=0.68), setup.dt,
               plastic_sets=setup.plastic_sets, output_groups=setup.output_groups)
Modulation(t, load_receptors(), load_routes()).attach(b)
for s in seeds:
    b.add(FlyBrainSpec(f"s{s}", s))
T_MS, BIN_MS = 2500, 10
steps = round(T_MS / setup.dt)
spb = round(BIN_MS / setup.dt)
counts = torch.zeros(B * n, dtype=torch.int64, device=dev)
first = torch.full((B * n,), 1 << 40, dtype=torch.int64, device=dev)
bins = torch.zeros(B, steps // spb + 1, dtype=torch.int64, device=dev)
def tap(_b, step, s):
    counts.index_add_(0, s, torch.ones_like(s))
    first[s] = torch.minimum(first[s], torch.full_like(s, step))
    bins[:, step // spb] += torch.bincount(s // n, minlength=B)
b.taps.append(tap)
ev = b.run(steps)
print("events", {k: sum(e.kind == k for e in ev) for k in {e.kind for e in ev}})
rate = (counts.view(B, n).double() / (T_MS / 1000)).cpu().numpy()
first = first.view(B, n).cpu().numpy() * setup.dt
pop = bins.cpu().numpy()[:, :-1] / (BIN_MS / 1000) / sp.sum()  # mean Hz per spiking neuron per bin
late = rate  # whole window
fly_mean = late[:, sp].mean(1)
ign = fly_mean > 1.0
print("fly means", np.round(fly_mean, 2))
print("ignited", int(ign.sum()), "of", B)
# onset: first bin where population rate exceeds 1 Hz
onset = {}
for i in np.where(ign)[0]:
    k = int(np.argmax(pop[i] > 1.0))
    onset[i] = k * BIN_MS
    print(f"fly {seeds[i]} onset ~{k*BIN_MS} ms; pop Hz around onset", np.round(pop[i, max(k-3,0):k+6], 2))
df = nr.select("cell_type", "super_class", "cell_class", "nt_pred", "primary_neuropil", "in_mb", "in_cx").with_columns(
    spiking=pl.Series(sp),
    r_ign=pl.Series(late[ign].mean(0)),
    r_q=pl.Series(late[~ign].mean(0)),
)
df = df.with_columns(excess=(pl.col("r_ign") - pl.col("r_q")))
tot = df["excess"].sum()
out = {}
for col in ("super_class", "cell_class", "nt_pred", "primary_neuropil"):
    g = (df.filter(pl.col("spiking")).group_by(col).agg(
        pl.len().alias("n"), pl.col("r_ign").mean().alias("ign_hz"), pl.col("r_q").mean().alias("quiet_hz"),
        (pl.col("excess").sum() / tot).alias("share_excess"),
        (pl.col("r_ign") > 5).mean().alias("frac_gt5hz"))
        .sort("share_excess", descending=True).head(12))
    print(f"\n== by {col}\n", g)
    out[col] = g.to_dicts()
ct = (df.filter(pl.col("spiking")).group_by("cell_type").agg(
    pl.len().alias("n"), pl.col("super_class").first(), pl.col("nt_pred").first(),
    pl.col("r_ign").mean().alias("ign_hz"), (pl.col("excess").sum() / tot).alias("share"))
    .sort("share", descending=True).head(25))
print("\n== top cell types by share of excess spikes\n", ct)
out["cell_type"] = ct.to_dicts()
# seed: neurons spiking in the 30 ms before onset in ignited flies, vs their quiet-fly first-spike behaviour
seedset = []
for i, k in onset.items():
    w = (first[i] >= k - 30) & (first[i] < k) & sp
    seedset.append(np.where(w)[0])
allseed = np.concatenate(seedset) if seedset else np.array([], int)
if allseed.size:
    s = nr[allseed.tolist()].group_by("super_class", "cell_class").len().sort("len", descending=True).head(15)
    print("\n== neurons first firing in the 30 ms before onset (pooled)\n", s)
    out["pre_onset"] = s.to_dicts()
# concentration: fraction of excess carried by top 1%/5% of neurons
e = np.sort(df.filter(pl.col("spiking"))["excess"].to_numpy())[::-1]
cs = np.cumsum(e) / e.sum()
for p in (0.001, 0.01, 0.05, 0.2):
    print(f"top {p:.1%} of spiking neurons carry {cs[int(p*len(e))]:.1%} of excess")
out["concentration"] = {str(p): float(cs[int(p * len(e))]) for p in (0.001, 0.01, 0.05, 0.2)}
json.dump(out, open(__file__.replace(".py", ".json"), "w"), indent=1, default=str)
