# 005 — Motor: Tasks

| Field | Value |
|---|---|
| Status | Phase 2 in progress |
| Design | [design.md](design.md) |

## Phase 2

- [x] **M1** Primitive table and resolution per template. *MOTOR-R-001, -008* · T-MOTOR-U-001
- [x] **M2** Readout: transfer, latency, ballistic jump trigger, constraints, superposition. *MOTOR-R-001..003, -009* · T-MOTOR-U-001, -002, T-MOTOR-I-001
- [x] **M3** Unmapped DNs published, inert; observation output. *MOTOR-R-004, -010* · T-MOTOR-U-003
- [x] **M4** Effort reporting. *MOTOR-R-007* · T-MOTOR-U-005
- [x] **M5** Minimal physiology: energy, ingestion, sleep pressure, engine sleep state (006 design). *LIFE-R-010, -011, -030; BRAIN-R-045*
- [x] **M6** Closed loop (`engine/loop.py`): brain ↔ senses ↔ motor ↔ body ↔ world on the schedule; checkpoint of the whole loop.
- [ ] **M7** Open-loop harness (tests only) and its isolation. *MOTOR-R-011, -012* · T-MOTOR-V-001, T-MOTOR-I-002, MOTOR-AC-06
- [ ] **M8** Global calibration of transfer thresholds against spontaneous activity (report).
- [ ] **M9** Emergence suite: protocols, statistics, reports, `colony gates run`. *MOTOR-R-020, -021* · T-MOTOR-E-001..005, MOTOR-AC-01..05, -07
- [ ] **M10** Phase-2 gate: all gates run and reported; timestep gate re-run with the emergence assays (002 G7).

## Later phases

- [ ] **L1** Song synthesis; courtship, copulation, female acceptance and rejection primitives. *MOTOR-R-005, -006* (Phase 5)
- [ ] **L2** Flight steering primitives once mapped. *MOTOR-OQ-02*
