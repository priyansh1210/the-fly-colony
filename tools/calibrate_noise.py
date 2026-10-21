"""Global calibration of the background noise against spontaneous-rate data (002, BRAIN-R-013).

    python tools/calibrate_noise.py [--flies 8] [--warmup 0.5] [--seconds 2.0]

Rule (see config/params/brain.yaml brain.noise.w): the background input rate stays at
brain.noise.rate and the membrane kick per event is scanned. The calibrated kick is the largest one
for which, in the production brain at rest (no sensory input),
- the mean spontaneous rate of spiking central-brain neurons lies in [1, 4] Hz: the registry's
  pre-existing target of "about 1-5 Hz mean in the central brain" (brain.noise.rate), capped by the
  metabolic upper bound on the whole-brain mean (State of Brain Emulation Report 2025,
  arXiv:2510.15745), and
- no brain.runaway event occurs.
No behavioural or gate measure enters the choice.

Amendment (2026-10-21, decided by the project owner after the first scan, documented in the
report): the first rule also required a Kenyon-cell mean <= 0.5 Hz (in vivo 0.1 +/- 0.4 spikes/s;
Turner G.C., Bazhenov M., Laurent G. (2008) J Neurophysiol 99:734). With uniform LIF parameters KCs
fire ~2.5x the central mean at every kick, so only a fully silent brain met it (0.5 mV: 0 Hz
everywhere), which violates the 1-5 Hz target. The KC rate is now measured and reported as a known
model limitation (no cell-type thresholds, no APL feedback), not used for the choice.

Writes specs/002-brain-engine/reports/<template>.noise-calibration.json.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace

import numpy as np
import torch

from flycolony.brain.build import setup_brain, template_path
from flycolony.brain.engine import BrainBatch, FlyBrainSpec
from flycolony.brain.modulation import Modulation, load_receptors, load_routes
from flycolony.config import load_all
from flycolony.config.schemas import project_root
from flycolony.connectome.template import load_template
from flycolony.engine.clock import MS_PER_S
from flycolony.registry import Registry

CENTRAL_MIN_HZ = 1.0
CENTRAL_MAX_HZ = 4.0
KC_IN_VIVO_HZ = 0.1
KICKS_MV = (1.5, 1.0, 0.8, 0.7, 0.68, 0.66, 0.64, 0.62, 0.6, 0.5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flies", type=int, default=8)
    ap.add_argument("--warmup", type=float, default=0.5)
    ap.add_argument("--seconds", type=float, default=2.0)
    a = ap.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")  # device-ok: tool
    cfg = load_all()["colony.yaml"]
    reg = Registry.load(project_root() / "config" / "params")
    path = template_path(cfg, "female")
    template = load_template(path)
    setup = setup_brain(template, device, cfg, reg)
    nr = template.neurons
    spiking = setup.topo.spiking.cpu().numpy()
    central = (nr["super_class"] == "central").fill_null(False).to_numpy().astype(bool) & spiking
    kc = nr["cell_type"].str.starts_with("KC").fill_null(False).to_numpy() & spiking
    rows = []
    for w in KICKS_MV:
        params = replace(setup.params, noise_w=w)
        b = BrainBatch(
            setup.topo, params, setup.dt,
            plastic_sets=setup.plastic_sets, output_groups=setup.output_groups,
        )  # fmt: skip
        Modulation(template, load_receptors(), load_routes()).attach(b)
        for i in range(a.flies):
            b.add(FlyBrainSpec(f"n{i}", 7000 + i))
        events = list(b.run(round(a.warmup * MS_PER_S / setup.dt)))
        counts = torch.zeros(b.batch_size * b.n, dtype=torch.int64, device=device)
        b.taps.append(lambda _b, _t, s, c=counts: c.index_add_(0, s, torch.ones_like(s)))
        steps = round(a.seconds * MS_PER_S / setup.dt)
        events += b.run(steps)
        rate = (counts.view(b.batch_size, b.n).double().mean(0) / a.seconds).cpu().numpy()
        row = {
            "noise_w_mv": w,
            "central_mean_hz": float(rate[central].mean()),
            "central_median_hz": float(np.median(rate[central])),
            "central_silent_frac": float((rate[central] == 0).mean()),
            "kc_mean_hz": float(rate[kc].mean()),
            "all_spiking_mean_hz": float(rate[spiking].mean()),
            "runaway_events": sum(e.kind == "brain.runaway" for e in events),
        }
        row["meets_rule"] = (
            CENTRAL_MIN_HZ <= row["central_mean_hz"] <= CENTRAL_MAX_HZ
            and row["runaway_events"] == 0
        )
        rows.append(row)
        print(
            f"w={w:4.2f} mV  central mean {row['central_mean_hz']:6.2f} Hz  median"
            f" {row['central_median_hz']:5.2f}  silent {row['central_silent_frac']:.2f}"
            f"  KC {row['kc_mean_hz']:5.2f} Hz  runaway {row['runaway_events']}"
            f"  {'ok' if row['meets_rule'] else '-'}",
            flush=True,
        )
        del b
    ok = [r for r in rows if r["meets_rule"]]
    chosen = max(ok, key=lambda r: r["noise_w_mv"]) if ok else None
    report = {
        "spec": "002 BRAIN-R-013 background-noise calibration (Phase 2)",
        "template": path.name,
        "rule": (
            f"largest brain.noise.w with central spiking mean in [{CENTRAL_MIN_HZ}, "
            f"{CENTRAL_MAX_HZ}] Hz and no runaway; rate fixed at "
            f"brain.noise.rate = {setup.params.noise_rate} Hz"
        ),
        "amendment": (
            "2026-10-21, decided by the project owner after the first scan: the Kenyon-cell "
            "criterion (mean <= 0.5 Hz) was dropped because only a fully silent brain met it "
            "(0.5 mV gave 0 Hz everywhere, against the registry's 1-5 Hz central target). The KC "
            f"rate is reported as a known limitation (in vivo ~{KC_IN_VIVO_HZ} Hz; the model "
            "has uniform LIF parameters and no APL feedback)."
        ),
        "first_scan_2026_10_21": {
            "rule": "central mean <= 4 Hz and KC mean <= 0.5 Hz and no runaway",
            "chosen_noise_w_mv": 0.5,
            "central_mean_hz_by_w": {
                "1.5": 23.78,
                "1.25": 22.12,
                "1.0": 20.73,
                "0.9": 18.18,
                "0.8": 10.78,
                "0.7": 4.98,
                "0.6": 1.90,
                "0.5": 0.0,
                "0.4": 0.0,
                "0.3": 0.0,
            },
            "kc_mean_hz_by_w": {
                "1.5": 59.15,
                "1.25": 56.35,
                "1.0": 53.67,
                "0.9": 47.26,
                "0.8": 27.92,
                "0.7": 12.81,
                "0.6": 4.88,
                "0.5": 0.0,
                "0.4": 0.0,
                "0.3": 0.0,
            },
        },
        "sources": [
            "State of Brain Emulation Report 2025, arXiv:2510.15745 (whole-brain mean <= ~4 Hz)",
            "Turner, Bazhenov & Laurent (2008) J Neurophysiol 99:734 (KC 0.1 +/- 0.4 Hz; reported only)",
        ],
        "condition": {
            "flies": a.flies,
            "warmup_s": a.warmup,
            "measured_s": a.seconds,
            "dt_ms": setup.dt,
            "neurons": {"central_spiking": int(central.sum()), "kc_spiking": int(kc.sum())},
        },
        "scan": rows,
        "chosen_noise_w_mv": chosen["noise_w_mv"] if chosen else None,
        "previous_noise_w_mv": setup.params.noise_w,
    }
    dest = (
        project_root()
        / "specs"
        / "002-brain-engine"
        / "reports"
        / f"{path.name}.noise-calibration.json"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"chosen noise_w = {report['chosen_noise_w_mv']} mV; wrote {dest}")


if __name__ == "__main__":
    main()
