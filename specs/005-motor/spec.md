# 005 — Motor (descending neurons → body)

| Field | Value |
|---|---|
| Status | Approved — 2026-10-12 |
| ID prefix | `MOTOR` |
| Phase | 2 (readout and closed loop; owns the Phase-2 emergence gates) |
| Plan refs | §5.4, §7 (mating needs two brains), §15 Phase 2 gate |
| Depends on | 001 (I/O map), 002, 003, 004, 006 (energy cost, stamina) |
| Used by | 003 (body execution), 008 (signal emission), 010 (intent decoding) |
| Constitution | CONST-1.2 (motor layer: execute, never decide), CONST-1.4, CONST-7.3 |

## 1. Purpose

Turn the activity of descending neurons (DNs) and brain motor neurons (MNs) into the body's **motor primitives**, the "muscle layer". The brain chooses; the motor layer only executes, within biomechanical limits. This spec also owns the **Phase-2 closed-loop emergence gates**, because this is where the sense → brain → body loop closes.

## 2. Scope

**In scope:** the primitive catalog; the readout from DN/MN groups; how concurrent primitives combine; song synthesis parameters; motor effort for energy accounting; the test-only DN-stimulation harness; the Phase-2 emergence gates.

**Out of scope:** body physics (003); the brain (002); interpreting behavior (010).

## 3. Motor primitive catalog (v1)

Mappings live in the versioned I/O map with a citation for each entry. The neuron names below are examples and starting points, not a complete list.

| # | Primitive | Body effect | Readout source (examples) |
|---|---|---|---|
| 1 | Walk forward / backward | Forward speed command (sign gives direction) | Forward-walking DNs; MDN for backward walking (Bidaye et al. 2014) |
| 2 | Steer | Turning rate while walking or flying | DNa01, DNa02 |
| 3 | Escape takeoff | Ballistic jump, then flight | Giant Fiber (DNp01) and other takeoff DNs |
| 4 | Flight steering and landing | Yaw, pitch, thrust; landing extension | Flight and landing DNs (per annotation) |
| 5 | Grooming | Grooming movement of a body part (head, antennae, wings, abdomen) | Grooming DNs, e.g. aDN, DNg11, DNg12 (Hampel et al. 2015) |
| 6 | Proboscis extension and ingestion | Proboscis out; pumping rate | Brain MNs such as MN9; pharyngeal pump MNs |
| 7 | Wing extension and song | One-wing extension; vibration mode, IPI and frequency | pIP10 and other song DNs |
| 8 | Lunge and wing threat | Lunge impulse; both wings raised | Aggression-related DNs (MaleCNS/BANC labels, `ASSUMPTION` where unlabelled) |
| 9 | Foreleg actions | Tapping, fencing, boxing, holding, kicking | Foreleg DNs (per annotation, `ASSUMPTION`) |
| 10 | Abdomen bend and copulation | Male abdomen curl; genital coupling output | Copulation-related DNs (per annotation, `ASSUMPTION`) |
| 11 | Vaginal-plate opening (female acceptance) | Vaginal plate opens | vpoDN (Wang et al. 2021) |
| 12 | Ovipositor extrusion | Ovipositor extends | DNs per annotation (`ASSUMPTION`) |
| 13 | Wing flicking (female rejection) | Brief wing movements | DNs per annotation (`ASSUMPTION`) |
| 14 | Egg-laying | Egg deposition sequence | oviDNs (Wang et al. 2020) |

## 4. Requirements

### 4.1 Readout

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| MOTOR-R-001 | M | THE ENGINE SHALL compute each primitive's command from the filtered firing rates of its mapped DN/MN groups, using a documented transfer function (thresholds, gains, time constants in the registry). The only other inputs are the body state needed to execute it (mode, contacts, stamina). | T-MOTOR-U-001 |
| MOTOR-R-002 | M | A primitive SHALL never trigger itself, chain into another primitive, or run a sequence. It is active only while its neurons drive it. The exception is ballistic actions (escape jump, lunge, egg deposition), whose fixed physical duration is in the registry. | T-MOTOR-I-001 |
| MOTOR-R-003 | M | Concurrent primitives SHALL combine by superposition, limited only by biomechanical constraints listed in the registry (e.g. no walking while airborne; song only while grounded; coupling only while grounded and in contact). No priority rule may exist beyond those constraints. | T-MOTOR-U-002, review |
| MOTOR-R-004 | M | DNs with no known function SHALL be simulated and have their rates published on the Observation Stream, but SHALL drive no movement. | T-MOTOR-U-003 |
| MOTOR-R-005 | M | Mating SHALL need both brains, through the coupling rule in BODY-R-005. | T-BODY-U-005 |
| MOTOR-R-006 | M | Song parameters (pulse vs sine mode, inter-pulse interval, carrier frequency, amplitude, which wing) SHALL be derived from the activity of song-related output neurons through a documented mapping (see MOTOR-OQ-01). | T-MOTOR-U-004 |
| MOTOR-R-007 | M | THE ENGINE SHALL report motor effort per primitive to physiology for energy cost. Physiology may cap the maximum output amplitude by stamina, injury and age (006). | T-MOTOR-U-005 |
| MOTOR-R-008 | M | Mappings SHALL be versioned in the I/O map per sex, using the cross-dataset matching (CONN-R-030). | T-CONN-U-004 |
| MOTOR-R-009 | M | The latency from DN activity to movement onset SHALL be a registry value. | T-MOTOR-U-001 |
| MOTOR-R-010 | M | THE ENGINE SHALL publish primitive activations and DN group rates on the Observation Stream. | T-MOTOR-U-003 |

### 4.2 Validation harness (test-only)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| MOTOR-R-011 | M | THE SYSTEM SHALL provide an open-loop test harness (CONST-1.4) that drives a mapped DN group in isolation and checks for the expected primitive. Examples: MDN → backward walking; Giant Fiber → takeoff; pIP10 → wing extension and song; vpoDN → vaginal-plate opening; oviDN → egg-laying (with substrate and eggs present). | T-MOTOR-V-001 |
| MOTOR-R-012 | M | The harness SHALL be absent from the production package, and an `import-linter` contract SHALL forbid production code from importing it. | T-MOTOR-I-002 |

### 4.3 Closed-loop emergence gates (Phase 2)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| MOTOR-R-020 | M | THE SYSTEM SHALL provide an emergence suite in which every trial starts from world stimuli only: no DN stimulation, no scripts, no per-trial parameter changes. | T-MOTOR-E-001..005 |
| MOTOR-R-021 | M | Every gate run SHALL be reported in full (all seeds, all trials, pass or fail) together with the template, registry and config versions (CONST-7.3). | T-MOTOR-E-001..005 |

## 5. Acceptance criteria — Phase-2 gates

The thresholds are **proposals for your review**. Each gate uses n ≥ 50 trials across distinct individuals and seeds, compared with a matched control; significance at p < 0.01.

| ID | Gate | Stimulus → expected emergent response | Proposed pass criterion |
|---|---|---|---|
| MOTOR-AC-01 | Sugar → feeding | A hungry fly's labellum touches sucrose | Proboscis extension + ingestion in ≥ 60% of trials; significantly more than with water in sated flies |
| MOTOR-AC-02 | Bitter → rejection | Sucrose + bitter vs sucrose alone | Extension/ingestion rate significantly lower with bitter |
| MOTOR-AC-03 | Looming → escape | An expanding dark disk on a collision course | Takeoff or escape movement in ≥ 50% of trials, starting before the projected collision |
| MOTOR-AC-04 | Odor plume → approach | A vinegar-like plume upwind in the wind field | Reaches the source significantly more often than with no odor (upwind bias) |
| MOTOR-AC-05 | Darkness + sleep pressure → sleep | Night phase with high sleep pressure vs day with low pressure | Sleep amount significantly higher (definition: see WATCH-OQ-01) |
| MOTOR-AC-06 | Open-loop mapping | Harness stimulation of each mapped DN group | Expected primitive in ≥ 90% of trials |
| MOTOR-AC-07 | No self-driven motion | All DN outputs clamped to zero (test) | No primitive becomes active |

## 6. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-MOTOR-U-001 | unit | Transfer functions and latency. |
| T-MOTOR-U-002 | unit | Superposition and biomechanical constraints only. |
| T-MOTOR-U-003 | unit | Unmapped DNs are logged and do not move the body. |
| T-MOTOR-U-004 | unit | Song parameter synthesis. |
| T-MOTOR-U-005 | unit | Effort reporting and stamina limits. |
| T-MOTOR-V-001 | validation | Open-loop DN → primitive (harness). |
| T-MOTOR-E-001..005 | emergence | The five Phase-2 gates. |
| T-MOTOR-I-001 | invariant | No self-triggering, chaining or sequencing (static audit + runtime). |
| T-MOTOR-I-002 | invariant | Harness cannot be imported in production. |

## 7. Assumptions and open questions

| ID | Question | Proposal | Decision |
|---|---|---|---|
| MOTOR-OQ-01 | **No VNC in v1.** Pattern generation such as walking gait, pulse vs sine song pattern and flight power lives in the ventral nerve cord, which brain-only templates lack. Is it acceptable under the constitution for the motor layer to implement VNC-level pattern generation, driven by DN outputs? | Yes, as "muscle layer" code with one condition: *whether* and *what* to do (sing or not, which mode, toward whom) must be set by brain outputs through a documented mapping. Every such mapping is flagged `ASSUMPTION`. v2 (BANC / full MaleCNS) replaces it. | Accepted (proposal), 2026-10-12 |
| MOTOR-OQ-02 | Many aggression, copulation and rejection DNs have no established functional label. | Start from MaleCNS/BANC annotations and the literature. Where a primitive has no credible mapping, report it as "not yet mappable" rather than invent one. | Accepted (proposal), 2026-10-12 |
| MOTOR-OQ-03 | Gate thresholds in §5. | Please confirm or adjust. | Accepted: the proposed thresholds in §5, 2026-10-12. |
| MOTOR-OQ-04 | **Phase ordering.** Gate MOTOR-AC-05 needs sleep pressure, which the plan delivers in Phase 4 (006). | Either (a) move this gate to Phase 4, or (b) bring a minimal sleep homeostat into Phase 2. Proposal: (b). | Accepted: option **(b)**. A minimal sleep homeostat (LIFE-R-030) is brought into Phase 2. 2026-10-12. |
