"""Food patches, water springs and fixed test media (WORLD-R-020, -021, -023, -025, -026).

Every patch is a liquid-topped disc on the floor: centre, radius, drop height and volume, a type
from `config/world/food.yaml`, and a stage. Fruit types go through unripe → ripe → fermenting →
rotting → depleted with stage durations in life-clock time; each stage has its own composition
(tastants) and odor emission (amount/s per species). Media types (gate drops, water springs) have one
fixed stage. Ingestion removes exactly the ingested volume; an empty patch is depleted.

Patches are batched as [W, K] tensors (K slots per world; unused slots are inactive).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import torch
import yaml
from pydantic import BaseModel, ConfigDict, Field

from flycolony.config import project_root
from flycolony.engine.clock import SECONDS_PER_HOUR

TASTANTS = ("sucrose", "bitter", "salt", "protein", "ethanol")  # mol/L in the liquid
STAGES = ("unripe", "ripe", "fermenting", "rotting", "depleted")
DEPLETED = STAGES.index("depleted")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StageSpec(_Strict):
    duration_fly_h: float | None = None  # None = stays in this stage
    composition: dict[str, float] = Field(default_factory=dict)  # tastant -> mol/L
    emission: dict[str, float] = Field(default_factory=dict)  # odor species -> amount/s
    humidity_source: float = 0.0  # relative-humidity set-point raised at the patch (0 = none)
    citation: str = ""


class FoodType(_Strict):
    description: str
    stages: dict[str, StageSpec]  # subset of STAGES, in STAGES order
    ripening_ramp_fly_h: float = 0.0  # WORLD-R-025: emission ramps up from 0 after creation


class FoodTable(_Strict):
    version: int
    types: dict[str, FoodType]


def load_food_table(path: Path | None = None) -> FoodTable:
    path = path or project_root() / "config" / "world" / "food.yaml"
    t = FoodTable.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    for name, ft in t.types.items():
        bad = [s for s in ft.stages if s not in STAGES]
        if bad:
            raise ValueError(f"food type {name}: unknown stages {bad}")
        for s in ft.stages.values():
            unknown = [k for k in s.composition if k not in TASTANTS]
            if unknown:
                raise ValueError(f"food type {name}: unknown tastants {unknown}")
    return t


@dataclass
class PatchSpec:
    """One patch placed in a world: type, stage, floor centre (mm), radius, drop height, volume."""

    type: str
    x: float
    y: float
    radius_mm: float
    height_mm: float
    volume_mm3: float
    stage: str = "ripe"


class Patches:
    """K patch slots for each of W worlds."""

    def __init__(
        self, n_worlds: int, slots: int, table: FoodTable, species: list[str], device: torch.device
    ):
        f64 = torch.float64
        self.table, self.species, self.device = table, species, device
        self.type_names = sorted(table.types)
        w, k = n_worlds, slots
        self.active = torch.zeros(w, k, dtype=torch.bool, device=device)
        self.type = torch.zeros(w, k, dtype=torch.long, device=device)
        self.stage = torch.full((w, k), DEPLETED, dtype=torch.long, device=device)
        self.stage_t0 = torch.zeros(w, k, dtype=f64, device=device)  # life-clock s
        self.created = torch.zeros(w, k, dtype=f64, device=device)  # life-clock s
        self.center = torch.zeros(w, k, 2, dtype=f64, device=device)
        self.radius = torch.zeros(w, k, dtype=f64, device=device)
        self.height = torch.zeros(w, k, dtype=f64, device=device)
        self.volume = torch.zeros(w, k, dtype=f64, device=device)
        self.ingested = torch.zeros(w, k, dtype=f64, device=device)  # cumulative mm³
        self.dirty = True  # emission sources need rebuilding

    def place(self, world: int, slot: int, spec: PatchSpec, life_s: float) -> None:
        if spec.type not in self.table.types:
            raise KeyError(f"unknown food type {spec.type!r}")
        ft = self.table.types[spec.type]
        if spec.stage not in ft.stages:
            raise ValueError(f"food type {spec.type} has no stage {spec.stage!r}")
        self.active[world, slot] = True
        self.type[world, slot] = self.type_names.index(spec.type)
        self.stage[world, slot] = STAGES.index(spec.stage)
        self.stage_t0[world, slot] = life_s
        self.created[world, slot] = life_s
        self.center[world, slot] = torch.tensor([spec.x, spec.y], dtype=torch.float64)
        self.radius[world, slot] = spec.radius_mm
        self.height[world, slot] = spec.height_mm
        self.volume[world, slot] = spec.volume_mm3
        self.dirty = True

    def _stage_spec(self, w: int, k: int) -> StageSpec | None:
        ft = self.table.types[self.type_names[int(self.type[w, k])]]
        return ft.stages.get(STAGES[int(self.stage[w, k])])

    def composition(self) -> torch.Tensor:
        """Tastant concentrations per patch [W, K, len(TASTANTS)] (0 for inactive/depleted)."""
        w, k = self.active.shape
        out = torch.zeros(w, k, len(TASTANTS), dtype=torch.float64)
        act = (self.active & (self.stage != DEPLETED)).cpu()
        for wi in range(w):
            for ki in range(k):
                if act[wi, ki]:
                    s = self._stage_spec(wi, ki)
                    for j, name in enumerate(TASTANTS):
                        out[wi, ki, j] = s.composition.get(name, 0.0) if s else 0.0
        return out.to(self.device)

    def advance(self, life_s: float) -> None:
        """Advance stages whose duration has elapsed (life-clock time)."""
        act = self.active.cpu()
        for wi, ki in act.nonzero().tolist():
            while True:
                stage = int(self.stage[wi, ki])
                if stage == DEPLETED:
                    break
                ft = self.table.types[self.type_names[int(self.type[wi, ki])]]
                spec = ft.stages[STAGES[stage]]
                if spec.duration_fly_h is None:
                    break
                end = (
                    float(self.stage_t0[wi, ki]) + spec.duration_fly_h * SECONDS_PER_HOUR
                )  # registry-ok: h→s
                if life_s < end:
                    break
                nxt = next(
                    (
                        i
                        for i in range(stage + 1, len(STAGES))
                        if STAGES[i] in ft.stages or i == DEPLETED
                    ),
                    DEPLETED,
                )
                self.stage[wi, ki] = nxt
                self.stage_t0[wi, ki] = end
                self.dirty = True

    def ramping(self, life_s: float) -> bool:
        """True while any active patch is still inside its ripening ramp (emission changing)."""
        act = self.active.cpu()
        for wi, ki in act.nonzero().tolist():
            ft = self.table.types[self.type_names[int(self.type[wi, ki])]]
            ramp_s = ft.ripening_ramp_fly_h * 3600.0  # registry-ok: h→s
            if ramp_s > 0 and life_s - float(self.created[wi, ki]) < ramp_s:
                return True
        return False

    def ingest(self, world: torch.Tensor, slot: torch.Tensor, volume: torch.Tensor) -> torch.Tensor:
        """Remove ingested volume (mm³) from patches; returns the volume actually taken.

        Handles several flies on one patch in a fixed order (sorted by fly index) so the result
        does not depend on GPU scheduling.
        """
        taken = torch.zeros_like(volume)
        for i in range(volume.shape[0]):  # few feeding flies per step; ordered, deterministic
            w, k = int(world[i]), int(slot[i])
            if k < 0 or not bool(self.active[w, k]) or int(self.stage[w, k]) == DEPLETED:
                continue
            v = torch.minimum(volume[i], self.volume[w, k])
            self.volume[w, k] -= v
            self.ingested[w, k] += v
            taken[i] = v
            if float(self.volume[w, k]) <= 0:
                self.stage[w, k] = DEPLETED
                self.dirty = True
        return taken

    def emission(self, life_s: float) -> torch.Tensor:
        """Emission per patch and species [W, K, S] (amount/s), with the ripening ramp."""
        w, k = self.active.shape
        out = torch.zeros(w, k, len(self.species), dtype=torch.float64)
        act = (self.active & (self.stage != DEPLETED)).cpu()
        for wi in range(w):
            for ki in range(k):
                if not act[wi, ki]:
                    continue
                ft = self.table.types[self.type_names[int(self.type[wi, ki])]]
                s = ft.stages[STAGES[int(self.stage[wi, ki])]]
                ramp = 1.0
                if ft.ripening_ramp_fly_h > 0:
                    age_h = (life_s - float(self.created[wi, ki])) / 3600.0  # registry-ok: s→h
                    ramp = min(1.0, max(0.0, age_h / ft.ripening_ramp_fly_h))
                for name, rate in s.emission.items():
                    if name not in self.species:
                        raise KeyError(f"food emits unknown species {name!r}")
                    out[wi, ki, self.species.index(name)] = rate * ramp
        return out

    def contains(self, world: torch.Tensor, p: torch.Tensor) -> torch.Tensor:
        """Index of the patch whose drop volume contains each point, or −1: [P]."""
        c = self.center[world]  # [P, K, 2]
        d2 = ((p[:, None, :2].double() - c) ** 2).sum(-1)
        inside = (
            (d2 <= self.radius[world] ** 2)
            & (p[:, None, 2].double() <= self.height[world])
            & self.active[world]
            & (self.stage[world] != DEPLETED)
        )
        any_ = inside.any(-1)
        first = inside.double().argmax(-1)  # lowest slot wins: deterministic
        return torch.where(any_, first, torch.full_like(first, -1))

    def state_dict(self) -> dict[str, torch.Tensor]:
        keys = (
            "active",
            "type",
            "stage",
            "stage_t0",
            "created",
            "center",
            "radius",
            "height",
            "volume",
            "ingested",
        )
        return {k: getattr(self, k) for k in keys}

    def load_state_dict(self, s: dict[str, torch.Tensor]) -> None:
        for k, v in s.items():
            setattr(self, k, v.to(self.device))
        self.dirty = True
