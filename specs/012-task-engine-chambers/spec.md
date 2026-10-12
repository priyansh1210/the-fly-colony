# 012 — Task Engine, Chambers & Transfers

| Field | Value |
|---|---|
| Status | Approved — 2026-10-12 |
| ID prefix | `TASK` |
| Phase | 7 |
| Plan refs | §1 (DSA embodied), §9 (task spec + catalog of 70), §10.4 (chambers, image tasks, transfers) |
| Depends on | 003 (chamber worlds, occluded placement), 004 (vision, neutral baseline), 009 (Control API), 010 (behavior, trials), 011 (attempt logs) |
| Used by | 013 (puzzle builder, scores, fly-eye view) |
| Constitution | CONST-1 (incentives only through the world), CONST-2.4 and 2.6 (naturalized, signature-free transfers), CONST-7.3 (failure is a valid result) |

## 1. Purpose

Give flies problems to solve without teaching them anything directly. Tasks are **physical places** (mazes, arenas, image panoramas) with **natural incentives** (sugar, a cool spot, heat, bitter). The Watcher moves flies in without being noticed, computes the true optimum with a real algorithm, and scores the fly against it.

## 2. Scope

**In scope:** the task spec schema; the world/Watcher split; chamber types and the maze compiler; the image arena; sleep and blink transfers and the invisibility test; trial segmentation; optimal solvers; metrics and scores; assignment, schedules, eligibility, max duration and auto-return; leaderboards; the starter catalog of 70 tasks.

**Out of scope:** the puzzle-builder UI (013); world physics (003).

## 3. Requirements

### 3.1 Task specs

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| TASK-R-001 | M | A task SHALL be defined in YAML with: `id`, `name`, `category` (A–G), `dsa_analog`, `chamber` (reference) or `dome_arrangement`, `layout` (graph or geometry), `incentives`, `schedule`/`trigger`, `eligibility`, `success_criterion`, `metrics`, `difficulty_levels` (parameterized), `randomization` (seeded), `max_duration`, `return_policy`, `trial_reset` (naturalized methods only). | T-TASK-U-001 |
| TASK-R-002 | M | Incentives SHALL be physical world elements sensed through the senses (sugar, water, a cool spot, heat, bitter). No reward or punishment signal ever goes directly into a brain. | T-TASK-I-002, review |
| TASK-R-003 | M | Task specs SHALL be validated when loaded. An invalid spec is rejected with the reasons. | T-TASK-U-001 |
| TASK-R-004 | M | The world-side part (chamber instantiation, incentives, triggers) SHALL run in the engine. The scoring part (trial segmentation, solvers, metrics) SHALL run in the Watcher. Scoring affects the world only through audited, naturalized Watcher commands (e.g. rearranging for the next trial). | T-WATCH-I-006 |
| TASK-R-005 | M | Trial resets SHALL use only naturalized methods declared in the spec: food regrowing in place, a blink transfer back to the start, or letting the fly walk back on its own. | T-TASK-U-002 |

### 3.2 Chambers

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| TASK-R-010 | M | Supported chamber types SHALL include: graph mazes (nodes = junctions or rooms; edges = corridors with length, width and a cost terrain such as warm, rough or uphill), T-mazes and Y-mazes, radial mazes, heat-place arenas, odor arenas (odor ports), social arenas (2 or more flies), image arenas, and special motor-skill rigs (gaps, walls, gates, bridges, a swinging fruit). The dome's Challenge Grounds host voluntary versions. | T-TASK-U-003 |
| TASK-R-011 | M | THE SYSTEM SHALL compile a maze graph deterministically into geometry that preserves its topology and edge costs. The solver runs on the same graph. | T-TASK-U-004 |
| TASK-R-012 | M | Chambers SHALL support create, edit (only when empty), instantiate and destroy, and SHALL be saved in checkpoints. | T-TASK-U-003 |

### 3.3 Image arena

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| TASK-R-020 | M | An image arena SHALL be a cylindrical panorama (configurable radius, height and elevation coverage) textured from an uploaded image or video. Each fly sees it through normal raycasting, at about 5° per ommatidium. | T-TASK-U-005 |
| TASK-R-021 | M | Image colors SHALL be converted to photoreceptor spectral channels (UV, blue, green) by a documented mapping (`ASSUMPTION`), with a calibrated luminance range. | T-TASK-U-005 |
| TASK-R-022 | M | Video SHALL play with frame timing in neural time, up to the vision render rate (100 Hz). | T-TASK-U-005 |
| TASK-R-023 | M | The fly-eye preview (SENSE-R-015) SHALL show exactly the sampled photoreceptor input for a chosen fly and pose. | T-SENSE-U-003 |
| TASK-R-024 | M | Modes: **free viewing** (log neural responses); **preference** (time oriented toward or near image regions); **discrimination learning** (image A over a cool/sugar zone, image B over a heat zone); **motion / optic flow** (rotating gratings, looming). | T-TASK-U-006 |
| TASK-R-025 | S | A closed-loop panorama mode (panorama rotation coupled to the fly's turning) MAY be offered for flight-simulator-style tasks. | — |

### 3.4 Transfers (§10.4)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| TASK-R-030 | M | THE WATCHER SHALL support `transfer <fly> --to <chamber or dome location> --mode sleep\|blink`, including return trips. | T-TASK-U-007 |
| TASK-R-031 | M | **Sleep transfer (default):** the fly is moved only while it is in the engine sleep state, while its visual input is dark (night, or a dimmed chamber phase), and while no awake fly can see it at the source (WORLD-R-071). The destination's light matches the source's light at the moment of transfer, so waking there brings no sudden illumination change. | T-TASK-U-007 |
| TASK-R-032 | M | **Blink transfer:** the fly's senses are rendered from the neutral baseline (SENSE-R-070) for the registry blink duration (~200 ms), and the move happens in the middle of the blink. The source-side occlusion rule still applies. | T-TASK-U-007 |
| TASK-R-033 | M | IF a sleep transfer cannot be carried out within the configured wait (default 1 fly day) THEN THE WATCHER SHALL report it and ask whether to use a blink transfer. | T-TASK-U-007 |
| TASK-R-034 | M | A fly's physiology SHALL keep running during and after a transfer. Chambers provide water unless the task explicitly tests thirst. | T-LIFE-U-001 |
| TASK-R-035 | M | **Transfer invisibility test:** (a) every sensory input during and after a transfer stays within the envelope of naturally occurring inputs for that channel; and (b) a classifier trained on the transferred fly's neural activity cannot tell transfers apart from matched natural events (e.g. dusk, passing shadows) better than chance + ε (proposal ε = 5%, n ≥ 200 events per class). | T-TASK-I-001 |
| TASK-R-036 | M | No other fly SHALL ever see a fly vanish or appear (source- and destination-side occlusion). | T-TASK-I-001 |

### 3.5 Scoring

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| TASK-R-040 | M | THE WATCHER SHALL compute the optimum with the exact algorithm for each analog: BFS (unweighted shortest path); Dijkstra (weighted); DFS / tree traversal; exact TSP (Held–Karp for ≤ 12 nodes, otherwise best known with a bound); bandit oracle (best expected arm and regret); connected components; the marginal-value-theorem optimum; and others as listed in the catalog. | T-TASK-U-008 |
| TASK-R-041 | M | Metrics SHALL include: path efficiency (optimal ÷ actual cost), trials to criterion, errors (task-specific, e.g. revisits, wrong arms, dead-end entries), latency (first move, reaching the goal), plus task-specific metrics. | T-TASK-U-009 |
| TASK-R-042 | M | THE WATCHER SHALL segment trials from positions and world events: leaving the start zone, reaching the goal, timeout. | T-TASK-U-009 |
| TASK-R-043 | M | Scores SHALL be reproducible: the same logs always give the same scores. The scorer version is recorded. | T-TASK-I-003 |
| TASK-R-044 | M | Every attempt SHALL be logged to the fly's `tasks/attempts.jsonl` (task, difficulty, trial index, metrics, optimum, score, evidence) with a readable summary line, e.g. "F0012 solved Dijkstra-maze L3 at 87% efficiency after 6 trials." | T-LOG-U-004 |
| TASK-R-045 | M | THE WATCHER SHALL keep leaderboards per task and difficulty. | T-TASK-U-010 |
| TASK-R-046 | M | Failures and timeouts SHALL be recorded as valid results (CONST-7.3). | T-TASK-U-009 |

### 3.6 Assignment and scheduling

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| TASK-R-050 | M | A task SHALL be assignable either by transfer, or by **dome arrangement**: placing the puzzle where the fly will meet it (e.g. near its favorite perch, chosen from Watcher position statistics), using occluded placement. | T-TASK-U-011 |
| TASK-R-051 | M | Triggers SHALL support fly time of day (e.g. time-place learning at a fixed fly hour) and Watcher-observed conditions (e.g. "when F0012 is hungry"). | T-TASK-U-011 |
| TASK-R-052 | M | Eligibility (sex, adult stage, minimum age, health thresholds, fidelity) SHALL be checked before assignment. | T-TASK-U-011 |
| TASK-R-053 | M | WHEN `max_duration` is reached THE WATCHER SHALL schedule a return according to `return_policy` (by default, a sleep transfer at the next opportunity). | T-TASK-U-011 |
| TASK-R-054 | M | Punishments SHALL stay within safe registry bounds (e.g. a maximum non-lethal heat). | T-TASK-U-001 |

### 3.7 Rollout

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| TASK-R-060 | M | The first 10 tasks SHALL be implemented and gated before the rest. Proposal: #1, #2, #6, #8, #10, #26, #27, #28, #38, #61. Then all 70. | T-TASK-E-001 |

## 4. Starter catalog (70 tasks)

| # | Task | DSA / cognitive analog | Where | Primary metrics |
|---|---|---|---|---|
| **A** | **Graph & search** | | | |
| 1 | T-maze choice | binary decision | T-maze | accuracy, latency |
| 2 | Y-maze spontaneous alternation | visited-set (size 1) | Y-maze | alternation rate |
| 3 | Dead-end corridor | backtracking | corridor | time to reverse |
| 4 | Depth-3 tree maze | DFS | tree maze | nodes visited vs DFS, revisits |
| 5 | Grid maze | path finding | grid maze | efficiency vs BFS |
| 6 | Multi-route maze | shortest path (BFS) | graph maze | efficiency, trials to criterion |
| 7 | Terrain-cost routes | Dijkstra | weighted maze | cost efficiency vs Dijkstra |
| 8 | 8-arm radial maze | visited-set memory | radial maze | revisit errors |
| 9 | Detour around a transparent barrier | constrained planning | barrier arena | detour latency, success |
| 10 | Odor gradient ascent | greedy local search | odor arena | efficiency vs gradient path |
| 11 | Sequential halving corridor | binary-search analog | halving corridor | steps vs log₂ n |
| 12 | 5-patch foraging tour | TSP | patch arena / dome | tour length vs Held–Karp |
| 13 | Novel-arena coverage | graph traversal / coverage | open arena | coverage over time |
| 14 | Shifting-wall maze | dynamic re-planning | dynamic maze | re-plan latency, efficiency after shift |
| 15 | Loop-trap maze | cycle detection and escape | loop maze | loops before escape |
| 16 | Which enclosure has the exit | connected components | multi-enclosure | time to the exit component |
| 17 | Sweetness-ordered visits | sorting / sequence | 3–5 patches | rank correlation |
| 18 | Nested dead-ends, reverse return | stack / LIFO | nested corridor | return-order correctness |
| 19 | Regenerating patches, depletion order | queue / FIFO | patch ring | order vs regeneration |
| 20 | Near-small vs far-large reward | greedy vs optimal | two-patch arena | reward rate vs optimum |
| **B** | **Loops & rhythms** | | | |
| 21 | Patrol ring, ordered checkpoints | cyclic traversal | ring track | ordered laps |
| 22 | Figure-8 route | cyclic path | figure-8 track | route fidelity |
| 23 | Time-place learning | timers / scheduling | dome or arena | anticipatory arrival |
| 24 | Orbit a landmark | fixation / circular path | landmark arena | orbits, radius stability |
| 25 | Return home to a perch | path integration | dome | homing error, efficiency |
| **C** | **Learning & memory** | | | |
| 26 | Odor + heat aversive conditioning | association | odor arena, heat floor | performance index (PI) |
| 27 | Odor + sugar appetitive conditioning | association | odor arena | PI |
| 28 | Visual pattern learning | classification | image arena | preference index |
| 29 | Color learning | classification | image arena | preference index |
| 30 | Visual place learning (heat maze) | spatial memory | heat-place arena | latency to cool spot over trials |
| 31 | Reversal learning | overwrite / update | as 26/27 | trials to re-criterion |
| 32 | Extinction | forgetting | as 27 | PI decay |
| 33 | Second-order conditioning | transitive association | odor arena | PI to CS2 |
| 34 | Trace conditioning | delayed association | odor arena | PI vs trace gap |
| 35 | LTM retest after 1 and 3 fly days | persistence | as 26/27 | retained PI |
| 36 | Context-dependent memory | conditional lookup | two contexts | PI by context |
| 37 | Novelty preference / latent inhibition | novelty detection | odor arena | preference, learning deficit |
| **D** | **Decisions** | | | |
| 38 | Multi-armed bandit | explore / exploit | 3–5 arms | regret vs oracle |
| 39 | Patch-leaving | marginal value theorem | depleting patches | leave time vs MVT |
| 40 | Risk: constant vs variable reward | risk sensitivity | two patches | choice proportion |
| 41 | Tasty odor + bitter food | multi-objective | arena | approach vs ingestion |
| 42 | Speed–accuracy (decaying food) | time-limited search | arena | reward vs latency |
| 43 | Delay discounting | scheduling | delay arena | choice vs delay |
| 44 | Egg-laying site choice (♀) | weighted choice | substrate arena | eggs per substrate |
| 45 | Satiety-dependent choice | state-dependent policy | two foods | choice by satiety |
| **E** | **Social** | | | |
| 46 | Male finds and courts a receptive female | search + signalling | social arena | latency to court, copulation |
| 47 | Female mate choice by song quality | ranking | social arena (2 ♂) | chosen male vs song |
| 48 | Mate copying | social learning | social arena | preference shift |
| 49 | Hold a food territory | resource defense | food arena | occupancy, fights won |
| 50 | Dominance hierarchy | ranking from pairwise comparisons | group arena | linearity index |
| 51 | Social learning of egg-laying sites | information transfer | substrate arena | site-choice shift |
| 52 | cVA aggregation | pheromone grouping | dome | aggregation index |
| 53 | Collective escape from a looming shadow | broadcast propagation | dome | escape cascade latency |
| 54 | Group foraging efficiency | parallel search | dome | food found per fly hour vs solo |
| 55 | Isolation then reintroduction | state change | isolation → dome | change in social metrics |
| 56 | Courtship conditioning | learning from rejection | social arena | courtship index drop |
| 57 | Scramble competition | contention | limited food | share vs traits |
| **F** | **Survival** | | | |
| 58 | Find water in a drought | constrained search | dome | time to water |
| 59 | Food scarcity | scarce foraging | dome | intake, survival |
| 60 | Predator-shadow avoidance | threat learning | shadow arena | escape rate, zone avoidance |
| 61 | Find preferred temperature (~25 °C) | gradient optimization | thermal gradient | time near 25 °C |
| 62 | Plume tracking (surge / cast) | intermittent-signal search | wind arena | success, efficiency |
| 63 | Reach a shelter perch before dark | deadline scheduling | dome | arrival before dusk |
| 64 | Avoid toxic food | learned avoidance | arena | toxic intake |
| 65 | Light / gravity orientation | taxis | vertical arena | photo- and geotaxis index |
| **G** | **Motor skills** | | | |
| 66 | Gap crossing | motor learning | gap rig | success over attempts |
| 67 | Climbing wall | locomotion | wall rig | success, speed |
| 68 | Flying through gates (slalom) | flight control | gate rig | gates passed, collisions |
| 69 | Narrow bridge / rough terrain | balance | bridge rig | falls, speed |
| 70 | Landing on a swinging fruit | moving-target landing | swing rig | landing success |

## 5. Acceptance criteria (Phase 7 gate)

| ID | Criterion |
|---|---|
| TASK-AC-01 | The transfer invisibility test passes for both sleep and blink modes. |
| TASK-AC-02 | Scores are reproducible from logs. |
| TASK-AC-03 | Solver unit tests match known optima; compiled mazes preserve topology and costs. |
| TASK-AC-04 | The image arena preview equals the sampled input; uploaded images and videos render in the arena. |
| TASK-AC-05 | The first 10 tasks run end to end (assign → attempts → scores → leaderboard). Success rates are reported honestly, whatever they are. |
| TASK-AC-06 | All 70 task specs validate, and each has at least one runnable difficulty level. |

## 6. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-TASK-U-001 | unit | Spec schema, validation, safety bounds. |
| T-TASK-U-002 | unit | Naturalized trial resets. |
| T-TASK-U-003 | unit | Chamber types and lifecycle. |
| T-TASK-U-004 | unit | Maze compiler preserves topology and costs. |
| T-TASK-U-005 | unit | Image arena mapping and video timing. |
| T-TASK-U-006 | unit | Image arena modes. |
| T-TASK-U-007 | unit | Transfer modes, preconditions, fallback. |
| T-TASK-U-008 | unit | Solvers against known optima. |
| T-TASK-U-009 | unit | Trial segmentation, metrics, failure recording. |
| T-TASK-U-010 | unit | Leaderboards. |
| T-TASK-U-011 | unit | Assignment, triggers, eligibility, auto-return. |
| T-TASK-I-001 | invariant | Transfer invisibility (envelope + classifier + occlusion). |
| T-TASK-I-002 | invariant | No direct reward path into brains (static audit). |
| T-TASK-I-003 | invariant | Score reproducibility. |
| T-TASK-E-001 | emergence | First-10 task runs (reported, not required to succeed). |

## 7. Assumptions and open questions

| ID | Question | Proposal | Decision |
|---|---|---|---|
| TASK-OQ-01 | **Sleep transfers and vision.** Flies sleep with their eyes open, so moving a sleeping fly in daylight would make its scene jump. | Require darkness as well (R-031), and match the lighting between source and destination. | Accepted (proposal), 2026-10-12 |
| TASK-OQ-02 | Invisibility threshold ε and sample size. | ε = 5%, n ≥ 200 per class. | Accepted (proposal), 2026-10-12 |
| TASK-OQ-03 | Which first 10 tasks? | #1, #2, #6, #8, #10, #26, #27, #28, #38, #61 (covers graph search, memory, learning, vision, decisions, survival). | Accepted (proposal), 2026-10-12 |
| TASK-OQ-04 | Are blink transfers back to the start acceptable as a trial reset? | Yes for chamber tasks. In the dome, only voluntary re-attempts. | Accepted (proposal), 2026-10-12 |
| TASK-OQ-05 | How to convert RGB images to fly photoreceptor channels. | Documented approximation. UV has no RGB source, so it is set to a fixed ambient level unless the image supplies a UV layer. | Accepted (proposal), 2026-10-12 |
| TASK-OQ-06 | Do chambers provide water and food by default? | Water yes; food only when part of the task. | Accepted (proposal), 2026-10-12 |
