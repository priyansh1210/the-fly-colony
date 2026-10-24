"""Rest-only calibration of the per-connection synapse cap (002, brain.syn.max_synapses).

    python tools/calibrate_cap.py [--flies 8]

Problem (2026-10-22): the model's synapses neither depress nor adapt, so a reciprocally connected
excitatory pair with hundreds of synapses each way latches: one noise spike starts it and it fires
at ~130 Hz for ever (e.g. CB0216 L<->R, 451/455 synapses, which holds the proboscis motor neuron
MN9 at ~100 Hz at rest). Global short-term depression with the measured ORN->PN parameters
(brain.syn.depression.*) breaks the latch but makes every sustained response transient and fails
the sugar->MN9 validation, so the project owner chose (2026-10-23) a cap on each connection's
synapse count, calibrated at rest only.

Rule: run the production brain at rest (background noise only) for --warmup s, switch the
background input off, wait --settle s and count spikes over --measure s. A neuron is self-sustained
if it still fires >= LATCH_HZ in any fly while the output of the antennal-lobe network is also
silenced (its neurons' presynaptic gain set to 0 for the quiet phase). The cap is the largest scanned value for which no neuron
outside the antennal-lobe network (AL_CLASSES) is self-sustained. The antennal-lobe network
sustains itself at every cap (a separate known limitation: excitatory LN chemical loops) and is
reported, not used. No sensory stimulus, behavioural or gate measure enters the choice.

Amendment (2026-10-23, before any cap was applied): the first scan switched off only the
background input. The self-sustained antennal lobe then kept driving ~140-170 downstream neurons
(lateral horn, descending) at every cap, so the test could not separate latches from AL-driven
activity and no cap met the rule. The AL output is now silenced during the quiet phase too; the
criterion is unchanged. The first scan is kept in the report.

Writes specs/002-brain-engine/reports/<template>.synapse-cap-calibration.json.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
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

LATCH_HZ = 10.0
CAPS = (None, 450.0, 400.0, 350.0, 300.0, 250.0, 200.0, 150.0, 100.0)
AL_CLASSES = ("ALLN", "ALPN", "ALIN", "ALON", "olfactory", "hygrosensory", "thermosensory")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flies", type=int, default=8)
    ap.add_argument("--warmup", type=float, default=3.0)
    ap.add_argument("--settle", type=float, default=0.5)
    ap.add_argument("--measure", type=float, default=0.5)
    a = ap.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")  # device-ok: tool
    cfg = load_all()["colony.yaml"]
    reg = Registry.load(project_root() / "config" / "params")
    path = template_path(cfg, "female")
    template = load_template(path)
    setup = setup_brain(template, device, cfg, reg)
    nr = template.neurons
    n = nr.height
    ctype = nr["cell_type"].fill_null("?").to_numpy()
    cclass = nr["cell_class"].fill_null("?").to_numpy()
    sclass = nr["super_class"].fill_null("?").to_numpy()
    in_al = np.isin(cclass, AL_CLASSES)
    counts0 = torch.from_numpy(np.asarray(template.edges["weight"], dtype=np.float32)).to(device)
    w_now = setup.topo.weight.clone()
    # Uncapped weights from the template counts (female FAFB: no cross-dataset scale); edges the
    # electrical-pair rule zeroed stay zero.
    w_per_count = setup.params.w_syn
    base = torch.where(w_now == 0, w_now, counts0 * w_per_count)
    rows = []
    for cap in CAPS:
        w = base if cap is None else base.clamp(-cap * w_per_count, cap * w_per_count)
        setup.topo.weight.copy_(w)
        b = BrainBatch(
            setup.topo, setup.params, setup.dt,
            plastic_sets=setup.plastic_sets, output_groups=setup.output_groups,
        )  # fmt: skip
        Modulation(template, load_receptors(), load_routes()).attach(b)
        for i in range(a.flies):
            b.add(FlyBrainSpec(f"c{i}", 7000 + i))
        events = list(b.run(round(a.warmup * MS_PER_S / setup.dt)))
        rest = torch.zeros(b.batch_size * n, dtype=torch.int64, device=device)
        tap = lambda _b, _t, s, c=rest: c.index_add_(0, s, torch.ones_like(s))  # noqa: E731
        b.taps.append(tap)
        events += b.run(round(1.0 * MS_PER_S / setup.dt))
        b.taps.clear()
        b.k = replace(b.k, p_noise=0.0)  # background input off
        b.pre[:, torch.from_numpy(np.flatnonzero(in_al)).to(device)] = 0.0  # and AL output
        b.run(round(a.settle * MS_PER_S / setup.dt))
        quiet = torch.zeros(b.batch_size * n, dtype=torch.int64, device=device)
        b.taps.append(lambda _b, _t, s, c=quiet: c.index_add_(0, s, torch.ones_like(s)))
        b.run(round(a.measure * MS_PER_S / setup.dt))
        r_rest = rest.view(b.batch_size, n).double().cpu().numpy() / 1.0
        r_quiet = quiet.view(b.batch_size, n).double().cpu().numpy() / a.measure
        sustained = (r_quiet >= LATCH_HZ).any(0)
        outside = np.flatnonzero(sustained & ~in_al)
        row = {
            "max_synapses": cap,
            "edges_capped": 0 if cap is None else int((counts0.abs() > cap).sum()),
            "self_sustained_outside_al": int(outside.size),
            "self_sustained_in_al": int((sustained & in_al).sum()),
            "outside_al_types": dict(Counter(ctype[outside].tolist()).most_common(20)),
            "outside_al_super_class": dict(Counter(sclass[outside].tolist())),
            "rest_central_mean_hz": float(
                r_rest[:, (sclass == "central") & setup.topo.spiking.cpu().numpy()].mean()
            ),
            "rest_mn9_hz": float(r_rest[:, ctype == "CB0701"].mean()),
            "runaway_events": sum(e.kind == "brain.runaway" for e in events),
        }
        row["meets_rule"] = row["self_sustained_outside_al"] == 0 and row["runaway_events"] == 0
        rows.append(row)
        print(json.dumps(row), flush=True)
        del b
    setup.topo.weight.copy_(w_now)
    ok = [r for r in rows if r["meets_rule"] and r["max_synapses"] is not None]
    chosen = max(ok, key=lambda r: r["max_synapses"]) if ok else None
    report = {
        "spec": "002 per-connection synapse cap calibration (Phase 2)",
        "template": path.name,
        "rule": (
            f"largest brain.syn.max_synapses in {[c for c in CAPS if c]} with no neuron outside "
            f"the antennal-lobe network ({', '.join(AL_CLASSES)}) still firing >= {LATCH_HZ} Hz "
            f"in any fly {a.settle}-{a.settle + a.measure} s after the background input is switched "
            f"off (after {a.warmup} s at rest), and no runaway"
        ),
        "decision": (
            "2026-10-23, project owner: cap per-connection synapse counts, calibrated at rest only, "
            "instead of global short-term depression (which failed the sugar->MN9 validation). "
            "The cap value has no direct citation; Liu, Davoudian, Lizbinski & Jeanne (2022) Curr Biol "
            "doi 10.1016/j.cub.2021.11.056 show connection strength follows synapse density, not "
            "raw count, so raw counts overstate the largest connections."
        ),
        "known_limitation": (
            "the antennal-lobe network is self-sustained at every cap (excitatory LN chemical "
            "loops); reported as self_sustained_in_al"
        ),
        "condition": {
            "flies": a.flies,
            "warmup_s": a.warmup,
            "settle_s": a.settle,
            "measure_s": a.measure,
            "dt_ms": setup.dt,
            "noise_w_mv": setup.params.noise_w,
            "depression_keep": setup.params.depression_keep,
        },
        "first_scan_2026_10_23": {
            "note": "background off only; AL output not silenced (confounded, see amendment)",
            "self_sustained_outside_al_by_cap": {
                "none": 154,
                "450": 167,
                "400": 157,
                "350": 173,
                "300": 164,
                "250": 135,
                "200": 160,
                "150": 152,
                "100": 139,
            },
            "rest_mn9_hz_by_cap": {
                "none": 115.8,
                "450": 115.7,
                "400": 112.2,
                "350": 88.6,
                "300": 49.6,
                "250": 18.7,
                "200": 11.25,
                "150": 3.25,
                "100": 3.5,
            },
        },
        "scan": rows,
        "chosen_max_synapses": chosen["max_synapses"] if chosen else None,
    }
    dest = (
        project_root()
        / "specs"
        / "002-brain-engine"
        / "reports"
        / f"{path.name}.synapse-cap-calibration.json"
    )
    dest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"chosen max_synapses = {report['chosen_max_synapses']}; wrote {dest}")


if __name__ == "__main__":
    main()
