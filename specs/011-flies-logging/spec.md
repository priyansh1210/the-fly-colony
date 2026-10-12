# 011 — The `/flies` Record (logging)

| Field | Value |
|---|---|
| Status | Approved — 2026-10-12 |
| ID prefix | `LOG` |
| Phase | 3 (writers, completeness). Later phases add content (mind, speech, tasks, LLM prose). |
| Plan refs | §11, §3 (Watcher writes), §17 (log volume), §18 (completeness) |
| Depends on | 009 (stream, clocks, timelines), 010, 008, 012 |
| Used by | 013 (dashboard, Q&A, diaries), you (reading diaries) |
| Constitution | CONST-3 (total observability), CONST-5.4 (never delete), CONST-7 (interpreted flags) |

## 1. Purpose

Define exactly what the Watcher writes, where, in what format, and with what guarantees. The goal is a **complete**, timestamped, human-readable and machine-queryable record of every fly's life, while keeping the volume feasible for weeks of running on D:.

## 2. Scope

**In scope:** the folder layout; common record fields; the event taxonomy; per-file formats; day rollover; event IDs; write guarantees and crash consistency; the completeness test; volume, compression and retention; the flight recorder and focus recordings; roster, profiles, diaries and the chronicle (template narrator); colony-level files; the Watcher folder; the query layer.

**Out of scope:** how facts are derived (008, 010, 012); LLM prose (013 adds it on top of templates).

## 3. Layout

```
flies/
  README.md                     roster: id, name, sex, stage, age, parents, status, preset, measured personality
  _colony/
    chronicle/day-0001.md       births, deaths, matings, fights, notable events
    family-tree.json
    relationships-graph/day-0001.json
    population-stats.parquet
    evolution.parquet
  F0001-rex/
    profile.md | profile.json   sex, birth time, parents, genome summary, assigned vs expressed personality, fidelity history
    diary/day-0001.md           narrative timeline: notable acts, speech, thoughts, feelings (template + optional LLM prose)
    timeline/day-0001.jsonl     EVERY event (complete, machine-readable)
    speech/day-0001.jsonl       every signal sent/received, with English translation
    mind/day-0001.parquet       feelings, drives, thoughts at 1 Hz neural time
    brain/day-0001.zarr         activity per neuropil (~80) and key pathway (~150) at 4–10 Hz
    health/day-0001.parquet     energy, water, protein, injuries, mated status, egg load, age
    tasks/attempts.jsonl        task attempts and scores
    recordings/                 full spike rasters (focus mode and flight-recorder dumps only)
watcher/
  journal/day-0001.md
  interventions.jsonl
  sleep-log.jsonl
timelines/<timeline-id>/{flies,watcher}/   (branches and archived futures, WATCH-R-032/033)
```

## 4. Requirements

### 4.1 Records and identity

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LOG-R-001 | M | THE WATCHER SHALL write exactly the layout in §3, rooted at the configured path (default `D:\the-fly-colony\flies`, reached from WSL2 as `/mnt/d/...`). | T-LOG-U-001 |
| LOG-R-002 | M | Every record SHALL carry: `real_ts`, `sim_ts`, `fly_ts`, `event_id`, `fly_id` (null for colony-level records), `interpreted`, `evidence`, `confidence`, `schema_version`, `timeline_id` and `fidelity`. Direct physical facts (e.g. a contact) have `interpreted: false`, and their evidence is a reference to the engine event. | T-LOG-U-002 |
| LOG-R-003 | M | `event_id` SHALL be deterministic, unique and sortable, derived from (timeline, tick, source, sequence), so replays produce identical IDs and LLM citations stay valid. | T-LOG-I-002 |
| LOG-R-004 | M | "Everything" SHALL include: every behavior start and stop; every contact; every signal sent and received; feeding and drinking bouts; sleep bouts; mood changes past threshold; thought samples (mind files); decisions; task attempts and trials; life events (birth, eclosion, maturity, mating, egg laid, death); interventions that affect the fly (e.g. transfer); fidelity changes. | T-LOG-I-001 |
| LOG-R-005 | M | Per-fly files SHALL roll over at fly midnight (`day-NNNN`, zero-padded to 4 digits and growing if needed), computed from the life clock, so they stay correct when D changes. | T-LOG-U-003 |

### 4.2 Formats

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LOG-R-010 | M | `timeline/*.jsonl` SHALL hold every event for the fly as one JSON object per line. `speech/*.jsonl` holds signal events (COMM-R-001) and reception records. | T-LOG-U-004 |
| LOG-R-011 | M | `mind/*.parquet` SHALL hold emotion vectors and thought records (MIND-R-020/031). `health/*.parquet` SHALL hold physiology at a registry rate (proposal: every fly minute). | T-LOG-U-004 |
| LOG-R-012 | M | `brain/*.zarr` SHALL hold neuropil and key-pathway activity at 4–10 Hz, plus modulator traces, compressed with zstd. | T-LOG-U-004 |
| LOG-R-013 | M | `profile.json` SHALL hold: sex; birth time (three timestamps); origin (genesis / born / spawned); parents; generation; genome summary (preset, top deviating genes); assigned vs expressed personality; fidelity history; stage and status; cause of death. `profile.md` is its readable rendering. | T-LOG-U-005 |
| LOG-R-014 | M | The roster `README.md` SHALL be regenerated at least every fly hour and on every birth and death. | T-LOG-U-005 |
| LOG-R-015 | M | Colony files SHALL include: `chronicle/day-*.md` (births, deaths, matings, fights, notable events, interventions visible in the world); `family-tree.json` (nodes with parents and generation); `relationships-graph/day-*.json` (MIND-R-042); `population-stats.parquet` (per fly hour: counts by stage and sex, mean reserves, births, deaths); `evolution.parquet` (GENE-R-070). | T-LOG-U-006 |
| LOG-R-016 | M | The `watcher/` folder SHALL hold `journal/day-*.md` (WATCH-R-040), `interventions.jsonl` (WATCH-R-016) and `sleep-log.jsonl` (WATCH-R-026). | T-LOG-U-007 |
| LOG-R-017 | M | Each file type SHALL declare a schema version, and there SHALL be a documented migration path for older versions. | T-LOG-U-008 |

### 4.3 Diaries and chronicle (template narrator)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LOG-R-020 | M | THE WATCHER SHALL always write a **template diary** first, incrementally during the day and finalized at day close. Each notable event is a line with `fly_ts`, a plain description, the speech translation or thought or feeling where relevant, and its `event_id`. | T-LOG-U-009 |
| LOG-R-021 | M | Diary entries SHALL name other flies as "Name (F0042)". Interpreted content is visibly marked (e.g. italic quotes for translations, "(thinking)" for thoughts, "(feels)" for feelings). | T-LOG-U-009 |
| LOG-R-022 | M | LLM prose (013), when available, SHALL be appended in a separate, clearly marked section with event citations. It never replaces the template text. | T-LLM-U-003 |

Example diary lines (format draft):

```
## Day 3 — F0012 Rex (♂, 4 fly days old)
- **06:02:11** Woke on Perch 2 after 7 h 40 min of sleep. `E…a91`
- **06:14:03** Sang pulse song to Jasmine (F0042). *"I'm courting you."* (conf 0.92) `E…b07`
- **06:14:09** Jasmine (F0042) flicked her wings. *"Not interested."* (conf 0.71) `E…b0c`
- **06:14:10** (feels) frustrated ↑ — courtship drive high, 3rd rejection today (conf 0.64) `E…b0d`
- **06:20:45** (thinking) Sweet smell to the left… hungry… turning left. `E…c11`
```

### 4.4 Guarantees

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LOG-R-030 | M | **Completeness:** every event in the engine stream SHALL appear in `/flies`. The test compares a debug dump of engine events with the logs. | T-LOG-I-001 |
| LOG-R-031 | M | Writes SHALL be append-only and flushed at least every N seconds (registry). After a crash, partial last lines are repaired, and replayed events are de-duplicated by `event_id`. | T-LOG-I-003 |
| LOG-R-032 | M | Logs SHALL never feed back into the engine. | T-WATCH-I-006 |
| LOG-R-033 | M | Writers SHALL keep up with the stream at 100 flies on the target rig, writing from WSL2 to `/mnt/d`, with 2× headroom. IF they cannot THEN the engine blocks (WATCH-R-003) and an alert is raised. | T-LOG-P-001 |

### 4.5 Raw neural data, volume and retention

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LOG-R-040 | M | Full spike rasters SHALL be written only for focus-mode flies and flight-recorder dumps (CONST-3.3). | T-LOG-U-010 |
| LOG-R-041 | M | The **flight recorder** SHALL keep a rolling in-RAM buffer of full spike data (scope, window length and RAM budget configurable) and dump pre- and post-event windows to `recordings/` around matings, fights, births, deaths and other configured triggers. | T-LOG-U-010 |
| LOG-R-042 | M | THE WATCHER SHALL write a daily storage report (GB per real day, projected days until full) to the journal. The budget is about 10–15 GB per real day at 100 flies and 24 fly days per real day. | T-LOG-P-002 |
| LOG-R-043 | M | At fly-day close, JSONL files SHALL be compressed to `.jsonl.zst`. Markdown stays plain. Parquet and Zarr use zstd internally. | T-LOG-U-011 |
| LOG-R-044 | M | Brain summaries older than 7 days SHALL be downsampled to a lower rate (proposal: 1 Hz). Events, diaries, profiles and the chronicle are kept forever. Recordings follow a configurable retention policy. | T-LOG-U-011 |
| LOG-R-045 | M | Retention jobs SHALL never delete events or diaries, and SHALL run only on closed days. | T-LOG-I-004 |

### 4.6 Query layer

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LOG-R-050 | M | THE WATCHER SHALL provide read-only DuckDB views over all tables (timeline, speech, mind, health, tasks, colony), used by `colony ask` and the LLM's tools. | T-LOG-U-012 |
| LOG-R-051 | M | Queries such as "what did F042 do today", "who fought whom", "family tree of F007" and "evolution report" SHALL be answerable from these views without the LLM (as structured output). | T-LOG-U-012 |

## 5. Acceptance criteria

| ID | Criterion |
|---|---|
| LOG-AC-01 | **Completeness (Phase 3 gate):** over a 1-fly-day run, engine events ⊆ `/flies` records, with zero missing. |
| LOG-AC-02 | A crash-and-replay leaves no duplicate or missing events. |
| LOG-AC-03 | Day files roll over at fly midnight, including across a live change of D. |
| LOG-AC-04 | A diary for a colony fly shows timestamps, speech translations, thoughts and feelings, each with an event id (manual acceptance #2 in plan §18). |
| LOG-AC-05 | Sustained write throughput on the target rig has ≥ 2× headroom; the daily volume is within budget. |
| LOG-AC-06 | Retention compresses and downsamples closed days and never deletes events or diaries. |
| LOG-AC-07 | The example queries in R-051 return correct structured answers. |

## 6. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-LOG-U-001 | unit | Layout and roots (including timelines). |
| T-LOG-U-002 | unit | Common fields on every record type. |
| T-LOG-U-003 | unit | Day rollover under D changes. |
| T-LOG-U-004 | unit | Formats for timeline, speech, mind, health and brain files. |
| T-LOG-U-005 | unit | Profiles and roster. |
| T-LOG-U-006 | unit | Colony files, including the relationship graph. |
| T-LOG-U-007 | unit | Watcher folder. |
| T-LOG-U-008 | unit | Schema versions and migration. |
| T-LOG-U-009 | unit | Template diary format and markers. |
| T-LOG-U-010 | unit | Focus recordings and the flight recorder. |
| T-LOG-U-011 | unit | Compression and downsampling. |
| T-LOG-U-012 | unit | DuckDB views and example queries. |
| T-LOG-I-001 | invariant | Completeness. |
| T-LOG-I-002 | invariant | Deterministic event IDs across replays. |
| T-LOG-I-003 | invariant | Crash consistency and idempotence. |
| T-LOG-I-004 | invariant | Retention never deletes protected data. |
| T-LOG-P-001 | perf | Write throughput to `/mnt/d`. |
| T-LOG-P-002 | perf | Daily volume vs budget. |

## 7. Assumptions and open questions

| ID | Question | Proposal | Decision |
|---|---|---|---|
| LOG-OQ-01 | "Brain summaries older than 7 days": fly days or real days? | **Real days**, since the rule exists to manage disk space. | Accepted (proposal), 2026-10-12 |
| LOG-OQ-02 | Flight-recorder scope and RAM budget. | Default: all flies, 10 s pre + 10 s post window, ≤ 8 GB RAM on the 56 GB rig (less on the laptop). | Accepted (proposal), 2026-10-12 |
| LOG-OQ-03 | Do day files start at fly midnight or at dawn? | Midnight (a calendar day); dawn is still visible in the diary. | Accepted (proposal), 2026-10-12 |
| LOG-OQ-04 | Sampling rate for health data. | Every fly minute (2.5 s real). | Accepted (proposal), 2026-10-12 |
| LOG-OQ-05 | Recording file format. | Parquet (neuron_id, t) per dump, with a small JSON header; NWB export later if wanted. | Accepted (proposal), 2026-10-12 |
| LOG-OQ-06 | Writing directly to `/mnt/d` from WSL2 may be slow (9P filesystem). | Stage to WSL ext4 and copy asynchronously to D: if the throughput test fails (PERF-R-009). | Accepted (proposal), 2026-10-12 |
