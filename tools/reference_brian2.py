"""Brian2 reference harness (BRAIN-R-080): run an assay with the unmodified Shiu et al. model.

Usage (needs the `reference` extra: uv sync --extra reference):

    python tools/reference_brian2.py <assay> [--trials 30] [--procs 6] [--duration-ms 1000]

The assay's stimulus is resolved from the female template's I/O map (config/brain/assays.yaml),
converted to FlyWire root ids, and passed to `model.run_exp` from the pinned
philshiu/Drosophila_brain_model commit in data/raw/shiu2024_model. Brian2 runs with numpy code
generation (no C++ compiler needed). The output is the model's own spike parquet plus a
per-neuron rate table: data/reference/<template>/<assay>.{spikes,rates}.parquet.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flycolony.brain.assays import load_assays, resolve_stimulus  # noqa: E402
from flycolony.config import load_all  # noqa: E402
from flycolony.connectome.template import load_template  # noqa: E402

PREFS = "codegen.target = 'numpy'\n"


def load_shiu_model(raw: Path):
    spec = importlib.util.spec_from_file_location("shiu_model", raw / "model.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("assay")
    ap.add_argument("--trials", type=int, default=None)
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--duration-ms", type=float, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cfg = load_all()["colony.yaml"]
    template_id = cfg.templates.female
    tpl = load_template(ROOT / cfg.paths.templates / template_id)
    assays = load_assays()
    assay = assays.get(args.assay)
    trials = args.trials or assay.trials
    duration = args.duration_ms or assay.duration_ms
    stim = resolve_stimulus(assay, tpl)
    src = tpl.neurons["source_id"].to_numpy()

    raw = ROOT / cfg.paths.data_raw / "shiu2024_model"
    out = ROOT / "data" / "reference" / template_id
    out.mkdir(parents=True, exist_ok=True)
    # Brian2 reads ./brian_preferences; loky workers inherit the working directory.
    (out / "brian_preferences").write_text(PREFS, encoding="utf-8", newline="\n")
    os.chdir(out)

    model = load_shiu_model(raw)
    from brian2 import Hz, ms

    params = dict(model.default_params)
    params["t_run"] = duration * ms
    params["n_run"] = trials
    exc, exc2 = [], []
    for i, group in enumerate(stim):
        ids = [int(src[j]) for j in group.neuron_ids]
        if i == 0:
            exc, params["r_poi"] = ids, group.rate_hz * Hz
        elif i == 1:
            exc2, params["r_poi2"] = ids, group.rate_hz * Hz
        else:
            raise SystemExit("the reference model supports at most two drive groups")
    name = f"{assay.name}.spikes"
    t0 = time.time()
    model.run_exp(
        exp_name=name,
        neu_exc=exc,
        neu_exc2=exc2,
        path_res=out,
        path_comp=raw / "Completeness_783.csv",
        path_con=raw / "Connectivity_783.parquet",
        params=params,
        n_proc=args.procs,
        force_overwrite=args.force,
    )
    spikes = pl.read_parquet(out / f"{name}.parquet")
    rates = (
        spikes.group_by("flywire_id")
        .len()
        .with_columns((pl.col("len") / (trials * duration / 1000.0)).alias("rate_hz"))
        .rename({"flywire_id": "source_id", "len": "spikes"})
        .sort("source_id")
    )
    rates.write_parquet(out / f"{assay.name}.rates.parquet")
    meta = {
        "assay": assay.name,
        "template": template_id,
        "trials": trials,
        "duration_ms": duration,
        "drive": [{"n": len(g.neuron_ids), "rate_hz": g.rate_hz} for g in stim],
        "brian2_codegen": "numpy",
        "shiu_model": "philshiu/Drosophila_brain_model@91bdd1e7dcf193f3e7ca5a8933497fcef63b7960",
        "wall_s": round(time.time() - t0, 1),
    }
    (out / f"{assay.name}.meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
