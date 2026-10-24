"""Feeding gate diagnostic: proboscis/ingestion group rates vs thresholds, sucrose vs water, 16 flies."""
import numpy as np, torch
from flycolony.engine import gates as G
from flycolony.brain.build import template_path
from flycolony.config import load_all
from flycolony.config.schemas import project_root
from flycolony.connectome.template import load_template
from flycolony.registry import Registry

dev = torch.device("cuda")
cfg = load_all()["colony.yaml"]; reg = Registry.load(project_root() / "config" / "params")
t = load_template(template_path(cfg, "female"))
gates = G.load_gates(); g = gates["gates"]["feeding"]; base = gates
store = {}
class Out(G._Outcome):
    def __init__(s, *a, **k):
        super().__init__(*a, **k); s.tr = []
    def observe(s, lp):
        super().observe(lp)
        b = lp.brain
        s.tr.append(b.rates.clone())
        store["names"] = b.group_names
        store["tr"] = s.tr
        store["sense"] = getattr(lp, "senses", None)
G._Outcome = Out
for arm in ("condition", "control"):
    trials = G._trials(g, 0, base, (arm,), 16)
    res, _ = G._run_batch(g, base, arm, trials, t, cfg, reg, dev)
    tr = torch.stack(store["tr"]).cpu().numpy()  # [T, B, groups]
    names = store["names"]
    for gname in ("feeding.proboscis_extension", "feeding.ingestion"):
        if gname in names:
            x = tr[:, :, names.index(gname)]
            print(f"{arm:9s} {gname:28s} mean {x.mean():6.1f}  per-fly max {np.round(x.max(0),0).tolist()}")
    print(arm, "max_ext", [round(r['max_extension'], 3) for r in res], "ingested>0", sum(r['ingested_mm3'] > 0 for r in res))
print("thresholds: proboscis", reg.get("motor.proboscis.threshold_hz"), "ingestion", reg.get("motor.ingestion.threshold_hz"), "min_ext", reg.get("gate.feed.min_extension"))
