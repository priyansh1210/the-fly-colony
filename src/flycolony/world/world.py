"""WorldGroup: W closed worlds of identical geometry, stepped as one batch (WORLD-R-001..003).

The Colony Dome is a group with W = 1; emergence-gate arenas are groups with W = trials. Every
fly carries a world index, and every lookup is gathered by it, so nothing crosses between worlds.
Environment changes arrive only as commands applied at step boundaries (WORLD-R-070); the
naturalization rules for structural changes belong to the Control API (Phase 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import torch

from flycolony.engine.clock import MS_PER_S, Clock
from flycolony.registry import Registry
from flycolony.world.entities import Patches, PatchSpec, load_food_table
from flycolony.world.fields import Fields, Grid, SpeciesSpec, Vent, Wind, solve_wind, zero_wind
from flycolony.world.geometry import Arena
from flycolony.world.sky import Looming, LoomParams, Sky, SkyParams

TEMPERATURE, HUMIDITY = "temperature", "humidity"


@dataclass
class WorldSpec:
    """Everything that defines a world group's structure (hashed into checkpoints)."""

    arena: Arena
    n_worlds: int = 1
    cell_mm: float | None = None  # None: registry dome/chamber default by arena kind
    vents: list[Vent] = field(default_factory=list)
    patch_slots: int = 4  # registry-ok: default patch slots per world (structural capacity)


class WorldGroup:
    def __init__(self, spec: WorldSpec, reg: Registry, device: torch.device):
        self.spec, self.reg, self.device = spec, reg, device
        g = reg.get
        cell = spec.cell_mm or float(
            g(
                "world.grid.cell_mm_dome"
                if spec.arena.kind == "cylinder"
                else "world.grid.cell_mm_chamber"
            )
        )
        self.grid = Grid(spec.arena, cell, device)
        self.odors: list[str] = list(g("world.odor.species"))
        species = [
            SpeciesSpec(
                o, float(g("world.odor.diffusion_mm2_s")), float(g("world.odor.decay_per_s"))
            )
            for o in self.odors
        ]
        species += [
            SpeciesSpec(
                TEMPERATURE,
                float(g("world.air.thermal_diffusivity_mm2_s")),
                ambient=float(g("world.air.temperature_c")),
            ),
            SpeciesSpec(
                HUMIDITY,
                float(g("world.air.vapour_diffusivity_mm2_s")),
                ambient=float(g("world.air.humidity")),
            ),
        ]
        self.max_cfl = float(g("world.field.max_cfl"))
        self.max_diff = float(g("world.field.max_diffusion_number"))
        self.wind = self._solve(spec.vents)
        self.fields = Fields(self.grid, species, spec.n_worlds, self.wind)
        self.sky = Sky(SkyParams.from_registry(reg))
        self.looming = Looming(spec.n_worlds, LoomParams.from_registry(reg), device)
        self.patches = Patches(
            spec.n_worlds, spec.patch_slots, load_food_table(), self.odors, device
        )
        self._composition: torch.Tensor | None = None
        self.source_tau_s = float(g("world.air.source_tau_s"))
        self.ramp_refresh_s = float(g("world.food.ramp_refresh_fly_s"))
        self._last_rebuild = float("-inf")

    @property
    def n_worlds(self) -> int:
        return self.spec.n_worlds

    def _solve(self, vents: list[Vent]) -> Wind:
        if not vents:
            return zero_wind(self.grid)
        g = self.reg.get
        return solve_wind(
            self.grid,
            vents,
            tol=float(g("world.wind.tolerance")),
            max_iter=int(g("world.wind.max_iterations")),
        )

    # --- commands (applied at step boundaries) ---------------------------------------------------

    def set_vents(self, vents: list[Vent]) -> None:
        self.spec.vents = list(vents)
        self.wind = self._solve(vents)
        self.fields.wind = self.wind

    def place_patch(self, world: int, slot: int, spec: PatchSpec, clock: Clock) -> None:
        self.patches.place(world, slot, spec, clock.life_s)
        self._composition = None

    def start_looming(self, world: int, clock: Clock, target, direction) -> None:
        self.looming.start(world, clock.sim_ts, target, direction)

    # --- stepping -----------------------------------------------------------------------------------

    def step(self, clock: Clock, dt_ms: float) -> None:
        """Advance fields, entities and events by dt_ms of neural time (period of 'fields')."""
        self.patches.advance(clock.life_s)
        ramp_due = (
            clock.life_s - self._last_rebuild >= self.ramp_refresh_s
            and self.patches.ramping(clock.life_s)
        )
        if self.patches.dirty or ramp_due:
            self._rebuild_sources(clock)
        self.fields.step(dt_ms / MS_PER_S, max_cfl=self.max_cfl, max_diff=self.max_diff)
        self.looming.update(clock.sim_ts)

    def _rebuild_sources(self, clock: Clock) -> None:
        """Dense emission and humidity-relaxation sources from the patches (CPU, fixed order)."""
        g, f = self.grid, self.fields
        w_n, s_n = self.n_worlds, len(f.species)
        life = clock.life_s
        emit = self.patches.emission(life)  # [W, K, n_odor]
        src = torch.zeros(w_n, s_n, *g.shape, dtype=torch.float64)
        tgt = torch.zeros_like(src)
        rate = torch.zeros_like(src)
        centers = self.patches.center.cpu()
        hum = f.index(HUMIDITY)
        for wi in range(w_n):
            for ki in range(self.patches.active.shape[1]):
                if not bool(self.patches.active[wi, ki]):
                    continue
                xyz = torch.tensor([*centers[wi, ki].tolist(), g.cell / 2], dtype=torch.float64)
                i = g.cell_of(xyz.to(self.device)).cpu().tolist()
                src[wi, : len(self.odors), i[0], i[1], i[2]] += emit[wi, ki]
                stage = self.patches._stage_spec(wi, ki)
                if stage is not None and stage.humidity_source > 0:
                    tgt[wi, hum, i[0], i[1], i[2]] = stage.humidity_source
                    rate[wi, hum, i[0], i[1], i[2]] = 1.0 / self.source_tau_s
        f.source = src.to(self.device)
        f.relax_target = tgt.to(self.device)
        f.relax_rate = rate.to(self.device)
        self.patches.dirty = False
        self._composition = None
        self._last_rebuild = life

    # --- queries for bodies and senses ----------------------------------------------------------------

    def composition(self) -> torch.Tensor:
        """Tastant composition per patch [W, K, T] (cached until patches change)."""
        if self._composition is None:
            self._composition = self.patches.composition()
        return self._composition

    def odor_at(self, world: torch.Tensor, p: torch.Tensor) -> torch.Tensor:
        return self.fields.sample(world, p)[:, : len(self.odors)]

    def air_at(self, world: torch.Tensor, p: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """(temperature °C, relative humidity) at points."""
        s = self.fields.sample(world, p)
        return s[:, self.fields.index(TEMPERATURE)], s[:, self.fields.index(HUMIDITY)]

    def wind_at(self, world: torch.Tensor, p: torch.Tensor) -> torch.Tensor:
        del world  # one wind field per group (vents are shared)
        return self.wind.at(self.grid, p)

    # --- checkpoint (WORLD-R-003) ---------------------------------------------------------------------

    def state_dict(self) -> dict:
        return {
            "geometry_hash": self.spec.arena.spec_hash(),
            "n_worlds": self.n_worlds,
            "vents": [vars(v) for v in self.spec.vents],
            "fields": {k: v.cpu() for k, v in self.fields.state_dict().items()},
            "patches": {k: v.cpu() for k, v in self.patches.state_dict().items()},
            "looming": {k: v.cpu() for k, v in self.looming.state_dict().items()},
            "sky": self.sky.state_dict(),
        }

    def load_state_dict(self, s: dict) -> None:
        if s["geometry_hash"] != self.spec.arena.spec_hash() or s["n_worlds"] != self.n_worlds:
            raise ValueError("checkpoint is for a different world geometry")
        self.set_vents([Vent(**v) for v in s["vents"]])
        self.fields.load_state_dict(s["fields"])
        self.patches.load_state_dict(s["patches"])
        self.looming.load_state_dict(s["looming"])
        self.sky.load_state_dict(s["sky"])
        self._composition = None
        # Restored sources are exact; patches.dirty only marks the composition cache.
        self.patches.dirty = False
