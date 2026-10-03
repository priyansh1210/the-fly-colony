# 008 — Communication & Social Signals

| Field | Value |
|---|---|
| Status | Draft — awaiting review |
| ID prefix | `COMM` |
| Phase | 5 (signals, reception, social emergence); 6 (translation polish) |
| Plan refs | §1 ("Speak / communicate"), §7, §11 (`speech/` logs) |
| Depends on | 003 (fields, source tags, contacts), 004 (reception), 005 (emission), 006 (mating transfers), 009, 010 (behavior classifier) |
| Used by | 010 (relationships), 011 (speech logs, diaries), 013 (speech bubbles) |
| Constitution | CONST-1 (no signal by rule), CONST-2.2 (read-only), CONST-7 (translations are interpreted) |

## 1. Purpose

Flies "talk" through real fly channels: courtship song, aggression sounds, pheromones, touch and visual displays. This spec makes every signal a **first-class, logged event** with an emitter, parameters, the flies that **physically received** it, and an **English translation** by the Watcher. Nothing here gives a fly an extra channel: flies perceive each other only through their senses.

## 2. Scope

**In scope:** the signal catalog; emission as physical output; per-source attribution and the receiver list; signal segmentation; the translation table; reception records; detection of courtship and fight sequences; measured social phenomena.

**Out of scope:** the physics of sound and odor (003); transduction (004); motor output (005); emotion and relationship scoring (010).

## 3. Signal catalog (v1)

| Signal | Channel | Emitted by (physical) | Received through | Key parameters |
|---|---|---|---|---|
| Pulse song | near-field sound | one-wing vibration, pulses | Johnston's organ A/B | inter-pulse interval (IPI), carrier frequency, pulses per train, amplitude, wing |
| Sine song | near-field sound | one-wing continuous vibration | Johnston's organ A/B | frequency, duration, amplitude |
| Aggression sound | near-field sound | wing movements during fights | Johnston's organ | `ASSUMPTION` model |
| cVA | volatile + contact | males; mated females (transferred) | Or67d/Or65a ORNs; contact | concentration |
| 7-T | contact hydrocarbon | male cuticle | gustatory/pheromone neurons | contact dose |
| 7,11-HD | contact hydrocarbon | female cuticle | gustatory/pheromone neurons | contact dose |
| Tapping | touch + taste | male foreleg on another fly | leg GRNs and mechanoreceptors (see SENSE-OQ-01) | contacts, duration |
| Licking | taste | proboscis on genitalia | receiver's touch; emitter's taste | duration |
| Fencing / boxing / holding | touch | forelegs | mechanoreceptors | impulse, duration |
| Wing threat | visual | both wings raised | vision | angle, duration |
| Lunge | visual + impact | body lunge | vision, touch | impulse |
| Wing flicking, kicking (rejection) | visual + touch | female wings and legs | vision, touch | rate |
| Ovipositor extrusion | visual + contact | female abdomen | vision, touch | duration |
| Abdomen curl (copulation attempt) | visual + touch | male abdomen | vision, touch | duration |

## 4. Requirements

### 4.1 Signals as events

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| COMM-R-001 | M | Every signal SHALL be logged as an event with: `signal_id`, emitter, type, parameters, start and end times (three timestamps each), receiver list, translation, evidence, confidence and translator version. | T-COMM-U-001 |
| COMM-R-002 | M | A signal SHALL exist only as physical output of motor primitives or body chemistry. No signal is ever emitted by rule. | T-COMM-I-001 |
| COMM-R-003 | M | THE ENGINE SHALL compute, for every fly, how much of its sensory input on the acoustic, volatile, contact-chemical, touch and visual (fly in view) channels comes from each source entity, and SHALL publish this attribution on the Observation Stream. This is observation-only and never feeds back into the simulation. | T-COMM-U-002, T-SENSE-I-002 |
| COMM-R-004 | M | THE WATCHER SHALL segment signals from the emitter's body and motor data (e.g. vibration mode and IPI, wing-threat posture). It SHALL set the receiver list to every fly whose relevant sensory-neuron input from that source exceeded a registry threshold, bystanders included (overhearing). | T-COMM-U-003 |
| COMM-R-005 | M | THE WATCHER SHALL log, for each receiver, a "received" entry in its `speech/` log: what was perceived, through which channel, and how strongly. | T-COMM-U-004 |
| COMM-R-006 | M | Pheromone signals come from continuous emitters. THE WATCHER SHALL log reception onset and offset when a receiver's channel crosses threshold, not a continuous stream. | T-COMM-U-004 |
| COMM-R-007 | M | Mating transfers (e.g. cVA to the female, LIFE-R-051) SHALL be logged as life events and reflected in later pheromone receptions. | T-COMM-U-005 |
| COMM-R-008 | M | Flies SHALL have no shared memory, message bus or any channel to each other except their senses. | T-COMM-I-002 |

### 4.2 Translation (the Watcher's voice)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| COMM-R-010 | M | THE WATCHER SHALL translate each signal into short first-person English using a versioned translation table. Inputs: signal type, parameters, and context (emitter and receiver sex and state, current behavior bout from 010). Output: `translation`, `interpreted: true`, `evidence`, `confidence`. | T-COMM-U-006 |
| COMM-R-011 | M | Translations SHALL be context-dependent where the biology is. For example, ovipositor extrusion by a mated female during courtship → "I'm already mated — go away", but in a virgin female the same act may signal acceptance (`ASSUMPTION`, cited in the table). | T-COMM-U-006 |
| COMM-R-012 | M | IF no table entry matches THEN the translation SHALL be `untranslated`, with evidence attached. | T-COMM-U-006 |
| COMM-R-013 | M | The LLM SHALL NOT be needed for translation. It may only rephrase in diaries (013). | review |

Example rows (the full table is drafted in design):

| Signal + context | Translation | Confidence basis |
|---|---|---|
| Pulse song, male → female | "I'm courting you." | Well established |
| Sine song, male → female | "Still here… still interested." | Moderate |
| Wing threat, male → male near food | "Back off!" | Well established |
| Lunge | "Get away from here!" | Well established |
| Tapping | "(tasting you) Who are you?" | Interpretive |
| Female wing flicking / kicking | "Not interested." | Moderate |
| Female slows + vaginal plate opens | "…Okay." | Well established |
| cVA detected by a male | "(smells) Another male was here." | Interpretive |

### 4.3 Social behavior (emergent, detected only)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| COMM-R-020 | M | Courtship elements (orient, follow, tap, sing, lick, attempt copulation) SHALL arise only from the male's brain. Female acceptance (slowing, vaginal-plate opening) and rejection (running, wing flicking, kicking, ovipositor extrusion) SHALL arise only from the female's brain. The Watcher detects and logs each sequence and its transitions. | T-COMM-E-001 |
| COMM-R-021 | M | Fight elements (approach, wing threat, fencing, lunging, boxing, holding, tussling, chasing) SHALL be detected and logged. The Watcher decides the outcome of each encounter (010). | T-COMM-E-002 |
| COMM-R-022 | S | THE WATCHER SHALL measure and report these expected emergent phenomena, which are not required to pass: courtship conditioning after rejection; less courtship toward mated, cVA-carrying females; winner and loser effects; dominance hierarchies; cVA-mediated aggregation. | T-COMM-E-003 |

## 5. Acceptance criteria

| ID | Criterion |
|---|---|
| COMM-AC-01 | A synthetic song source 2 mm from fly A and 5 cm from fly B lists A (and any bystander within range) as a receiver, and not B. |
| COMM-AC-02 | In a 1-fly-day colony run, every detected signal has either a translation or `untranslated`, and always carries evidence. |
| COMM-AC-03 | Song detection reaches ≥ 95% precision and recall against engine ground truth (vibration mode known to the engine). Targets for the other channels are set in design. |
| COMM-AC-04 | **Phase 5 gate (shared with GENE-AC-02):** at least one complete emergent courtship sequence ending in copulation is logged, with every signal and its receivers. |
| COMM-AC-05 | No signal event exists without a matching physical emission (invariant). |
| COMM-AC-06 | Bit-identity with the Watcher attached vs detached still holds with attribution enabled. |

## 6. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-COMM-U-001 | unit | Signal event schema. |
| T-COMM-U-002 | unit | Per-source attribution math. |
| T-COMM-U-003 | unit | Segmentation and receiver thresholding, including overhearing. |
| T-COMM-U-004 | unit | Reception records, including pheromone onset and offset. |
| T-COMM-U-005 | unit | Mating-transfer logging. |
| T-COMM-U-006 | unit | Translation table, context rules, `untranslated` fallback. |
| T-COMM-E-001 | emergence | Courtship sequences in a colony run. |
| T-COMM-E-002 | emergence | Fight sequences. |
| T-COMM-E-003 | emergence | Social-phenomena report. |
| T-COMM-I-001 | invariant | Every signal traces to a physical emission. |
| T-COMM-I-002 | invariant | No non-sensory channel between flies (static audit). |

## 7. Assumptions and open questions

| ID | Question | Proposal |
|---|---|---|
| COMM-OQ-01 | In v1, how are the song pattern (pulse vs sine) and IPI set without a VNC? | See MOTOR-OQ-01. |
| COMM-OQ-02 | Acoustic model for aggression sounds. | Treat as wing-generated near-field sound with registry spectra (`ASSUMPTION`). |
| COMM-OQ-03 | Include substrate vibration (abdominal quivering) as a channel? | Not in v1 (WORLD-R-043 "Could"). |
| COMM-OQ-04 | Translation tone: short first-person phrases like the plan's examples? | Yes. Tone is adjustable in the table without code changes. |
