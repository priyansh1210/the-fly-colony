import copy, json, torch
from flycolony.brain.build import template_path
from flycolony.config import load_all
from flycolony.connectome.template import load_template
from flycolony.engine import gates as G
from flycolony.registry import Registry
from flycolony.body.body import GROUNDED
cfg = load_all()["colony.yaml"]; reg = Registry.load()
tpl = load_template(template_path(cfg, "female")); dev = torch.device("cuda")
base = copy.deepcopy(G.load_gates()); g = base["gates"]["sleep"]; g["seconds"] = 15.0
stats = {}
orig = G._Outcome.observe
def observe(self, lp):
    orig(self, lp)
    b = lp.bodies; s = stats.setdefault(id(self), {"n": 0})
    thr = lp.move_threshold
    mv_speed = (b.speed.abs() >= thr); mv_yaw = (b.yaw_rate.abs() >= thr); air = b.mode != GROUNDED
    for k, v in (("speed", mv_speed), ("yaw", mv_yaw), ("air", air)):
        s[k] = s.get(k, 0) + v.double()
    q = ~(mv_speed | mv_yaw | air)
    s["run"] = torch.where(q, s.get("run", torch.zeros_like(b.speed)) + 1, torch.zeros_like(b.speed))
    s["maxrun"] = torch.maximum(s.get("maxrun", torch.zeros_like(b.speed)), s["run"])
    s["n"] += 1
G._Outcome.observe = observe
for arm in ("condition", "control"):
    trials = [G.Trial(arm, 900000 + i, float(i)) for i in range(2)]
    stats.clear()
    G._run_batch(g, base, arm, trials, tpl, cfg, reg, dev)
    s = next(iter(stats.values())); n = s["n"]; dt = 0.0005
    print(arm, "moving-by-speed frac", (s["speed"] / n).tolist(), "by-yaw frac", (s["yaw"] / n).tolist(),
          "airborne frac", (s["air"] / n).tolist(), "longest still run s", (s["maxrun"] * dt).tolist(), flush=True)
print("move_threshold", float(reg.get("life.sleep.move_threshold")), "bout needs", float(reg.get("life.sleep.bout_fly_min")) * 60 / 24, "s neural")
