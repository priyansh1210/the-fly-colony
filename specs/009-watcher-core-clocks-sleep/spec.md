# 009 — Watcher Core, Clocks & Sleep

| Field | Value |
|---|---|
| Status | Approved — 2026-10-12 |
| ID prefixes | `CLOCK` (time), `WATCH` (Watcher core, Control API, sleep, checkpoints) |
| Phase | 3 (Watcher core). The clock core is needed from Phase 2; checkpoints and branches are hardened in Phase 9. |
| Plan refs | §3, §6, §10.1, §10.2, §10.3, §17, §18 (invariants) |
| Depends on | 000, 002, 003 |
| Used by | Every other spec |
| Constitution | CONST-2 (invisibility), CONST-3 (observability), CONST-4 (chain of command), CONST-5 (reproducibility) |

## 1. Purpose

Build the Watcher's skeleton and the time system it controls:
- the **clocks** (neural time, life clock, three timestamps);
- the one-way **Observation Stream**;
- the **Environment Control API** (the only way to change the world) with naturalization and audit;
- the Watcher's **awake/asleep** cycle, during which the world is suspended;
- **checkpoints, restores and branches**;
- crash and disk safety.

## 2. Scope

**In scope:** clock math and pacing; process layout; the stream and backpressure; the Control API schema and command catalog; the naturalization catalog; audit; the Watcher state machine and schedules; checkpoints and timelines; the Watcher journal; resilience; the invisibility invariants.

**Out of scope:** what observers compute (008, 010, 012); what writers produce (011); user interfaces (013).

## 3. Clocks

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| CLOCK-R-001 | M | Neural time SHALL advance only by engine steps (integer tick count × dt), never by wall-clock time. | T-CLOCK-U-001 |
| CLOCK-R-002 | M | A pacer SHALL keep neural time ≈ `sim_speed` × awake wall time (default 1.0). The pacer only delays; it never skips or alters steps. | T-CLOCK-U-001 |
| CLOCK-R-003 | M | The life clock SHALL be integrated every step as `Δlife = Δneural × 86400 / D(t)`, where D is neural seconds per fly day (default 3600). It stays continuous when D changes live. D's valid range is in the registry. | T-CLOCK-U-002 |
| CLOCK-R-004 | M | Timestamps: `sim_ts` = neural seconds since genesis (tick-exact); `fly_ts` = "Day N, HH:MM:SS" with genesis at Day 1, 06:00:00; `real_ts` = ISO-8601 wall clock with UTC offset. | T-CLOCK-U-003 |
| CLOCK-R-005 | M | WHEN D or `sim_speed` is changed THE ENGINE SHALL apply the change at the next step boundary, and the change is audited. | T-CLOCK-U-002 |
| CLOCK-R-006 | M | THE WATCHER SHALL continuously report the measured real minutes per fly day and the RTF. | T-CLOCK-U-004 |
| CLOCK-R-007 | M | WHILE the engine is suspended, neural time and the life clock SHALL be frozen. | T-WATCH-I-005 |
| CLOCK-R-008 | M | IF the hardware runs slower than the target speed THEN fly days SHALL stretch in wall time; no step is skipped and no rate is changed. | T-CLOCK-U-004 |
| CLOCK-R-009 | M | WHERE `sim_speed` > 1 is requested, THE ENGINE SHALL run as fast as possible up to that speed and report the speed it actually achieved. | T-CLOCK-U-004 |
| CLOCK-R-010 | M | Every life-clock process SHALL read time from the single clock service; modules may not keep their own time. | review, T-CLOCK-U-002 |

Worked defaults: 1 fly day = 3600 s real; 1 fly hour = 150 s; 1 fly minute = 2.5 s.

## 4. Architecture and the Observation Stream

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WATCH-R-001 | M | The Engine (process A, GPU, WSL2), the Watcher (B, CPU) and the LLM server (C, CPU) SHALL run as separate processes. | review |
| WATCH-R-002 | M | The Observation Stream SHALL be a one-way shared-memory ring buffer (pyzmq fallback) with a versioned schema. The Engine writes, the Watcher reads. The only data flowing back is the reader cursor, used for backpressure. | T-WATCH-U-001 |
| WATCH-R-003 | M | IF the buffer is full because the Watcher has not consumed it THEN THE ENGINE SHALL block before overwriting. Blocking changes only wall-clock timing. | T-WATCH-I-002 |
| WATCH-R-004 | M | THE ENGINE SHALL advance only while a Watcher is attached. The single exception is a test-only "detached" mode that records the stream to disk for comparison (CONST-2.5). | T-WATCH-I-002 |
| WATCH-R-005 | M | The Watcher SHALL host these observers: behavior classifier and mind decoder (010), translator (008), task scorer (012), narrator, chronicle and writers (011), controller and scheduler (this spec). | review |
| WATCH-R-006 | M | `import-linter` contracts: engine packages SHALL NOT import `watcher`, `console`, `tasks.scoring` or any LLM client. The Watcher SHALL import from the engine only the Observation Stream and Control API schemas. | T-WATCH-I-006 |

## 5. Environment Control API

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WATCH-R-010 | M | THE SYSTEM SHALL define a typed command schema (pydantic, exported as JSON Schema) grouped as: `time`, `watcher`, `env`, `life`, `task`, `timeline`, `query` (read-only). | T-WATCH-U-002 |
| WATCH-R-011 | M | The schema SHALL have no field type that can refer to a neuron, synapse, trace or any internal brain state. Commands address only: world entities (zones, patches, vents, chambers), whole flies as bodies (transfer, remove), genomes at creation (genesis, spawn), and global parameters (caps, mutation rate, sex-ratio mode, D, sim_speed). | T-WATCH-I-003 |
| WATCH-R-012 | M | THE WATCHER SHALL validate every command (schema, bounds, current state) before applying it. An invalid command is rejected with a reason, and nothing is partially applied. | T-WATCH-U-003 |
| WATCH-R-013 | M | Commands SHALL take effect at step boundaries at a recorded tick. The **command log** (tick, command) is part of the run. Replaying the log from the same checkpoint reproduces the run bit-identically. | T-WATCH-I-001 |
| WATCH-R-014 | M | Each command type SHALL declare its naturalization method and parameters (§6), and the engine applies it (WORLD-R-070/071). | T-WATCH-U-004 |
| WATCH-R-015 | M | Destructive or large commands SHALL need explicit confirmation. The list is configurable; by default: remove fly, restore, genesis over an existing colony, spawn > 20, caps below the current population, and large sudden environment changes. | T-WATCH-U-005 |
| WATCH-R-016 | M | THE WATCHER SHALL append every command, accepted or rejected, to `watcher/interventions.jsonl` with: three timestamps, source (cli / dashboard / chat-llm / schedule / policy), raw input (for chat: the natural-language text and the parsed command), the validated command, confirmation, applied tick, naturalization used, and outcome. | T-WATCH-U-006 |

Command catalog (from plan §10.3; field details go in design):

| Group | Commands |
|---|---|
| time | `set_fly_day(D)`, `set_speed`, `pause`, `resume` |
| watcher | `sleep [now]`, `wake`, `schedule`, `verbosity`, `focus <fly>`, `narration_style` |
| env | `light` (schedule, day length, season), `temperature`, `humidity`, `wind`, `food` (add / remove / type / amount / scarcity), `water`, `obstacle`, `zone`, `threat_shadow` |
| life | `genesis`, `spawn`, `caps`, `egg_viability`, `mutation_rate`, `sex_ratio_mode`, `remove <fly>` |
| task | `chamber create/edit/delete`, `assign`, `transfer`, `difficulty` (details in 012) |
| timeline | `checkpoint`, `restore`, `branch`, `list` |
| query | read-only questions over the logs (served by 011/013) |

## 6. Naturalization catalog

| Command | Naturalization method |
|---|---|
| light, temperature, humidity, wind | Gradual ramp, no shorter than the registry minimum |
| add food | Ripens in place from a small, low-odor state |
| remove food | Accelerated rot/depletion, or occluded removal |
| water | Spring flow ramps up or down |
| obstacle / zone add or remove | Occluded placement (WORLD-R-071) or darkness |
| spawn adult | Late-stage pupa placed by the occluded rule, then ecloses |
| spawn egg / larva / pupa | Occluded placement in the nursery |
| remove fly | Occluded removal while the fly is asleep (WATCH-OQ-03) |
| transfer | Sleep or blink transfer (012) |
| threat shadow | A natural sky event |
| D, sim_speed, caps, mutation rate, sex-ratio mode | No perceptual correlate (global rates) |
| focus (fidelity promotion) | Audited; tested to be behaviorally neutral (FID-R-012) |

## 7. Watcher awake/asleep cycle

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WATCH-R-020 | M | THE WATCHER SHALL move through the states AWAKE → GOING_TO_SLEEP → ASLEEP → WAKING → AWAKE. | T-WATCH-U-007 |
| WATCH-R-021 | M | WHEN `watcher sleep` is issued (default mode) THE WATCHER SHALL enter GOING_TO_SLEEP and wait until it is fly-night and ≥ 95% of adults are classified asleep, or until 1 fly day has passed. It then checkpoints and suspends the engine. | T-WATCH-U-007 |
| WATCH-R-022 | M | WHEN `watcher sleep now` is issued THE WATCHER SHALL checkpoint and suspend at the next step boundary. | T-WATCH-U-007 |
| WATCH-R-023 | M | WHILE ASLEEP the engine SHALL be suspended: no steps, clocks frozen, no events. | T-WATCH-I-005 |
| WATCH-R-024 | M | WHEN woken THE WATCHER SHALL resume from the exact suspended state (from memory, or from the checkpoint after a restart), so the world continues its night toward dawn. To the flies it is one seamless night. | T-WATCH-I-005 |
| WATCH-R-025 | M | Supported schedules: manual; a fixed real-world schedule (e.g. 23:00–07:00 local); tied to PC sleep (OS suspend or shutdown notices trigger `sleep now`, and the wall-clock gap is logged as Watcher sleep, not as lag). | T-WATCH-U-008 |
| WATCH-R-026 | M | Every transition SHALL be written to `watcher/sleep-log.jsonl` with three timestamps. | T-WATCH-U-007 |
| WATCH-R-027 | S | The asleep-fraction threshold (95%) and the maximum wait (1 fly day) SHALL be configurable. | T-WATCH-U-007 |

## 8. Checkpoints and timelines

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WATCH-R-030 | M | A checkpoint SHALL hold the complete engine state (brains, bodies, world, physiology, clocks, RNG states, pending commands, command-log position), the config snapshot, the registry and template versions, and the Watcher's own derived state (e.g. relationship accumulators, decoder states), so both sides resume consistently. | T-WATCH-I-004 |
| WATCH-R-031 | M | Automatic checkpoints SHALL be taken on Watcher sleep, every N fly hours (default 6), on a `brain.runaway` event, and before any destructive command. | T-WATCH-U-009 |
| WATCH-R-032 | M | `restore` SHALL resume from a checkpoint on the same timeline. Logs written after the restore point are **moved** to an archived timeline folder, never deleted (CONST-5.4). | T-WATCH-U-010 |
| WATCH-R-033 | M | `branch` SHALL create a new timeline id from a checkpoint. Branch logs go to `timelines/<timeline-id>/flies/` and `.../watcher/`; the main timeline keeps `flies/` and `watcher/`. | T-WATCH-U-010 |
| WATCH-R-034 | M | Checkpoints SHALL be checksummed, and a restore verifies the checksum first. | T-WATCH-I-004 |
| WATCH-R-035 | M | Suspend → resume and checkpoint → restore SHALL be lossless: the continuation is bit-identical to an uninterrupted run. | T-WATCH-I-004, T-WATCH-I-005 |
| WATCH-R-036 | S | Retention SHALL keep the last K automatic checkpoints plus every manual and branch-origin checkpoint. | T-WATCH-U-009 |

## 9. Journal, alerts and resilience

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WATCH-R-040 | M | THE WATCHER SHALL keep `watcher/journal/day-NNNN.md`: awake and asleep periods, interventions, alerts (runaway, disk, lag, crashes), decoder and translator version changes. | T-WATCH-U-011 |
| WATCH-R-041 | M | Alerts SHALL be shown in the CLI and the dashboard. | T-DASH-M-001 |
| WATCH-R-042 | M | IF the Watcher crashes THEN the engine SHALL stay blocked (R-003). A restarted Watcher reconnects and continues from its last consumed record with no loss. | T-WATCH-I-007 |
| WATCH-R-043 | M | IF the engine crashes THEN it SHALL restart from the last checkpoint and replay the command log. Event IDs are deterministic (LOG-R-003), so replayed records are written idempotently, without duplicates. | T-WATCH-I-007 |
| WATCH-R-044 | M | IF free space on the `/flies` volume falls below the warning threshold (default 20 GB) THEN THE WATCHER SHALL raise an alert. Below the critical threshold (default 5 GB) it SHALL `sleep now`. | T-WATCH-U-012 |

## 10. Invisibility invariant

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WATCH-R-050 | M | From the same checkpoint and command log, a 2-fly-day run with the Watcher attached (all observers on) and a run detached (test null consumer) SHALL produce identical final state hashes and identical engine event streams. | T-WATCH-I-001 |

## 11. Acceptance criteria (Phase 3 gate)

| ID | Criterion |
|---|---|
| WATCH-AC-01 | Watcher-attached ≡ detached over 2 fly days (bit-identical). |
| WATCH-AC-02 | Log completeness holds (with 011). |
| WATCH-AC-03 | Suspend/resume is lossless, and the clocks are frozen while asleep. |
| WATCH-AC-04 | A command that tries to address brain state cannot be expressed (schema fuzzing finds none). |
| WATCH-AC-05 | Every command appears in the audit log with all required fields. |
| WATCH-AC-06 | Changing D mid-run keeps the life clock continuous, and the day/night cycle adapts. |
| WATCH-AC-07 | Killing the Watcher mid-run blocks the engine; restarting it continues with no gap. |
| WATCH-AC-08 | Restore archives the abandoned logs; a branch writes to its own timeline folder. |

## 12. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-CLOCK-U-001..004 | unit | Tick time and pacer; life-clock integration under D changes; timestamp formats; RTF and minutes-per-day reporting. |
| T-WATCH-U-001..012 | unit | Stream; schema; validation; naturalization dispatch; confirmation; audit; state machine; schedules; auto-checkpoints; restore and branch layout; journal; disk guard. |
| T-WATCH-I-001 | invariant | Attached ≡ detached (CONST-2.5); command-log replay. |
| T-WATCH-I-002 | invariant | Backpressure; no run without a Watcher. |
| T-WATCH-I-003 | invariant | Schema cannot address brain state (fuzzing + static check). |
| T-WATCH-I-004 | invariant | Checkpoint completeness, checksums, lossless restore. |
| T-WATCH-I-005 | invariant | Suspend freezes everything; resume is lossless. |
| T-WATCH-I-006 | invariant | `import-linter` contracts. |
| T-WATCH-I-007 | invariant | Crash recovery with no loss or duplicates. |

## 13. Assumptions and open questions

| ID | Question | Proposal | Decision |
|---|---|---|---|
| WATCH-OQ-01 | **Sleep bout time base.** The standard definition of fly sleep is "≥ 5 min immobility". Under compression, is that 5 fly minutes (12.5 s neural) or 5 neural minutes (= 2 fly hours)? | **5 fly minutes (life-clock time)**, so sleep amounts compare with real fly data per fly day; configurable. Used by 005, 006 and 010. | Accepted (proposal), 2026-10-12 |
| WATCH-OQ-02 | Layout for restore archives and branches. | As in R-032/033 (`timelines/<id>/…`); please confirm. | Accepted: `timelines/<id>/…`, nothing deleted. 2026-10-12. |
| WATCH-OQ-03 | How to "naturalize" removing a fly. | Remove while it is asleep and no awake fly can see it; other flies find it simply gone. The alternative is a natural death (a corpse remains). Which do you prefer? | Accepted (proposal), 2026-10-12 |
| WATCH-OQ-04 | PC-sleep integration with Windows + WSL2. | A Windows-side helper listens for power events and signals the Watcher. Even without it, a PC sleep freezes every process, so nothing happens unobserved. | Accepted (proposal), 2026-10-12 |
| WATCH-OQ-05 | Allow a headless engine run with no Watcher (e.g. benchmarks)? | Only in test/benchmark mode, never on a colony timeline (CONST-3.2). | Accepted (proposal), 2026-10-12 |
