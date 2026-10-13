"""Timestep gate and reference validation records (BRAIN-R-021, -022, -081).

Gate results live next to the immutable template, in ``<templates>/<template_id>.gates/``, and a
copy of each is committed under ``specs/002-brain-engine/reports/``. A record is valid only for
the brain-model parameters it was computed with (hash of the registry's ``brain.*`` entries), so
changing a parameter invalidates the gate instead of silently reusing it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from flycolony.config import content_hash, project_root
from flycolony.config.schemas import BrainConfig
from flycolony.registry import Registry

GATE_SUFFIX = ".gates"


class GateError(RuntimeError):
    """Production mode with a timestep that has not passed the gate (BRAIN-R-022)."""


def gate_dir(template_path: Path) -> Path:
    template_path = Path(template_path)
    return template_path.parent / f"{template_path.name}{GATE_SUFFIX}"


MODEL_TABLES = ("receptors.yaml", "plastic_sets.yaml", "flyvis_time_constants.yaml")


def model_hash(reg: Registry) -> str:
    """Hash of everything that defines brain dynamics: the registry's brain.* and conn.norm.*
    values (validation thresholds brain.gate.* / brain.male.* excluded) and the brain model tables
    in config/brain/."""
    entries = [
        {"id": e.id, "value": e.value}
        for e in reg.entries()
        if (e.id.startswith("brain.") and not e.id.startswith(("brain.gate.", "brain.male.")))
        or e.id.startswith("conn.norm.")
    ]
    tables = {
        name: yaml.safe_load(
            (project_root() / "config" / "brain" / name).read_text(encoding="utf-8")
        )
        for name in MODEL_TABLES
    }
    return content_hash({"registry": entries, "tables": tables})


def variant(dt: float, weights: str, graded: bool) -> str:
    return f"dt{dt:g}-{weights}-{'graded' if graded else 'lif'}"


def write_record(template_path: Path, name: str, record: dict) -> Path:
    d = gate_dir(template_path)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.json"
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return path


def read_record(template_path: Path, name: str) -> dict | None:
    path = gate_dir(template_path) / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def passed_dts(template_path: Path, weights: str, graded: bool, mhash: str) -> list[float]:
    """Timesteps whose gate record passed for this model variant and parameter hash."""
    out = []
    d = gate_dir(template_path)
    if not d.exists():
        return out
    for path in sorted(d.glob("timestep-*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if (
            rec.get("passed")
            and rec.get("weights") == weights
            and rec.get("graded") == graded
            and rec.get("model_hash") == mhash
        ):
            out.append(float(rec["dt_ms"]))
    return sorted(out)


@dataclass(frozen=True)
class DtChoice:
    dt: float
    mode: str
    gated: bool
    note: str


def resolve_dt(cfg: BrainConfig, template_path: Path, reg: Registry) -> DtChoice:
    """Pick the brain timestep for a template, refusing an ungated one in production (R-022)."""
    ref_dt = float(reg.get("brain.dt.reference"))
    if cfg.mode == "reference":
        return DtChoice(ref_dt, "reference", True, "reference mode (Shiu et al. configuration)")
    graded = cfg.graded
    gated = passed_dts(template_path, cfg.weights, graded, model_hash(reg))
    dt = cfg.dt_ms if cfg.dt_ms is not None else (max(gated) if gated else ref_dt)
    if dt == ref_dt and cfg.weights == "fp32":
        return DtChoice(dt, cfg.mode, True, "reference timestep")
    if dt in gated:
        return DtChoice(dt, cfg.mode, True, f"gate passed ({variant(dt, cfg.weights, graded)})")
    if cfg.mode == "production":
        raise GateError(
            f"dt={dt} ms ({cfg.weights}, {'graded' if graded else 'lif'}) has not passed the "
            f"timestep gate for {Path(template_path).name} with the current brain parameters. "
            "Run `colony brain gate`, or set brain.mode: experimental to run it flagged."
        )
    return DtChoice(dt, "experimental", False, "EXPERIMENTAL: ungated timestep")
