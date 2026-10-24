"""What drives MN9 (CB0701) at rest in the closed loop with the new model."""
import json
import numpy as np, polars as pl, torch
from flycolony.brain.build import template_path
from flycolony.config import load_all
from flycolony.config.schemas import project_root
from flycolony.connectome.template import load_template
from flycolony.engine.loop import ClosedLoop, FlyStart
from flycolony.registry import Registry
from flycolony.world.geometry import Arena
from flycolony.world.world import WorldGroup, WorldSpec

dev = torch.device("cuda")
cfg = load_all()["colony.yaml"]
reg = Registry.load(project_root() / "config" / "params")
t = load_template(template_path(cfg, "female"))
nr = t.neurons
n = len(nr)
F = 8
world = WorldGroup(WorldSpec(Arena("box", height=30, size_x=20, size_y=20), n_worlds=F), reg, dev)
loop = ClosedLoop(t, world, cfg, reg, dev)
for i in range(F):
    loop.add(FlyStart(f"r{i}", seed=5000 + i, world=i, xy=(10.0, 10.0), heading=0.0))
loop.run_for(3.0)
c = torch.zeros(F * n, dtype=torch.int64, device=dev)
loop.brain.taps.append(lambda _b, _t, s, c=c: c.index_add_(0, s, torch.ones_like(s)))
loop.run_for(2.0)
r = (c.view(F, n).double() / 2.0).mean(0).cpu().numpy()
ct = nr["cell_type"].fill_null("").to_numpy()
import os
TARGETS = os.environ.get("TARGETS", "CB0701").split(",")
mn9 = np.where(np.isin(ct, TARGETS))[0]
np.save(__file__.replace(".py", "_rates.npy"), r)
print("target ids", mn9.tolist(), "rates", r[mn9].round(1).tolist())
e = t.edges
indptr = np.asarray(e["indptr"]); post = np.asarray(e["indices"]); w = np.asarray(e["weight"], dtype=np.float64)
pre = np.repeat(np.arange(n), np.diff(indptr))
m = np.isin(post, mn9)
contrib = pl.DataFrame({"pre": pre[m], "w": w[m], "rate": r[pre[m]]}).with_columns(drive=pl.col("w") * pl.col("rate"))
contrib = contrib.join(nr.select(pl.col("neuron_id").cast(pl.Int64).alias("pre"), "cell_type", "cell_class", "super_class", "nt_pred"), on="pre")
g = contrib.group_by("cell_type", "cell_class", "super_class", "nt_pred").agg(
    pl.col("w").sum(), pl.col("rate").mean().alias("rate_hz"), pl.col("drive").sum()).sort("drive", descending=True)
pl.Config.set_tbl_rows(30); pl.Config.set_tbl_width_chars(200)
print("excitatory drive total %.0f, inhibitory %.0f" % (g.filter(pl.col("drive") > 0)["drive"].sum(), g.filter(pl.col("drive") < 0)["drive"].sum()))
print(g.head(20))
print(g.sort("drive").head(8))
sc = nr["super_class"].fill_null("").to_numpy(); cls = nr["cell_class"].fill_null("").to_numpy()
summ = {k: float(r[sc == k].mean()) for k in ("central", "sensory", "descending", "motor", "ascending")}
summ.update({k: float(r[cls == k].mean()) for k in ("Kenyon_Cell", "ALLN", "ALPN", "gustatory", "olfactory")})
print({k: round(v, 2) for k, v in summ.items()})
g.write_csv(__file__.replace(".py", ".csv"))
