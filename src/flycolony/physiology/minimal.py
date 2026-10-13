"""Minimal Phase-2 physiology (006 design): energy, ingestion, sleep pressure, engine sleep state.

- Energy: one lumped reserve E in [0, E_max] (J). Basal metabolism and activity cost per unit motor
  effort are per fly day, integrated in life-clock time (LIFE-R-001, -012). Ingestion transfers the
  drop's sucrose energy at the pump rate × volume per pump while the labellum is in the liquid and
  the proboscis is extended (LIFE-R-011); the volume is a behavior-time process scaled by 86400/D
  (LIFE-OQ-01) and removed from the drop exactly (WORLD-R-021).
- Sleep pressure S (Borbély process S, LIFE-R-030): rises toward 1 while awake, decays while asleep,
  in life-clock time. It reaches the brain only through the `sleep_pressure` route.
- Engine sleep state (BRAIN-R-045): asleep after ≥ bout fly-minutes of body quiescence (WATCH-OQ-01),
  from the fly's own body signals only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

from flycolony.engine.clock import SECONDS_PER_DAY, Clock
from flycolony.registry import Registry

LITRES_PER_MM3 = 1e-6  # registry-ok: unit conversion


@dataclass
class PhysioParams:
    e_max: float
    basal_per_day: float
    effort_per_day: float
    sucrose_j_per_mol: float
    pump_volume_mm3: float
    tau_wake_h: float
    tau_sleep_h: float
    bout_fly_s: float
    move_threshold: float

    @classmethod
    def from_registry(cls, reg: Registry) -> PhysioParams:
        g = lambda k: float(reg.get(k))  # noqa: E731
        return cls(
            e_max=g("life.energy.max_j"),
            basal_per_day=g("life.energy.basal_j_per_day"),
            effort_per_day=g("life.energy.effort_j_per_day"),
            sucrose_j_per_mol=g("life.energy.sucrose_j_per_mol"),
            pump_volume_mm3=g("life.ingest.pump_volume_mm3"),
            tau_wake_h=g("life.sleep.tau_wake_h"),
            tau_sleep_h=g("life.sleep.tau_sleep_h"),
            bout_fly_s=g("life.sleep.bout_fly_min") * 60.0,  # registry-ok: min → s
            move_threshold=g("life.sleep.move_threshold"),
        )


class PhysioBatch:
    STATE = ("energy", "pressure", "quiet_since", "asleep", "ingested_mm3")

    def __init__(self, params: PhysioParams, device: torch.device):
        self.p, self.device = params, device
        self._alloc(0)

    def _alloc(self, n: int) -> None:
        f64 = torch.float64
        self.energy = torch.full((n,), self.p.e_max, dtype=f64, device=self.device)
        self.pressure = torch.zeros(n, dtype=f64, device=self.device)
        self.quiet_since = torch.zeros(n, dtype=f64, device=self.device)  # life-clock s
        self.asleep = torch.zeros(n, dtype=torch.bool, device=self.device)
        self.ingested_mm3 = torch.zeros(n, dtype=f64, device=self.device)

    def add(self, energy_frac: float = 1.0, pressure: float = 0.0, life_s: float = 0.0) -> None:
        """Add a fly with a given state (its history before the trial, integrated by the caller)."""
        one = lambda v, dt=torch.float64: torch.tensor([v], dtype=dt, device=self.device)  # noqa: E731
        self.energy = torch.cat([self.energy, one(energy_frac * self.p.e_max)])
        self.pressure = torch.cat([self.pressure, one(pressure)])
        self.quiet_since = torch.cat([self.quiet_since, one(life_s)])
        self.asleep = torch.cat([self.asleep, one(False, torch.bool)])
        self.ingested_mm3 = torch.cat([self.ingested_mm3, one(0.0)])

    @property
    def n(self) -> int:
        return int(self.energy.numel())

    @property
    def deficit(self) -> torch.Tensor:
        return 1 - self.energy / self.p.e_max

    # --- history before a trial ---------------------------------------------------------------------

    def starved_fraction(self, hours: float) -> float:
        """Reserve fraction after `hours` fly hours of basal metabolism without food."""
        e = self.p.e_max - self.p.basal_per_day * hours / 24.0  # registry-ok: hours per day
        return max(0.0, e / self.p.e_max)

    def pressure_after_wake(self, hours: float, start: float = 0.0) -> float:
        """Process S after `hours` fly hours awake (closed form)."""
        return 1 - (1 - start) * math.exp(-hours / self.p.tau_wake_h)

    # --- one physiology step ----------------------------------------------------------------------------

    def intake(
        self, clock: Clock, dt_neural_s: float, pump: torch.Tensor, can_ingest: torch.Tensor
    ) -> torch.Tensor:
        """Volume the fly would ingest this step (mm³): a behavior-time process, compressed by
        86400/D (LIFE-OQ-01). The caller removes it from the drop and credits what was taken."""
        return pump * self.p.pump_volume_mm3 * dt_neural_s * clock.compression * can_ingest

    def step(
        self,
        clock: Clock,
        dt_neural_s: float,
        effort: torch.Tensor,
        quiescent: torch.Tensor,
        taken_mm3: torch.Tensor,
        sucrose_in_drop: torch.Tensor,
    ) -> None:
        """Advance energy, sleep state and pressure by dt of neural time."""
        life_dt = dt_neural_s * clock.compression
        day = life_dt / SECONDS_PER_DAY
        gain = taken_mm3 * LITRES_PER_MM3 * sucrose_in_drop * self.p.sucrose_j_per_mol
        cost = (self.p.basal_per_day + self.p.effort_per_day * effort) * day
        self.energy = (self.energy + gain - cost).clamp(0, self.p.e_max)
        self.ingested_mm3 = self.ingested_mm3 + taken_mm3
        # Sleep state from body quiescence, then process S.
        now = clock.life_s
        self.quiet_since = torch.where(
            quiescent, self.quiet_since, torch.full_like(self.quiet_since, now)
        )
        self.asleep = quiescent & (now - self.quiet_since >= self.p.bout_fly_s)
        h = life_dt / 3600.0  # registry-ok: s → h
        wake = 1 - (1 - self.pressure) * math.exp(-h / self.p.tau_wake_h)
        sleep = self.pressure * math.exp(-h / self.p.tau_sleep_h)
        self.pressure = torch.where(self.asleep, sleep, wake)

    def state_dict(self) -> dict:
        return {k: getattr(self, k).cpu() for k in self.STATE}

    def load_state_dict(self, s: dict) -> None:
        for k in self.STATE:
            setattr(self, k, s[k].to(self.device))
