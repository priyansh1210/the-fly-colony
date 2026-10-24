"""Build the Phase-2 run report (HTML) from the stored gate reports.

    python build_report.py <repo> <out.html>
"""

import json
import sys
from pathlib import Path

repo, out = Path(sys.argv[1]), Path(sys.argv[2])
here = Path(__file__).parent
rep_dir = repo / "specs" / "005-motor" / "reports"
TPL = "female-fafb783-t2"


def load(name):
    p = rep_dir / f"{TPL}.{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


gates = {}
for name in ("feeding", "bitter", "plume", "sleep", "no_self_motion", "looming"):
    r = load(name)
    if r is None:
        gates[name] = {"status": "pending"}
        continue
    g = {k: r.get(k) for k in ("id", "status", "passed", "summary", "wall_s", "reason")}
    if r.get("trials"):
        keep = ("arm", "seed", "max_extension", "ingested_mm3", "min_distance_mm", "value",
                "any_primitive", "max_displacement_mm", "success")
        g["trials"] = [{k: t[k] for k in keep if k in t} for t in r["trials"]]
    gates[name] = g
any_rep = next(load(n) for n in ("feeding", "bitter", "no_self_motion") if load(n))
versions = {k: any_rep[k] for k in ("template", "pipeline_version", "registry_hash", "model_hash",
                                     "config_hash", "gates_hash", "brain_dt_ms", "vision_mode")}
openloop = json.loads((rep_dir / f"{TPL}.openloop.json").read_text(encoding="utf-8"))
calib = json.loads((rep_dir / f"{TPL}.motor-calibration.json").read_text(encoding="utf-8"))
ablation = json.loads((here / "mn9_diag.json").read_text(encoding="utf-8"))
data = {
    "gates": gates,
    "versions": versions,
    "openloop": [
        {"check": r["check"], "n": r["n_neurons"],
         "levels": {k: v["positive"] for k, v in r["levels"].items()}}
        for r in openloop["results"]
    ],
    "calib": {
        k: {kk: v[kk] for kk in ("mean_hz", "p99_hz", "calibrated_threshold_hz", "current_threshold_hz")}
        for k, v in calib["primitives"].items()
    },
    "moving_fraction": calib["fraction_of_steps_moving"],
    "ablation": ablation,
}
html = (here / "report_template.html").read_text(encoding="utf-8")
html = html.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
out.write_text(html, encoding="utf-8", newline="\n")
print("wrote", out, len(html) // 1024, "KB")
