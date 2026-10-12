# The Fly Colony — Specifications

**Status:** Approved 2026-10-12 · **Created:** 2026-09-26 · **Source:** master plan `plans/fuzzy-hugging-newt.md`

This folder is the spec-driven-development (SDD) source of truth. Nothing gets built until the spec that covers it is approved. A spec says **what** the system must do and **how we will know** it does it. The **how** goes into each feature's `design.md`, and the ordered work into `tasks.md`. Those two files are written only after you approve that feature's `spec.md`.

---

## How to review

1. Read the [constitution](000-constitution.md) first. Every other spec is subordinate to it.
2. For each spec, check:
   - **Scope:** is anything missing or out of place?
   - **Requirements:** is anything wrong, missing or over-specified?
   - **Acceptance criteria:** is this the bar you want?
   - **Open questions** at the end, each with a proposed answer.
3. Write decisions directly in the files (e.g. `Decision: …` under an open question), or tell me. I will update the specs and change their status to *Approved*.
4. [Decisions needed at review](#decisions-needed-at-review) below collects the questions with the biggest impact.

---

## Index

| # | Spec | Prefixes | Phase | Depends on | Status |
|---|---|---|---|---|---|
| 000 | [Constitution](000-constitution.md): the seven non-negotiable rules | `CONST` | all | — | Approved |
| 001 | [Connectome pipeline & foundations](001-connectome-pipeline/spec.md): BrainTemplates, I/O map, config, Parameter Registry | `CONN` | 0 | 000 | Approved |
| 002 | [Brain engine](002-brain-engine/spec.md): hybrid LIF/graded GPU simulator, neuromodulation, plasticity, validation | `BRAIN` | 1 (+2–4) | 001 | Approved |
| 003 | [Body & world](003-body-world/spec.md): Colony Dome, chambers, fields, ColonyBody physics | `WORLD`, `BODY` | 2 (+4, 5, 7) | 009 | Approved |
| 004 | [Senses](004-senses/spec.md): world → sensory neurons; interoceptive routes | `SENSE` | 2 | 001–003 | Approved |
| 005 | [Motor](005-motor/spec.md): DNs → motor primitives; **Phase-2 emergence gates** | `MOTOR` | 2 | 001–004, 006 | Approved |
| 006 | [Physiology & life cycle](006-physiology-lifecycle/spec.md): metabolism, circadian clock, sleep, development, aging, caps | `LIFE` | 4 (+5) | 002–005, 009 | Approved |
| 007 | [Genome, personality & reproduction](007-genome-personality-reproduction/spec.md): genes, presets, genesis, spawn, inheritance | `GENE` | 5 | 001–003, 006, 009 | Approved |
| 008 | [Communication](008-communication/spec.md): signals, receivers, translation, social emergence | `COMM` | 5 (+6) | 003–006, 009, 010 | Approved |
| 009 | [Watcher core, clocks & sleep](009-watcher-core-clocks-sleep/spec.md): stream, Control API, naturalization, sleep, checkpoints | `CLOCK`, `WATCH` | 3 (clock from 2) | 000, 002, 003 | Approved |
| 010 | [Mind decoder](010-mind-decoder/spec.md): behavior, feelings, thoughts, relationships, measured personality | `MIND` | 3–6 | 002, 005, 008, 009 | Approved |
| 011 | [`/flies` record](011-flies-logging/spec.md): layout, formats, completeness, retention | `LOG` | 3 (+later) | 008–010, 012 | Approved |
| 012 | [Task engine & chambers](012-task-engine-chambers/spec.md): task DSL, image arena, transfers, solvers, 70 tasks | `TASK` | 7 | 003, 004, 009–011 | Approved |
| 013 | [Console, dashboard & LLM](013-console-dashboard-llm/spec.md): CLI, web dashboard, grounded local LLM | `CLI`, `DASH`, `LLM` | 6, 8 | 009–012 | Approved |
| 014 | [Performance & fidelity](014-performance-fidelity/spec.md): FULL/HYBRID/COARSE, RTF targets, soak test | `FID`, `PERF` | 1–9 | 001, 002, 009, 011 | Approved |

---

## Conventions

### Requirement syntax (EARS)

| Pattern | Template |
|---|---|
| Ubiquitous | THE `<system>` SHALL `<response>` |
| Event-driven | WHEN `<trigger>` THE `<system>` SHALL `<response>` |
| State-driven | WHILE `<state>` THE `<system>` SHALL `<response>` |
| Unwanted behavior | IF `<condition>` THEN THE `<system>` SHALL `<response>` |
| Optional feature | WHERE `<feature is enabled>` THE `<system>` SHALL `<response>` |

System names used: **ENGINE** (process A), **WATCHER** (process B), **PIPELINE** (offline template builder), **CLI**, **SYSTEM** (when several components share the obligation).

### IDs

| Kind | Format | Example |
|---|---|---|
| Constitution clause | `CONST-<article>.<clause>` | `CONST-2.5` |
| Requirement | `<PREFIX>-R-<NNN>` | `BRAIN-R-021` |
| Acceptance criterion | `<PREFIX>-AC-<NN>` | `MOTOR-AC-01` |
| Test | `T-<PREFIX>-<L>-<NNN>`, where L = **U** unit, **V** validation, **E** emergence, **I** invariant, **P** performance, **S** soak, **M** manual | `T-WATCH-I-001` |
| Open question | `<PREFIX>-OQ-<NN>` | `WATCH-OQ-01` |

- Test levels map to `tests/{unit,validation,emergence,invariants,perf}`. Soak tests live under `perf/`, and manual checklists under `tests/manual/`.
- Each prefix is owned by exactly one spec. IDs are never reused; a removed requirement is struck through, with the reason.
- **Priority:** **M** = Must (blocks its phase gate) · **S** = Should · **C** = Could (later or optional).
- **Flags:** `ASSUMPTION` = a value or claim without a source yet (must be in the registry) · `TBD` = decided in design · `interpreted` = Watcher-side interpretation, not ground truth.
- "Proposal" in an acceptance criterion or open question means a suggested number or choice that is waiting for your decision.

### Spec file structure

Header table → Purpose → Scope (in/out) → Requirements (grouped) → Acceptance criteria → Tests → Assumptions & open questions.

---

## Phase gates → where they are specified

| Phase | Gate | Spec |
|---|---|---|
| S | You approve the specs | this folder |
| 0 | Neuron and synapse counts match published figures; checksums pass | CONN-AC-01..08 |
| 1 | Matches the Shiu/Brian2 reference (corr ≥ 0.9); RTF measured on the 4060 and 1650 | BRAIN-AC-01..09 |
| 2 | Sugar → feeding, bitter → rejection, looming → escape, plume → approach, dark + pressure → sleep | MOTOR-AC-01..07 |
| 3 | Attached ≡ detached; completeness; lossless suspend/resume | WATCH-AC-01..08, LOG-AC-01 |
| 4 | Day/night activity profile emerges; starvation and aging curves | LIFE-AC-01..08 |
| 5 | 70:30 genesis; one full unscripted courtship → adult cycle; caps hold | GENE-AC-01..06, COMM-AC-04, LIFE-AC-06 |
| 6 | Decoder calibration; LLM 100% faithful (or fallback); ≥ 95% command parsing | MIND-AC-02, LLM-AC-01 |
| 7 | Transfer invisibility; reproducible scores | TASK-AC-01..06 |
| 8 | Every §10.3 power works end to end | DASH-AC-01..03 |
| 9 | 100 flies HYBRID at ≥ 1.0 RTF on the 4060; 72 h soak | PERF-AC-01..03, FID-AC-01..02 |

## Plan → spec traceability

| Plan section | Spec(s) |
|---|---|
| §1 Reality check | 000, 002, 008, 010, 012 |
| §2 Constitution | 000 |
| §3 Architecture | 009 (processes, stream, API), 000 (import rules) |
| §4.1 Connectome templates | 001 |
| §4.2–4.4 Neurons, neuromodulation, plasticity | 002 |
| §4.5 Genome, personality | 007 (genes, presets), 010 (measured personality) |
| §4.6 Fidelity levels | 014 |
| §5.1–5.2 Dome, physics | 003 |
| §5.3 Senses | 004 |
| §5.4 Motor | 005 |
| §5.5 Physiology, life cycle | 006 (+007 sex ratio) |
| §6 Time and clocks | 009 (+006 circadian) |
| §7 Social life | 008 (+010 relationships, 006/007 babies) |
| §8 Feelings and thoughts | 010 |
| §9 Tasks | 012 |
| §10.1–10.3 Watcher | 009 |
| §10.4 Chambers, image tasks, transfers | 012 (+003 world side, 004 blink baseline) |
| §10.5 Local LLM | 013 |
| §11 `/flies` record | 011 |
| §12 Console, dashboard | 013 |
| §13 Tech stack | 001, 002, 009, 013, 014 (as constraints) |
| §14 Repo layout | this README, 001 |
| §15 Roadmap | "Phase gates" table above |
| §16 Hardware | 014 |
| §17 Risks | Spread across specs; see open questions |
| §18 Verification | Test tables in every spec |

---

## Decisions needed at review

Writing the specs exposed a few gaps and conflicts in the plan. The ones that matter most, each with a proposed answer:

> **Decision (2026-10-12):** the project owner accepted every proposal below, and every open question in specs 001–014, as proposed. Each spec's open-question table records the decision. For #11, the project is **non-commercial**; dataset terms are still verified in Phase 0.

| # | Question | Where | Proposal |
|---|---|---|---|
| 1 | **Sleep bout time base.** "≥ 5 min immobility" means either 5 *fly* minutes (12.5 s real) or 5 *neural* minutes (= 2 fly hours). | WATCH-OQ-01 | 5 fly minutes, configurable. |
| 2 | **Energy balance under the compressed clock.** A fly day's energy burns in 1 real hour, but eating happens at biological speed. | LIFE-OQ-01 | Scale ingestion rate by 86400 / D (24× by default). |
| 3 | **Egg-laying time budget.** 50–100 eggs per fly day won't fit into 1 real hour of behavior. | LIFE-OQ-02 | 10–20 eggs per fly day (`ASSUMPTION`); the caps make more unnecessary. |
| 4 | **Brain-only v1 has no VNC.** Leg taste (courtship tapping), leg touch, proprioception, the sex-peptide pathway and song/gait pattern generation all live in the nerve cord. | SENSE-OQ-01, MOTOR-OQ-01 | A documented "synthetic VNC relay" driving ascending neurons, plus VNC-level pattern generation in the motor layer. Brain outputs still decide *whether* and *what*. All flagged `ASSUMPTION`; v2 replaces it. |
| 5 | **Phase ordering.** The Phase-2 sleep gate needs sleep pressure, which the plan delivers in Phase 4. | MOTOR-OQ-04 | Bring a minimal sleep homeostat into Phase 2. |
| 6 | **Sleep transfers and open eyes.** Flies sleep with their eyes open, so moving one in daylight makes its view jump. | TASK-OQ-01 | Sleep transfers also require darkness, with lighting matched at the destination. |
| 7 | **Operational definition of "no Watcher signature".** | TASK-R-035 | Sensory-envelope check plus a neural-activity classifier at chance + 5%. |
| 8 | **Focus is an intervention.** Promoting a focused fly to FULL changes its brain model. | FID-OQ-01 | Keep it audited and tested for neutrality, and add an "observe-only focus" option. |
| 9 | **Bit-identical determinism on GPU** needs deterministic kernels, which may be slower. | BRAIN-OQ-06 | Accept up to a 20% cost. |
| 10 | **Naturalizing structural changes** (obstacles, spawned pupae, removing a fly). | WORLD-OQ-03, WATCH-OQ-03 | "Occluded placement": apply only when no awake fly can see the area, or in darkness. Removal while the fly is asleep and unseen. |
| 11 | **Data licenses.** FlyWire and MaleCNS terms, and whether this project is non-commercial. | CONN-OQ-01 | Verify in Phase 0 before any build. |
| 12 | **Branch and restore log layout.** | WATCH-OQ-02 | `timelines/<id>/…`; nothing is ever deleted. |
| 13 | **Genetics model.** One allele per gene (plan) or diploid? | GENE-OQ-01 | Keep the plan's model for v1. |
| 14 | **Emergence gate thresholds.** | MOTOR-AC-01..05 | The proposed numbers in 005 §5. |
| 15 | **First 10 tasks.** | TASK-OQ-03 | #1, #2, #6, #8, #10, #26, #27, #28, #38, #61. |

---

## Glossary

| Term | Meaning |
|---|---|
| Connectome | The complete neuron-by-neuron wiring map of a brain. |
| BrainTemplate | Our immutable, versioned package of one sex's connectome for simulation (001). |
| FAFB / FlyWire v783 | The female adult fly brain dataset (139,255 neurons). |
| MaleCNS v1.0 | The male central nervous system dataset (brain + nerve cord, ~166.7k neurons). |
| BANC | Brain And Nerve Cord dataset (v2 option). |
| VNC | Ventral nerve cord, the fly's "spinal cord". Absent from the v1 brain-only templates. |
| DN / AN / MN | Descending neuron (brain → body), ascending neuron (body → brain), motor neuron. |
| GRN / ORN | Gustatory (taste) / olfactory receptor neuron. |
| JO | Johnston's organ: antennal hearing, wind and gravity sensor. |
| MB, KC, MBON, DAN | Mushroom body (learning center), Kenyon cell, MB output neuron, dopaminergic neuron. |
| PAM / PPL1 | Dopamine clusters signalling mostly reward / punishment. |
| CX, EPG, dFB, R5 | Central complex (navigation), compass neurons, dorsal fan-shaped body and R5 ring neurons (sleep). |
| P1 / pC1 | Courtship- and aggression-related central neurons (P1 is male-specific). |
| LPLC2, Giant Fiber | Looming detector → escape pathway. |
| cVA, 7-T, 7,11-HD | Pheromones: 11-cis-vaccenyl acetate, 7-tricosene (male), 7,11-heptacosadiene (female). |
| LIF / graded | Spiking leaky integrate-and-fire neuron / non-spiking potential-based unit. |
| Neural time / life clock | Biological-speed time for brain and physics / compressed time for days, aging and physiology. |
| D | Neural seconds per fly day (default 3600 = 1 real hour). |
| RTF | Real-time factor: neural seconds simulated per wall-clock second. |
| FULL / HYBRID / COARSE | Fidelity levels (014). |
| Naturalized intervention | A world change that looks like something the world could do on its own (000). |
| Emergence gate | A behavior test driven only by sensory input, with no scripts (000). |
| Flight recorder | A rolling RAM buffer of full spike data, saved around key events (011). |

---

## Next steps after approval

1. ~~You mark decisions and approve the specs; I update the statuses and the constitution changelog.~~ Done 2026-10-12.
2. **Phase 0:** repository skeleton (the git repository already exists), then `design.md` and `tasks.md` for **001**.
3. Continue feature by feature, in roadmap order: spec approved → design → tasks → implementation → acceptance tests green.
