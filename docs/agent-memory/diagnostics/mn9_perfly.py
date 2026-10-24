"""Per-fly MN9 / CB0216 in the closed loop at rest (M8 conditions), and top drivers in high flies."""
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
cfg = load_all()["colony.yaml"]; reg = Registry.load(project_root() / "config" / "params")
t = load_template(template_path(cfg, "female")); nr = t.neurons; n = len(nr)
F = 32
world = WorldGroup(WorldSpec(Arena("box", height=30, size_x=20, size_y=20), n_worlds=F), reg, dev)
loop = ClosedLoop(t, world, cfg, reg, dev)
for i in range(F):
    loop.add(FlyStart(f"r{i}", seed=5000 + i, world=i, xy=(10.0, 10.0), heading=0.0))
loop.run_for(3.0)
c = torch.zeros(F * n, dtype=torch.int64, device=dev)
loop.brain.taps.append(lambda _b, _t, s, c=c: c.index_add_(0, s, torch.ones_like(s)))
loop.run_for(2.0)
r = c.view(F, n).double().cpu().numpy() / 2.0
ct = nr["cell_type"].fill_null("").to_numpy()
mn9 = r[:, ct == "CB0701"].mean(1); cb = r[:, ct == "CB0216"].mean(1)
print("MN9 per fly", np.round(mn9, 1).tolist()); print("CB0216 per fly", np.round(cb, 1).tolist())
hi = np.argsort(-mn9)[:3]; lo = np.argsort(mn9)[:8]
e = t.edges; indptr = np.asarray(e["indptr"]); post = np.asarray(e["indices"]); w = np.clip(np.asarray(e["weight"], dtype=np.float64), -250, 250)
pre = np.repeat(np.arange(n), np.diff(indptr)); ids = np.where(ct == "CB0701")[0]; m = np.isin(post, ids)
d = pl.DataFrame({"pre": pre[m], "w": w[m], "hi": r[hi][:, pre[m]].mean(0), "lo": r[lo][:, pre[m]].mean(0)})
d = d.join(nr.select(pl.col("neuron_id").cast(pl.Int64).alias("pre"), "cell_type", "super_class"), on="pre")
d = d.group_by("cell_type", "super_class").agg(pl.col("w").sum(), pl.col("hi").mean(), pl.col("lo").mean()).with_columns(drive_hi=pl.col("w") * pl.col("hi"), drive_lo=pl.col("w") * pl.col("lo")).sort("drive_hi", descending=True)
pl.Config.set_tbl_rows(15); pl.Config.set_tbl_width_chars(200); print(d.head(12))
