"""Phase-1 validation: engine vs the Brian2 reference, the timestep gate, and the male-template
assays with cross-sex comparability (BRAIN-R-021, -080..082; T-BRAIN-V-001..003).

Every function returns a JSON-able record. The CLI (`colony brain ...`) stores records next to the
template (gate.py) and copies them to specs/002-brain-engine/reports/.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import polars as pl
import torch

from flycolony.brain.assays import (
    Assay,
    AssaySet,
    agreement,
    resolve_readouts,
    resolve_stimulus,
    run_assay,
)
from flycolony.brain.build import output_groups, plastic_sets, topology
from flycolony.brain.engine import BrainBatch
from flycolony.brain.gate import model_hash, variant, write_record
from flycolony.brain.modulation import Modulation, load_receptors, load_routes
from flycolony.brain.params import NeuronParams
from flycolony.brain.select import Resolved
from flycolony.config import project_root
from flycolony.connectome.template import BrainTemplate, pipeline_version
from flycolony.registry import Registry

REPORTS = Path("specs") / "002-brain-engine" / "reports"


def _thresholds(reg: Registry) -> dict:
    return {
        "min_corr": float(reg.get("brain.gate.min_corr")),
        "responsive_hz": float(reg.get("brain.gate.responsive_hz")),
        "top_k": int(reg.get("brain.gate.top_k")),
        "min_top_k_overlap": float(reg.get("brain.gate.min_top_k_overlap")),
    }


def publish(template: BrainTemplate, name: str, record: dict) -> Path:
    """Store a record next to the template and as a committed report."""
    write_record(template.path, name, record)
    out = project_root() / REPORTS / f"{template.template_id}.{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return out


def reference_rates(template: BrainTemplate, assay: str) -> np.ndarray | None:
    """Brian2 trial-mean rates (tools/reference_brian2.py output) indexed by neuron id."""
    path = project_root() / "data" / "reference" / template.template_id / f"{assay}.rates.parquet"
    if not path.exists():
        return None
    ref = pl.read_parquet(path)
    ids = template.neurons.select("neuron_id", "source_id").join(ref, on="source_id", how="inner")
    out = np.zeros(template.n_neurons)
    out[ids["neuron_id"].to_numpy()] = ids["rate_hz"].to_numpy()
    return out


def _expectations(
    assay: Assay, rates: dict[str, np.ndarray], readouts: dict[str, np.ndarray]
) -> list[dict]:
    out = []
    for e in assay.expect:
        ids = readouts[e.readout]
        mine = float(rates[assay.name][ids].mean())
        other = float(rates[e.vs][ids].mean()) if e.vs in rates else 0.0
        ok = mine > other if e.op == ">" else mine < other
        out.append(
            {
                "readout": e.readout,
                "op": e.op,
                "vs": e.vs,
                "value_hz": mine,
                "other_hz": other,
                "pass": ok,
            }
        )
    return out


def _readout_rates(
    assay: Assay, rates: np.ndarray, readouts: dict[str, np.ndarray]
) -> dict[str, float]:
    return {name: float(rates[ids].mean()) for name, ids in readouts.items()}


# --- engine vs Brian2 (BRAIN-R-080, -081) ---------------------------------------------------------


def validate_reference(
    template: BrainTemplate,
    device: torch.device,
    reg: Registry,
    assays: AssaySet,
    *,
    trials: int | None = None,
) -> dict:
    th = _thresholds(reg)
    p = NeuronParams.from_registry(reg, reference=True)
    topo = topology(template, device, reg, w_syn=p.w_syn, graded=False)
    dt = p.dt_reference
    eng: dict[str, np.ndarray] = {}
    ref: dict[str, np.ndarray] = {}
    per = {}
    for a in assays.assays:
        r = reference_rates(template, a.name)
        if r is None:
            per[a.name] = {
                "status": "missing Brian2 reference (run tools/reference_brian2.py)",
                "pass": False,
            }
            continue
        ref[a.name] = r
        eng[a.name] = run_assay(a, template, topo, p, dt, trials=trials)
        readouts = resolve_readouts(a, template)
        stim = resolve_stimulus(a, template)
        driven = np.concatenate([s.neuron_ids for s in stim])
        ag = agreement(
            r, eng[a.name], responsive_hz=th["responsive_hz"], top_k=th["top_k"], exclude=driven
        )
        per[a.name] = {
            "agreement": asdict(ag),
            "stimulus": [
                {
                    "name": s.name,
                    "n": int(s.neuron_ids.size),
                    "rate_hz": s.rate_hz,
                    "missing_v630_ids": list(s.missing_source_ids),
                }
                for s in stim
            ],
            "readout_engine_hz": _readout_rates(a, eng[a.name], readouts),
            "readout_reference_hz": _readout_rates(a, r, readouts),
            "citation": a.citation,
        }
    for a in assays.assays:
        if a.name not in eng:
            continue
        readouts = resolve_readouts(a, template)
        e_eng = _expectations(a, eng, readouts)
        e_ref = _expectations(a, ref, readouts)
        ag = per[a.name]["agreement"]
        ok = (
            ag["pearson"] >= th["min_corr"]
            and ag["top_k_overlap"] >= th["min_top_k_overlap"]
            and all(x["pass"] for x in e_eng)
            and [x["pass"] for x in e_eng] == [x["pass"] for x in e_ref]
        )
        per[a.name].update({"expect_engine": e_eng, "expect_reference": e_ref, "pass": ok})
    return {
        "kind": "reference-validation",
        "template_id": template.template_id,
        "engine": {
            "dt_ms": dt,
            "mode": "reference",
            "device": str(device),
            "trials": trials or "assay default",
        },
        "reference": "Brian2 (numpy codegen) running philshiu/Drosophila_brain_model@91bdd1e, same stimulus sets",
        "thresholds": th,
        "assays": per,
        "passed": all(v.get("pass") for v in per.values()),
        "model_hash": model_hash(reg),
        "pipeline_version": pipeline_version(),
    }


# --- timestep gate (BRAIN-R-021) ----------------------------------------------------------------


def _production_runner(template, device, reg, *, graded: bool, weights: str, dt: float):
    p = NeuronParams.from_registry(reg)
    topo = topology(template, device, reg, w_syn=p.w_syn, graded=graded, weights=weights)
    sets = plastic_sets(template, device)
    groups = output_groups(template)
    receptors, routes = load_receptors(), load_routes()

    def make() -> BrainBatch:
        b = BrainBatch(topo, p, dt, plastic_sets=sets, output_groups=groups)
        Modulation(template, receptors, routes).attach(b)
        return b

    return p, topo, make


def timestep_gate(
    template: BrainTemplate,
    device: torch.device,
    reg: Registry,
    assays: AssaySet,
    *,
    candidates: list[float],
    graded: bool,
    weights: str = "fp32",
    trials: int | None = None,
    mapping: dict[str, MaleMapping] | None = None,
) -> list[dict]:
    """Run the production model at each candidate dt against the same model at the reference dt.

    `mapping` supplies per-assay stimuli and readouts for a template the paper's lists do not
    address (the male, see `male_mapping`)."""
    th = _thresholds(reg)
    ref_dt = float(reg.get("brain.dt.reference"))
    base: dict[str, np.ndarray] = {}
    p, topo, make = _production_runner(
        template, device, reg, graded=graded, weights="fp32", dt=ref_dt
    )

    def stim(a: Assay) -> list[Resolved]:
        return mapping[a.name].stimulus if mapping else resolve_stimulus(a, template)

    def reads(a: Assay) -> dict[str, np.ndarray]:
        return mapping[a.name].readouts if mapping else resolve_readouts(a, template)

    for a in assays.assays:
        base[a.name] = run_assay(
            a, template, topo, p, ref_dt, trials=trials, make_batch=make, stimulus=stim(a)
        )
    records = []
    for dt in candidates:
        p, topo, make = _production_runner(
            template, device, reg, graded=graded, weights=weights, dt=dt
        )
        cand = {
            a.name: run_assay(
                a, template, topo, p, dt, trials=trials, make_batch=make, stimulus=stim(a)
            )
            for a in assays.assays
        }
        per = {}
        for a in assays.assays:
            readouts = reads(a)
            driven = np.concatenate([s.neuron_ids for s in stim(a)])
            ag = agreement(
                base[a.name],
                cand[a.name],
                responsive_hz=th["responsive_hz"],
                top_k=th["top_k"],
                exclude=driven,
            )
            e_base = _expectations(a, base, readouts)
            e_cand = _expectations(a, cand, readouts)
            same = [x["pass"] for x in e_base] == [x["pass"] for x in e_cand]
            per[a.name] = {
                "agreement": asdict(ag),
                "expect_reference_dt": e_base,
                "expect_candidate": e_cand,
                "same_outcome": same,
                "pass": ag.pearson >= th["min_corr"]
                and ag.top_k_overlap >= th["min_top_k_overlap"]
                and same,
            }
        rec = {
            "kind": "timestep-gate",
            "template_id": template.template_id,
            "dt_ms": dt,
            "reference_dt_ms": ref_dt,
            "weights": weights,
            "graded": graded,
            "model": "production (background noise, neuromodulation, plastic sets)",
            "device": str(device),
            "trials": trials or "assay default",
            "thresholds": th,
            "assays": per,
            "mirrored_assays": sorted(k for k, v in (mapping or {}).items() if v.mirrored),
            "emergence": "pending: the Phase-2 emergence assays do not exist yet; the gate is re-run when they do (BRAIN-R-021)",
            "passed": all(v["pass"] for v in per.values()),
            "model_hash": model_hash(reg),
            "pipeline_version": pipeline_version(),
        }
        rec["name"] = "timestep-" + variant(dt, weights, graded)
        records.append(rec)
    return records


# --- male template (BRAIN-R-082, CONN-R-031) --------------------------------------------------------


def _type_map(match_dir: Path, female: BrainTemplate, male: BrainTemplate) -> dict[str, list[str]]:
    """Female type -> male types: the published MaleCNS->FlyWire match, else the same type name."""
    tm = pl.read_parquet(match_dir / "type_match.parquet").filter(pl.col("matched"))
    out: dict[str, list[str]] = {}
    for mt, ft in tm.select("male_type", "female_type").iter_rows():
        out.setdefault(ft, []).append(mt)
    male_types = set(male.neurons["cell_type"].drop_nulls().to_list())
    for ft in set(female.neurons["cell_type"].drop_nulls().to_list()):
        if ft not in out and ft in male_types:
            out[ft] = [ft]
    return out


_MIRROR = {"L": "R", "R": "L"}


def map_to_male(
    sel: Resolved,
    female: BrainTemplate,
    male: BrainTemplate,
    tmap: dict[str, list[str]],
    *,
    mirror: bool = False,
) -> Resolved:
    """Same cell types, same side (or the opposite side when `mirror`) and the same count per type
    (lowest neuron ids first)."""
    f = female.neurons.filter(pl.col("neuron_id").is_in(sel.neuron_ids.tolist()))
    ids: list[int] = []
    unmapped: list[str] = []
    for (ftype, side), part in f.group_by("cell_type", "side", maintain_order=True):
        mtypes = tmap.get(ftype)
        if not mtypes:
            unmapped.append(str(ftype))
            continue
        mside = _MIRROR.get(side, side) if mirror else side
        cand = male.neurons.filter(
            pl.col("cell_type").is_in(mtypes) & (pl.col("side") == mside)
        ).sort("neuron_id")
        ids += cand["neuron_id"].head(part.height).to_list()
    r = Resolved(sel.name, np.array(sorted(ids), dtype=np.int64), sel.rate_hz)
    r.missing_source_ids = tuple(unmapped)  # type: ignore[assignment]
    return r


def input_synapses(template: BrainTemplate) -> np.ndarray:
    """Input synapse count per neuron (edges are CSR by presynaptic neuron)."""
    return np.bincount(
        template.edges["indices"],
        weights=template.edges["syn_count"],
        minlength=template.n_neurons,
    )


def _type_side_rates(template: BrainTemplate, rates: np.ndarray) -> dict[tuple, float]:
    df = (
        template.neurons.select("cell_type", "side")
        .with_columns(pl.Series("r", rates))
        .drop_nulls("cell_type")
    )
    agg = df.group_by("cell_type", "side").agg(pl.col("r").mean()).sort("cell_type", "side")
    return {(t, sd): r for t, sd, r in agg.iter_rows()}


def _completeness(
    f_ids: np.ndarray, m_ids: np.ndarray, f_in: np.ndarray, m_in: np.ndarray, scale: float
) -> np.ndarray:
    """Scaled male input synapses of each mapped readout neuron / the female readout mean."""
    ref = float(f_in[f_ids].mean()) if f_ids.size else 0.0
    return m_in[m_ids] * scale / ref if ref > 0 else np.ones(m_ids.size)


@dataclass
class MaleMapping:
    """One assay's female stimulus and readouts mapped onto the male template."""

    stimulus: list[Resolved]
    readouts: dict[str, np.ndarray]
    mirrored: bool
    readout_input_frac: dict[str, np.ndarray]


def male_mapping(
    female: BrainTemplate, male: BrainTemplate, match_dir: Path, reg: Registry, assays: AssaySet
) -> dict[str, MaleMapping]:
    """Map each assay to the male: same types, side and counts; mirror-image when a mapped readout
    neuron is a truncated reconstruction (brain.male.min_readout_input_frac)."""
    min_frac = float(reg.get("brain.male.min_readout_input_frac"))
    scale = float(reg.get("conn.norm.male_scale"))
    tmap = _type_map(match_dir, female, male)
    f_in, m_in = input_synapses(female), input_synapses(male)
    out = {}
    for a in assays.assays:
        f_read = resolve_readouts(a, female)

        def readouts(mirror: bool, f_read=f_read) -> dict[str, np.ndarray]:
            return {
                k: map_to_male(Resolved(k, v), female, male, tmap, mirror=mirror).neuron_ids
                for k, v in f_read.items()
            }

        def completeness(read: dict[str, np.ndarray], f_read=f_read) -> dict[str, np.ndarray]:
            return {k: _completeness(f_read[k], v, f_in, m_in, scale) for k, v in read.items()}

        # A truncated male readout neuron (far fewer input synapses than its female homolog)
        # cannot report the pathway; the brain is bilateral, so run the mirror-image assay.
        m_read, mirror = readouts(False), False
        frac = completeness(m_read)
        if any((f < min_frac).any() for f in frac.values()):
            alt = readouts(True)
            alt_frac = completeness(alt)
            if all((f >= min_frac).all() for f in alt_frac.values()):
                m_read, mirror, frac = alt, True, alt_frac
        stim = [
            map_to_male(s, female, male, tmap, mirror=mirror) for s in resolve_stimulus(a, female)
        ]
        out[a.name] = MaleMapping(stim, m_read, mirror, frac)
    return out


def male_assays(
    female: BrainTemplate,
    male: BrainTemplate,
    match_dir: Path,
    device: torch.device,
    reg: Registry,
    assays: AssaySet,
    *,
    trials: int | None = None,
) -> dict:
    th = _thresholds(reg)
    min_corr = float(reg.get("brain.male.min_type_side_corr"))
    scale = float(reg.get("conn.norm.male_scale"))
    p = NeuronParams.from_registry(reg, reference=True)
    dt = p.dt_reference
    ftopo = topology(female, device, reg, w_syn=p.w_syn, graded=False)
    mtopo = topology(male, device, reg, w_syn=p.w_syn, graded=False)
    tmap = _type_map(match_dir, female, male)
    maps = male_mapping(female, male, match_dir, reg, assays)
    frates, mrates, per = {}, {}, {}
    m_readouts_all = {}
    for a in assays.assays:
        f_read = resolve_readouts(a, female)
        mm = maps[a.name]
        m_read, mirror, frac, mstim = mm.readouts, mm.mirrored, mm.readout_input_frac, mm.stimulus
        frates[a.name] = run_assay(a, female, ftopo, p, dt, trials=trials)
        mrates[a.name] = run_assay(a, male, mtopo, p, dt, trials=trials, stimulus=mstim)
        m_readouts_all[a.name] = m_read
        ft = _type_side_rates(female, frates[a.name])
        mt = _type_side_rates(male, mrates[a.name])
        pairs = [
            (ft[(f, side)], mt[(m, _MIRROR.get(side, side) if mirror else side)])
            for (f, side) in ft
            for m in tmap.get(f, [])
            if (m, _MIRROR.get(side, side) if mirror else side) in mt
        ]
        arr = np.array(pairs) if pairs else np.zeros((0, 2))
        resp = (arr >= th["responsive_hz"]).any(axis=1) if arr.size else np.zeros(0, dtype=bool)
        corr = (
            float(np.corrcoef(arr[resp, 0], arr[resp, 1])[0, 1]) if resp.sum() > 1 else float("nan")
        )
        per[a.name] = {
            "mirrored": mirror,
            "male_stimulus": [
                {
                    "name": s.name,
                    "n": int(s.neuron_ids.size),
                    "unmapped_types": list(s.missing_source_ids),
                }
                for s in mstim
            ],
            "male_readout_input_frac": {k: v.tolist() for k, v in frac.items()},
            "readout_female_hz": _readout_rates(a, frates[a.name], f_read),
            "readout_male_hz": {
                k: float(mrates[a.name][v].mean()) if v.size else float("nan")
                for k, v in m_read.items()
            },
            "type_side_pearson": corr,
            "responsive_matched_type_sides": int(resp.sum()),
        }
    for a in assays.assays:
        exp_m = _expectations(a, mrates, m_readouts_all[a.name])
        per[a.name]["expect_male"] = exp_m
        per[a.name]["pass"] = all(x["pass"] for x in exp_m) and (
            per[a.name]["type_side_pearson"] >= min_corr
        )
    return {
        "kind": "male-assays",
        "female_template": female.template_id,
        "male_template": male.template_id,
        "male_weight_norm": {
            "mode": reg.get("conn.norm.male_mode"),
            "global_scale": scale,
            "type_clip": float(reg.get("conn.norm.male_type_clip")),
        },
        "engine": {
            "dt_ms": dt,
            "mode": "reference",
            "device": str(device),
            "trials": trials or "assay default",
        },
        "stimulus_mapping": (
            "female Shiu lists -> same cell types (MaleCNS->FlyWire match, else same name), same "
            "side (mirrored when a male readout neuron is truncated), same count per type"
        ),
        "assays": per,
        "passed": all(v["pass"] for v in per.values()),
        "model_hash": model_hash(reg),
        "pipeline_version": pipeline_version(),
    }
