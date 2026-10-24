# 006 — Physiology & Life Cycle: Design (Phase 2 subset)

| Field | Value |
|---|---|
| Status | Phase 2 subset, 2026-10-13. The full design is written for Phase 4. |
| Spec | [spec.md](spec.md) |

Phase 2 needs three things from physiology: hunger for the feeding gates, ingestion accounting, and the minimal sleep homeostat (LIFE-R-030, brought forward by MOTOR-OQ-04).

## 1. Module

```
src/flycolony/physiology/
  minimal.py   PhysioBatch: energy reserve, ingestion, sleep pressure, engine sleep state
```

All rates are per fly day and are integrated in life-clock time from the clock service (LIFE-R-001, CLOCK-R-010). Ingestion volume per second of feeding runs in neural time (a behavior-time process).

## 2. Energy (LIFE-R-010, -011, -012; Phase-2 subset)

- **Reserve.** One lumped energy reserve E in [0, E_max] (registry, energy units), plus basal metabolism per fly day (registry; `ASSUMPTION` until the Phase-4 survival calibration).
- **Activity costs.** Effort from 005 adds activity costs per unit effort.
- **Ingestion.** Volume = pump rate × volume per pump (registry) × time with the labellum in liquid. The energy gained is volume × sucrose concentration × energy per mol. The volume is removed from the drop exactly (WORLD-R-021).
  - Under the compressed clock, ingestion volume is scaled by `86400 / D` (LIFE-OQ-01 decision).
- **Deficit.** Energy deficit = 1 − E / E_max is the source variable of the hunger routes (004 §3).
- **Deferred to Phase 4.** Water and protein reserves, starvation death and hormones.

## 3. Sleep pressure and the engine sleep state (LIFE-R-030, BRAIN-R-045)

- **Sleep pressure S ∈ [0, 1]** follows Borbély's process S:
  - while awake, dS/dt = (1 − S) / τ_wake;
  - while asleep, dS/dt = −S / τ_sleep;
  - t is life-clock time; τ_wake and τ_sleep are registry entries (`ASSUMPTION`, fly-hour scale).
- **Route.** S reaches the brain only through the `sleep_pressure` route (dFB / R5 excitability, 004 §8).
- **Engine sleep state (BRAIN-R-045)** is computed from the fly's own signals: body quiescence (no locomotion command above `sleep.move_threshold`) for ≥ 5 fly-minutes (WATCH-OQ-01, registry), with dFB activity as a confirming signal logged for review. It never uses a Watcher classification.
- **Effects.** The sleep state is published and used by the homeostat. Downscaling of plastic weights (BRAIN-R-043) arrives with the plasticity rules.
