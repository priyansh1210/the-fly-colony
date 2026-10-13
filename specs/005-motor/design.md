# 005 — Motor: Design (Phase 2 scope)

| Field | Value |
|---|---|
| Status | Phase 2 design, 2026-10-13 |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |

## 1. Modules

```
src/flycolony/motor/
  primitives.py   primitive table (config/motor/primitives.yaml) → resolved neuron groups per template
  readout.py      MotorBatch: group rates → transfer → latency line → commands; effort; constraints
src/flycolony/engine/
  gates.py        emergence-gate protocols, trial batching, statistics, reports (MOTOR-R-020, -021)
tests/harness/
  stimulation.py  open-loop DN stimulation (test-only; MOTOR-R-011, -012)
```

## 2. Primitive table (MOTOR-R-001, -008, -009)

- **`config/motor/primitives.yaml`.**
  - Each primitive names its I/O-map motor groups (resolved per sex through the template's I/O map, which already uses the cross-dataset matching, MOTOR-R-008).
  - Optional side split (L/R by the template `side`).
  - Transfer, latency and constraints all reference registry ids.
- **Transfer (MOTOR-R-001).**
  - `rate` is the group's filtered firing rate (B4 output groups, exponential filter with τ = `motor.rate_tau_ms`).
  - `cmd = max_cmd · s((rate − θ) / r_half)`, where `s(x) = x / (1 + x)` for x > 0 and 0 otherwise.
  - θ, r_half and max_cmd are registry entries per primitive. Thresholds sit above each group's spontaneous rate under background noise (measured in Phase 1: mean 6.7 Hz), so that noise alone gives small commands. The threshold value is an `ASSUMPTION`, calibrated globally.
- **Latency (MOTOR-R-009).** A ring buffer of `motor.latency_ms / physics_ms` steps per primitive (registry, per primitive).

| Primitive | Groups (Phase-0 I/O map) | Command | Source |
|---|---|---|---|
| walk forward | `walk.forward` (BDN2) | + speed | Sapkal et al. 2024 |
| walk backward | `walk.backward` (MDN) | − speed | Bidaye et al. 2014 |
| steer | `walk.steer` (DNa01/DNa02), L − R | yaw rate | Rayshubskiy et al. 2020 |
| escape takeoff | `escape.takeoff` (Giant Fiber) | ballistic jump trigger | von Reyn et al. 2014 |
| landing | `flight.landing` | landing extension while airborne | Ache et al. 2019 |
| proboscis extension | `feeding.proboscis_extension` (MN9) | extension target | Gordon & Scott 2009 |
| ingestion | `feeding.ingestion` (pharyngeal MNs) | pump rate | Manzo et al. 2012; Schlegel et al. 2024 |
| antennal grooming | `groom.antenna` (aDN) | grooming state | Hampel et al. 2015 |
| egg-laying | `oviposition` (oviDN) | Phase 5 | Wang et al. 2020 |

- **Not yet mappable (MOTOR-OQ-02), reported as such:**
  - flight steering and thrust;
  - lunge and wing threat;
  - foreleg actions;
  - abdomen bend and copulation;
  - vaginal-plate opening (vpoDN is a Phase-5 mapping task);
  - ovipositor extrusion;
  - wing flicking;
  - song (pIP10 is a Phase-5 mapping task).
- **Ballistic exceptions (MOTOR-R-002).**
  - *Escape jump:* one GF spike within the trigger window starts it, because a single GF spike triggers the short-mode takeoff (von Reyn et al. 2014). Its duration is in the registry.
  - *Lunge and egg deposition* are Phase 5.
  - Nothing else latches. Every other command follows its rate each step.
- **Unmapped DNs (MOTOR-R-004).** All descending neurons not in the table are an `unmapped` output group. Their rates are published and drive nothing.

## 3. Combination and constraints (MOTOR-R-003)

- **Superposition.** Speed = forward − backward. Yaw = steer. Proboscis and ingestion are independent of locomotion.
- **The only gating is the biomechanical constraint table** (registry, `motor.constraints`):
  - walking only while grounded;
  - the jump only while grounded;
  - landing extension only while airborne;
  - ingestion only with the proboscis extended beyond `motor.ingest.min_extension` and the labellum in a liquid;
  - antennal grooming scales walking speed by `motor.groom.walk_factor` (the forelegs are busy).
- **No priority rule exists.** A review checklist item and T-MOTOR-I-001 (a static audit for conditionals on other primitives' commands) enforce it.

## 4. Effort (MOTOR-R-007)

- Effort per primitive is `|cmd| · cost` (registry, per primitive; flight ≫ walking), reported each physics step to physiology.
- The physiology stamina cap is a multiplier on max_cmd (1 in Phase 2).

## 5. Open-loop harness (MOTOR-R-011, -012)

- **Mechanism.** `tests/harness/stimulation.py` drives a group of non-sensory neurons (DNs, MN9) by adding a constant current to them through a test-only subclass of `BrainBatch`. The production class has no method for this, so no production path can stimulate a DN.
- **Isolation.** The import contract "production never imports tests" exists. A test asserts that the harness is absent from the built wheel.
- **Checks (MOTOR-AC-06).** Each mapped group in turn gets its expected primitive in ≥ 90% of 20 trials:
  - MDN → backward walking;
  - GF → takeoff;
  - BDN2 → forward walking;
  - DNa02 L → left turn;
  - MN9 → proboscis extension;
  - pharyngeal MNs → pumping;
  - aDN → grooming;
  - landing DNs (airborne) → extension.

## 6. Emergence gates (MOTOR-R-020, -021; MOTOR-AC-01..05, -07)

### 6.1 Rules

- **World stimuli only.** Every trial starts from world stimuli. Allowed setup:
  - arena geometry, food and odor sources, wind, light and looming commands;
  - the fly's starting pose;
  - its physiological history (e.g. hours since last meal), integrated by the physiology model over the stated period before the trial.
- **No DN stimulation, scripts or per-trial parameter changes.** Seeds differ per trial, and each trial is a different individual: a seed and default `FlyBrainSpec` gains until the genome (007) exists.
- **Batching.** Trials run as batched worlds (003 §2). The report contains every trial: seed, outcome, measured quantities. It also records the template id, registry hash, config snapshot, pipeline version, brain dt, and vision mode (full or luminance).
- **Statistics.** One-sided Fisher exact test for proportions; one-sided Mann–Whitney U for continuous measures. α = 0.01. n ≥ 50 per condition (MOTOR-AC table).

### 6.2 Protocols

| Gate | Arena | Condition vs control | Trial length | Outcome |
|---|---|---|---|---|
| AC-01 sugar → feeding | 20 × 20 mm box; drop under the labellum at start | hungry (24 fly-h without food) + sucrose drop vs sated + water drop | 2 s | proboscis extension > `gate.feed.min_extension` **and** ingested volume > 0 |
| AC-02 bitter → rejection | same | hungry + sucrose + bitter vs hungry + sucrose | 2 s | same; lower with bitter |
| AC-03 looming → escape | 60 × 60 × 40 mm box | looming disk on a collision course (l/v = 40 ms, random azimuth in the lateral field) vs no disk over the same window | until projected collision | takeoff before projected collision; ≥ 50% of trials |
| AC-04 plume → approach | 160 × 50 × 30 mm wind tunnel, 0.3 m/s | vinegar-like source (acetic acid + ethyl acetate + acetoin) at the upwind end vs no odor | 30 s | reach within 15 mm of the source |
| AC-05 dark + pressure → sleep | 60 × 60 mm box with food and water | night + high sleep pressure (12 fly-h awake) vs day + low pressure | 30 fly-min (75 s neural at D = 3600) | sleep minutes: immobility bouts ≥ 5 fly-min (WATCH-OQ-01) |
| AC-07 no self-motion | any | all DN outputs clamped to zero (test hook in the readout) | 10 s | no primitive active, body at rest |

- **Feeding thresholds.** The extension threshold and the sucrose and bitter concentrations are registry entries: 100 mM sucrose and 10 mM caffeine-equivalent bitter, standard PER assay values (Moon et al. 2006; Meunier et al. 2003).
- **Plume (AC-04).** The source's emission rates and the wind speed are registry entries. With the luminance-mode vision fallback, AC-04 still runs, because it depends on olfaction and JO.
- **Sleep (AC-05).** Sleep is measured from body state only. The engine sleep state (BRAIN-R-045) and its homeostat are in the 006 design.

### 6.3 Running

- `colony gates run [--gate NAME] [--trials N]` writes `specs/005-motor/reports/<template>.<gate>.json` and prints the summary. The emergence tests (`tests/emergence/`, marker `emergence`) read the stored reports and check the pass criteria and the model hash, like the Phase-1 gate records.
- **Cost estimate** (Phase-1 throughput, ~0.3 fly-s/s at 16 flies): AC-01/02 ≈ 0.2 h, AC-03 ≈ 0.1 h, AC-04 ≈ 3 h, AC-05 ≈ 7 h.

## 7. Deviations and notes

- **Thresholds.** The transfer thresholds are the main free parameters between brain and body. They are global per primitive (never per trial or per gate) and calibrated once against spontaneous activity, so that the resting fly does not walk continuously. That calibration is in the report.
- **Partial repertoire.** If a gate fails, the report says so with the measured numbers. No gate-specific tuning is allowed (CONST-7.3; plan §17 "accept a partial repertoire with honest reporting").
