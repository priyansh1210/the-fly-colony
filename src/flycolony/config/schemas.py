"""Schemas for the top-level config files (CONN-R-070).

Only the fields needed so far are defined. Later specs extend these models; because every model
forbids unknown keys, a key that no spec defines yet is rejected instead of silently ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from flycolony.config.loader import canonical_json, content_hash, load_config


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- colony.yaml ---------------------------------------------------------------------------


class Paths(Strict):
    """All paths are relative to the project root unless absolute (CONN-R-055, PERF-R-010)."""

    data_raw: str = "data/raw"
    templates: str = "data/templates"
    flies: str = "flies"
    watcher: str = "watcher"
    checkpoints: str = "world/checkpoints"


class Clock(Strict):
    """Clock settings (owned by 009). D = neural seconds per fly day."""

    fly_day_neural_s: float = Field(3600.0, gt=0)
    sim_speed: float = Field(1.0, gt=0)


class Templates(Strict):
    female: str = "female-fafb783-t2"
    male: str = "male-malecns1-t2"


class BrainConfig(Strict):
    """Brain engine settings (spec 002).

    mode: `production` needs a passed timestep gate for dt (BRAIN-R-022); `experimental` runs an
    ungated dt and flags it; `reference` is the Shiu et al. configuration (dt = reference dt,
    no background noise, every neuron LIF).
    dt_ms: null picks the largest dt that passed the gate for the loaded template.
    """

    mode: Literal["production", "experimental", "reference"] = "production"
    dt_ms: float | None = Field(None, gt=0)
    graded: bool = True
    weights: Literal["fp32", "fp16"] = "fp32"


class Schedule(Strict):
    """Multi-rate schedule (BRAIN-R-023): each period must be a whole number of brain steps."""

    physics_ms: float = Field(0.5, gt=0)
    senses_ms: float = Field(1.0, gt=0)
    vision_ms: float = Field(10.0, gt=0)
    fields_ms: float = Field(10.0, gt=0)  # world fields, entities, events (003 §2)
    physio_ms: float = Field(100.0, gt=0)  # physiology routes to the brain (006)


class ColonyConfig(Strict):
    seed: int = Field(0, ge=0)
    paths: Paths = Paths()
    clock: Clock = Clock()
    templates: Templates = Templates()
    brain: BrainConfig = BrainConfig()
    schedule: Schedule = Schedule()


# --- genesis.yaml --------------------------------------------------------------------------


class Genesis(Strict):
    """Owned by 007. Preset content arrives with the genome design."""

    count: int = Field(100, ge=1)
    males: int = Field(70, ge=0)
    females: int = Field(30, ge=0)
    presets: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sex_counts_add_up(self) -> Genesis:
        if self.males + self.females != self.count:
            raise ValueError(
                f"males + females ({self.males}+{self.females}) != count ({self.count})"
            )
        if self.presets and sum(self.presets.values()) != self.count:
            raise ValueError("preset counts must add up to count")
        return self


# --- watcher.yaml --------------------------------------------------------------------------


class Llm(Strict):
    """Owned by 013. The model is chosen by the Phase-6 eval harness."""

    runtime: Literal["llama.cpp", "ollama", "none"] = "none"
    endpoint: str = "http://127.0.0.1:8080/v1"
    model: str | None = None
    device: Literal["cpu", "gpu"] = "cpu"


class WatcherConfig(Strict):
    verbosity: Literal["low", "normal", "high"] = "normal"
    llm: Llm = Llm()


# --- hardware.yaml (spec 014 §5) -----------------------------------------------------------


class TierThresholds(Strict):
    """VRAM thresholds in GiB that pick the default tier before a capacity benchmark."""

    low_below_gb: float = Field(6.0, gt=0)
    mid_below_gb: float = Field(12.0, gt=0)
    high_up_to_gb: float = Field(24.0, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> TierThresholds:
        if not (self.low_below_gb < self.mid_below_gb <= self.high_up_to_gb):
            raise ValueError("thresholds must satisfy low_below < mid_below <= high_up_to")
        return self


class HardwareConfig(Strict):
    device: str = Field("auto", pattern=r"^(auto|cpu|cuda(:\d+)?)$")
    tier: Literal["auto", "cpu", "low", "mid", "high", "ultra"] = "auto"
    tiers: TierThresholds = TierThresholds()
    max_flies_override: int | None = Field(None, ge=1)


# --- loading -------------------------------------------------------------------------------


def project_root() -> Path:
    """The repository root (the directory holding pyproject.toml)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


FILES: dict[str, type[Strict]] = {
    "colony.yaml": ColonyConfig,
    "genesis.yaml": Genesis,
    "watcher.yaml": WatcherConfig,
    "hardware.yaml": HardwareConfig,
}


def load_all(config_dir: Path | None = None) -> dict[str, Strict]:
    """Load every top-level config file. A missing file means "all defaults"."""
    config_dir = config_dir or project_root() / "config"
    out: dict[str, Strict] = {}
    for name, model in FILES.items():
        path = config_dir / name
        out[name] = load_config(model, path) if path.exists() else model()
    return out


def config_snapshot(configs: dict[str, Strict]) -> tuple[str, str]:
    """(canonical JSON, SHA-256) of the resolved configs, stored with runs and checkpoints."""
    data = {name: cfg.model_dump(mode="json") for name, cfg in sorted(configs.items())}
    return canonical_json(data), content_hash(data)
