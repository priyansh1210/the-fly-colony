# 006 — Physiology & Life Cycle

| Field | Value |
|---|---|
| Status | Draft — awaiting review |
| ID prefix | `LIFE` |
| Phase | 4 (metabolism, circadian clock, sleep homeostasis, aging, death, development); 5 (reproductive physiology, population control) |
| Plan refs | §5.5, §6 (circadian), §4.3 (body→brain), §7 (babies) |
| Depends on | 002, 003, 004 (route catalog), 005 (effort), 009 (life clock) |
| Used by | 007, 008, 010, 011 |
| Constitution | CONST-1.2 (physiology layer), CONST-1.5 (pre-adult stages), CONST-6 |

## 1. Purpose

Give every fly a living body chemistry (energy, water, protein, hormones, a circadian clock, sleep pressure, maturation, reproduction and aging) and run the life cycle from egg to death. Physiology affects the brain **only** through the catalogued interoceptive routes (SENSE-R-060).

## 2. Scope

**In scope:** metabolism and water balance; hormones as body variables; the circadian oscillator; the sleep homeostat; stages, timing and survival from egg to adult; sexual maturation; female reproductive physiology; aging and mortality; death and corpses; injury and stamina; population caps; temperature dependence; scaling under the compressed clock.

**Out of scope:** genomes and inheritance (007); how eggs and pupae are represented in the world (003); how the Watcher labels hunger or sleep (010).

## 3. Time base

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LIFE-R-001 | M | Every physiological rate SHALL be defined per fly day and integrated in **life-clock time** (CLOCK-R-003). The exception is a small, listed set of **behavior-time processes** that run in neural time (e.g. volume ingested per second of feeding, sperm transfer during copulation), each with a declared compression scaling (see LIFE-OQ-01). | T-LIFE-U-001 |

## 4. Requirements

### 4.1 Metabolism and water

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LIFE-R-010 | M | Each adult SHALL have an energy reserve (carbohydrate and lipid lumped together), a protein reserve and a water reserve, with an optional crop buffer (S). | T-LIFE-U-002 |
| LIFE-R-011 | M | WHILE the ingestion primitive is active and the proboscis touches food or water, THE ENGINE SHALL transfer nutrients at the registry ingestion rate × substance composition, depleting the source (WORLD-R-021). | T-LIFE-U-002 |
| LIFE-R-012 | M | Energy use SHALL equal basal metabolism (scaled by genome, body size and temperature Q10) plus activity costs per unit motor effort, with flight ≫ walking, and song and fighting in between. | T-LIFE-U-003 |
| LIFE-R-013 | M | Water loss SHALL depend on temperature, humidity and flight. | T-LIFE-U-003 |
| LIFE-R-014 | M | IF energy reaches zero THEN the fly SHALL die of starvation. IF water reaches zero THEN it SHALL die of dehydration. Survival curves must match registry targets (proposal: median starvation survival with water ~2–3 fly days at 25 °C, females longer than males; `ASSUMPTION` to verify). | T-LIFE-V-001 |
| LIFE-R-015 | M | Hormonal signals (AKH released when hemolymph sugar is low; insulin-like peptides released by insulin-producing-cell activity or after feeding) SHALL be body variables. They reach the brain only through catalogued routes. | T-LIFE-U-004 |

### 4.2 Circadian clock

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LIFE-R-020 | M | Each fly SHALL have a molecular-oscillator model for its clock-neuron groups. Its free-running period is 1 fly day × a genome factor near 1. It is entrained by light at the fly (CRY) and by eye input. Its output is the clock-neuron excitability route. | T-LIFE-V-002 |
| LIFE-R-021 | M | The default light schedule SHALL be 12 h light : 12 h dark. Genesis is Day 1, 06:00. | T-CLOCK-U-002 |
| LIFE-R-022 | M | In constant darkness the oscillator SHALL keep free-running. | T-LIFE-V-002 |

### 4.3 Sleep homeostasis

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LIFE-R-030 | M | Each fly SHALL have a sleep-pressure variable that builds during wake and dissipates during sleep (engine sleep state, BRAIN-R-045) in life-clock time. It acts on the brain only through the sleep-pressure route (`ASSUMPTION` mechanism). | T-LIFE-U-005 |
| LIFE-R-031 | M | Aging SHALL fragment sleep only through changes to route and physiological parameters (registry, `ASSUMPTION`), never through direct behavior changes. | T-LIFE-V-004 |

### 4.4 Development (pre-adult, CONST-1.5)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LIFE-R-040 | M | Stage durations at 25 °C SHALL be about: egg ~1 fly day, larva (L1–L3) ~4, pupa ~4. They depend on temperature and vary per individual (registry). | T-LIFE-V-003 |
| LIFE-R-041 | M | An egg SHALL be viable only if it was fertilized, laid on suitable substrate, and allowed by the population caps (R-071). | T-LIFE-U-006 |
| LIFE-R-042 | M | In v1, larvae SHALL be developmental processes without behavior: feeding from nursery food, growth, and density-dependent survival. The pupation site is drawn from a documented distribution on the nursery walls. | T-LIFE-U-007 |
| LIFE-R-043 | M | Larval nutrition SHALL set adult body size, together with the genome. | T-LIFE-U-007 |
| LIFE-R-044 | M | WHEN a pupa completes development THE ENGINE SHALL eclose an adult at the pupa's location: body from genome × nutrition, brain built per BRAIN-R-001, sex from the genome. | T-LIFE-U-008 |
| LIFE-R-045 | M | Sexual maturity SHALL be reached 0.5–1 fly day after eclosion (registry, per sex). Maturity acts only through the maturity route, gating receptivity- and courtship-related physiology, never behavior directly. | T-LIFE-U-009 |

### 4.5 Female reproductive physiology

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LIFE-R-050 | M | Egg maturation SHALL need protein reserve, SHALL be boosted after mating, and SHALL be capped at a registry egg load. | T-LIFE-U-010 |
| LIFE-R-051 | M | WHEN coupling lasts at least the registry minimum transfer duration THE ENGINE SHALL transfer sperm (count), sex peptide and cVA to the female. Sex peptide then lowers receptivity for a registry duration (a few fly days) and raises egg production and egg-laying drive, all through routes. | T-LIFE-U-011 |
| LIFE-R-052 | M | Stored sperm SHALL be used up as eggs are fertilized, and the sex-peptide effect SHALL fade as sperm run out. | T-LIFE-U-011 |
| LIFE-R-053 | M | Fecundity SHALL have a genome-scaled maximum of eggs per fly day, set to fit the compressed behavior-time budget (LIFE-OQ-02). | T-LIFE-U-010 |

### 4.6 Aging, injury and death

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LIFE-R-060 | M | Mortality from aging SHALL follow a Gompertz hazard h(a) = α·e^(β·a), with a in fly days and α, β set by the genome's lifespan factor and diet, giving a default median of ~45 fly days. | T-LIFE-V-004 |
| LIFE-R-061 | M | Aging SHALL lower stamina (maximum motor output) and fragment sleep (R-031) at registry rates (`ASSUMPTION`). | T-LIFE-V-004 |
| LIFE-R-062 | M | Injury points (BODY-R-006) SHALL reduce stamina temporarily and heal at a registry rate. | T-LIFE-U-012 |
| LIFE-R-063 | M | Causes of death SHALL be: aging, starvation, dehydration, injury (only if enabled), and removal by command. Every death is published with its cause. | T-LIFE-U-013 |
| LIFE-R-064 | M | WHEN a fly dies THE ENGINE SHALL remove its brain from the batch and turn its body into a corpse entity that decays (WORLD-R-050). | T-LIFE-U-013 |

### 4.7 Population control

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LIFE-R-070 | M | THE ENGINE SHALL enforce an adult population cap (default 150) and a larva cap (default 300), both settable by the Watcher. | T-LIFE-I-001 |
| LIFE-R-071 | M | An egg SHALL be marked non-viable when it is laid IF larvae + viable eggs ≥ larva cap, OR adults + pupae ≥ adult cap. The egg is still laid visibly; it just never hatches. | T-LIFE-I-001 |
| LIFE-R-072 | M | Larval survival SHALL depend on density (food per larva), acting as natural regulation. | T-LIFE-U-007 |
| LIFE-R-073 | M | Caps SHALL NEVER kill existing flies. | T-LIFE-I-001 |

### 4.8 Temperature

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LIFE-R-080 | S | Development and metabolic rates SHALL depend on temperature (Q10 or a degree-day model from the registry). | T-LIFE-U-014 |

## 5. Acceptance criteria

| ID | Criterion |
|---|---|
| LIFE-AC-01 | Starvation and dehydration survival curves (n ≥ 50 neutral-genome flies) match registry targets within tolerance. |
| LIFE-AC-02 | Lifespan distribution median is 45 ± 5 fly days with Gompertz shape (neutral genome, standard diet). |
| LIFE-AC-03 | The oscillator entrains to LD 12:12 and free-runs in constant darkness with the genome period. |
| LIFE-AC-04 | **Phase 4 gate:** a day/night activity profile emerges. Activity differs significantly between light and dark phases, and most sleep falls in the dark phase. |
| LIFE-AC-05 | Egg → adult timing matches registry stage durations within tolerance at 25 °C. |
| LIFE-AC-06 | Over 7 fly days with abundant food, the caps hold and no existing fly is killed by a cap. |
| LIFE-AC-07 | While the engine is suspended, no physiological variable changes. |
| LIFE-AC-08 | A mated female's receptivity route is suppressed and her egg output rises; both fade as sperm deplete. |

## 6. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-LIFE-U-001 | unit | Life-clock integration and the listed behavior-time processes; physiology continues in chambers. |
| T-LIFE-U-002..014 | unit | Reserves and ingestion; expenditure; hormones; sleep homeostat; egg viability; larvae; eclosion; maturity; oogenesis; mating transfers; injury; death; temperature. |
| T-LIFE-V-001 | validation | Starvation and dehydration curves. |
| T-LIFE-V-002 | validation | Circadian entrainment and free-running. |
| T-LIFE-V-003 | validation | Development timing. |
| T-LIFE-V-004 | validation | Aging and lifespan distribution. |
| T-LIFE-E-001 | emergence | Day/night activity profile (Phase 4 gate). |
| T-LIFE-I-001 | invariant | Caps hold and never kill. |

## 7. Assumptions and open questions

| ID | Question | Proposal |
|---|---|---|
| LIFE-OQ-01 | **Compressed-clock energy balance.** A fly day's worth of energy is burned in 1 real hour of life-clock time, but eating happens at biological speed in neural time. Unscaled, a fly could not eat enough. | Scale ingestion rate (volume per neural second of feeding) by C = 86400 / D (24× at the default), declared as a behavior-time scaling in the registry. Stomach and crop capacity stay biological. |
| LIFE-OQ-02 | **Egg-laying time budget.** Real females lay ~50–100 eggs per day, but each egg-laying act takes real neural time, and a fly day contains only 1 real hour of behavior. | Default fecundity target of 10–20 eggs per fly day (`ASSUMPTION`) so egg-laying fits the budget. The caps make higher output unnecessary. Alternative: allow a short multi-egg bout per act. |
| LIFE-OQ-03 | Sleep bout definition: "≥ 5 min immobility" measured in fly minutes or neural minutes? | See WATCH-OQ-01 (the proposal is fly minutes). |
| LIFE-OQ-04 | Cap semantics (R-071). | As written; please confirm. |
| LIFE-OQ-05 | Larvae and pupation-site rule (CONST-1.5). | As written; a v2 larval connectome would lift this. |
| LIFE-OQ-06 | A minimal sleep homeostat is needed in Phase 2 for MOTOR-AC-05. | Bring R-030 forward into Phase 2 (MOTOR-OQ-04). |
| LIFE-OQ-07 | Mechanism for the maturity route. | `ASSUMPTION`: a maturation factor scaling excitability of the receptivity and courtship-drive neurons. Revisit with the literature in design. |
