import torch
from flycolony.brain.build import template_path
from flycolony.config import load_all
from flycolony.connectome.template import load_template
from flycolony.engine.gates import load_gates, run_gate
from flycolony.registry import Registry
cfg = load_all()["colony.yaml"]; reg = Registry.load()
tpl = load_template(template_path(cfg, "female"))
rep = run_gate("feeding", tpl, cfg, reg, torch.device("cuda"), trials=4, write=False, protocols=load_gates())
print(rep["summary"], rep["wall_s"])
for t in rep["trials"]: print(t["arm"], round(t["max_extension"], 3), round(t["ingested_mm3"], 4))
