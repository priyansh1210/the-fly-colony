# 013 — Console, Dashboard & Watcher LLM

| Field | Value |
|---|---|
| Status | Draft — awaiting review |
| ID prefixes | `CLI` (command line), `DASH` (API + web dashboard), `LLM` (Watcher's local language model) |
| Phase | 6 (LLM runtime, eval harness, model pick); 8 (CLI, API, dashboard) |
| Plan refs | §10.3, §10.5, §12, §13 |
| Depends on | 009 (Control API, audit), 010, 011 (query layer, diaries), 012 (puzzle specs) |
| Used by | You |
| Constitution | CONST-4 (you → Watcher → Environment), CONST-2.3 (no brain access), CONST-7 (grounded language) |

## 1. Purpose

Give you three ways to control and understand the colony:
- the **`colony` CLI**;
- a **local web dashboard** (live view, fly inspector, puzzle builder, controls, chat);
- the **Watcher's local LLM**, which writes diary prose, answers questions over the logs, and turns plain English into typed commands.

All three talk only to the Watcher, and the LLM is grounded or silent.

## 2. Scope

**In scope:** CLI commands and behavior; the local API and WebSocket; dashboard views; LLM runtime, isolation, uses, grounding guard, eval harness, model selection and throughput.

**Out of scope:** command semantics (009, 012); data production (008, 010, 011).

## 3. CLI (`colony`, Typer)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| CLI-R-001 | M | The CLI SHALL talk only to the Watcher, never directly to the engine. | T-CLI-I-001 |
| CLI-R-002 | M | THE CLI SHALL provide at least: `genesis`, `run`, `status`, `watcher sleep [--now]\|wake\|schedule`, `time set --fly-day 60m`, `time speed`, `pause`, `resume`, `spawn N [--sex --preset --stage --at]`, `env …`, `chamber create\|list\|edit\|delete`, `task assign\|list\|scores`, `transfer F0012 --to maze-1 --mode sleep\|blink`, `focus F0012`, `checkpoint`, `restore`, `branch`, `timelines`, `ask "…"`, `log tail`. | T-CLI-U-001 |
| CLI-R-003 | M | Every mutating CLI command SHALL map to exactly one Control API command (or a batch you confirm). It shows validation errors, and destructive or large actions prompt for confirmation unless `--yes` is given (WATCH-R-015). | T-CLI-U-002 |
| CLI-R-004 | M | Every command SHALL support `--json` output for scripting and return documented exit codes. | T-CLI-U-003 |
| CLI-R-005 | M | `colony ask` SHALL return a grounded LLM answer with event citations. IF the LLM is unavailable THEN it SHALL return a structured answer from the query layer (LOG-R-051), or a clear message. | T-CLI-U-004 |

## 4. API and dashboard

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| DASH-R-001 | M | The Watcher SHALL serve a local FastAPI app: REST for commands and queries, and a WebSocket for the live (decimated) view stream. | T-DASH-U-001 |
| DASH-R-002 | M | The server SHALL bind to 127.0.0.1 by default. Binding to any other interface requires explicit config **and** token authentication. | T-DASH-U-002 |
| DASH-R-003 | M | The dashboard SHALL change nothing except by sending Control API commands. Every mutation is audited with `source = dashboard`. | T-DASH-U-003 |
| DASH-R-010 | M | **Live colony view** (Svelte + PixiJS): a top-down map of every fly (sex colors, mood halos, speech bubbles showing translations), entities (food by stage, water, eggs, pupae, corpses), zones and chambers; pan, zoom and select. Target ≥ 30 fps with 150 flies on the dev laptop. | T-DASH-P-001 |
| DASH-R-011 | M | **Fly inspector:** profile, live mood and drive gauges, thought stream, neuropil activity map, **fly-eye view**, diary, health, relationships, task history. | T-DASH-M-001 |
| DASH-R-012 | M | **Colony views:** statistics, family tree, relationship graph, evolution charts. | T-DASH-M-001 |
| DASH-R-013 | M | **Puzzle builder:** draw graph mazes, set edge costs and terrain, place incentives, upload images or videos to an image arena with a fly-eye preview, then save as validated chamber and task specs (012). | T-DASH-M-002 |
| DASH-R-014 | M | **Task scores and leaderboards.** | T-DASH-M-002 |
| DASH-R-015 | M | **Time controls:** D, `sim_speed`, pause/resume, with a live display of real minutes per fly day and RTF. | T-DASH-M-001 |
| DASH-R-016 | M | **Watcher panel:** state (awake/asleep), schedule, audit log, alerts, and chat with the Watcher LLM. | T-DASH-M-001 |
| DASH-R-017 | C | **3D brain viewer** (Three.js with FlyWire neuropil meshes), later. | — |
| DASH-R-018 | S | Frontend assets SHALL be bundled locally, so the dashboard works offline. | T-DASH-U-004 |

## 5. Watcher LLM

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| LLM-R-001 | M | The runtime SHALL be pluggable: a llama.cpp server or Ollama behind an OpenAI-compatible HTTP interface, with the endpoint and model set in `config/watcher.yaml`. | T-LLM-U-001 |
| LLM-R-002 | M | By default the LLM SHALL run on CPU/RAM, and use the GPU only when you configure it explicitly and the VRAM budget (014) allows. | T-LLM-U-001 |
| LLM-R-003 | M | **Isolation:** the LLM process SHALL have no access to the engine. The Watcher is its only client, and its output never reaches any fly. `import-linter` forbids engine → LLM imports. | T-LLM-I-001 |
| LLM-R-004 | M | The LLM SHALL be used for exactly four things: (1) per-fly daily diary prose from structured fact bundles; (2) colony chronicle prose; (3) Q&A over the logs through read-only DuckDB tools (allow-listed views, row limits, timeouts); (4) turning plain English into typed Control API commands. | T-LLM-U-002 |
| LLM-R-005 | M | **Grounding guard:** every generated sentence SHALL cite ≥ 1 `event_id`. A validator checks that each cited event exists and belongs to the bundle, and that every entity, number, time and event type mentioned appears in the bundle. IF validation fails THEN the Watcher retries up to N times, then falls back to the template text and logs the failure. | T-LLM-U-003 |
| LLM-R-006 | M | Template diaries SHALL always be produced first. No log depends on the LLM. | T-LLM-U-003 |
| LLM-R-007 | M | For plain-English commands, the LLM SHALL only **propose** typed commands (JSON), which are validated by schema and shown back to you in plain terms. Destructive or large actions need your explicit confirmation. The audit log records the natural-language input and the parsed command. | T-LLM-U-004 |
| LLM-R-008 | M | The LLM SHALL never issue commands on its own initiative, only in reply to your chat input. | T-LLM-I-002 |
| LLM-R-009 | M | **Eval harness:** 50 fact bundles (faithfulness must be 100% of sentences grounded, otherwise that output falls back to templates) and 100 sample commands (≥ 95% exact-match parse accuracy), plus latency and throughput. It produces a results table per candidate model; the best model that fits is selected and recorded in config. | T-LLM-V-001 |
| LLM-R-010 | M | **Throughput:** the LLM SHALL sustain ~5–6 tokens/s for diaries (100 flies × ~200 tokens × 24 fly days per real day). IF it falls behind THEN prose work queues up, and template output is unaffected. | T-LLM-P-001 |
| LLM-R-011 | M | Every generated text SHALL record the model id, prompt version and validation result. | T-LLM-U-003 |
| LLM-R-012 | M | Prompts SHALL be versioned in the repository. | review |
| LLM-R-013 | S | Chat answers SHALL state uncertainty, and say so plainly when the logs cannot answer a question. | T-LLM-V-001 |

## 6. Acceptance criteria

| ID | Criterion |
|---|---|
| DASH-AC-01 | **Phase 8 gate:** every power in plan §10.3 works end to end from both the CLI and the dashboard (checklist T-DASH-M-001/002). |
| DASH-AC-02 | The server listens only on localhost by default; a remote bind without a token is refused. |
| DASH-AC-03 | Every UI-originated mutation appears in the audit log with the correct source. |
| LLM-AC-01 | **Phase 6 gate:** a model is chosen with 100% faithfulness (after fallback) and ≥ 95% command-parse accuracy on the eval sets. |
| LLM-AC-02 | With the LLM server stopped, diaries, chronicle, queries and commands all still work (template and structured paths). |
| LLM-AC-03 | Plan §18 manual acceptance steps 1–6 pass. |

## 7. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-CLI-U-001..004 | unit | Command coverage; mapping and confirmation; JSON output and exit codes; `ask` with and without the LLM. |
| T-CLI-I-001 | invariant | The CLI never connects to the engine. |
| T-DASH-U-001..004 | unit | API and WebSocket; bind and auth; audited mutations; offline assets. |
| T-DASH-P-001 | perf | Live view frame rate with 150 flies. |
| T-DASH-M-001 | manual | Checklist: inspector, colony views, time controls, Watcher panel, alerts. |
| T-DASH-M-002 | manual | Checklist: puzzle builder, image upload, fly-eye preview, scores. |
| T-LLM-U-001..004 | unit | Runtime config; the four uses; grounding validator and fallback; command proposal flow. |
| T-LLM-I-001 | invariant | LLM isolation contracts. |
| T-LLM-I-002 | invariant | No self-initiated commands. |
| T-LLM-V-001 | validation | Eval harness (faithfulness, parse accuracy). |
| T-LLM-P-001 | perf | Sustained tokens/s on the target rig. |

## 8. Assumptions and open questions

| ID | Question | Proposal |
|---|---|---|
| LLM-OQ-01 | Which models to evaluate? | Candidates in the 8–14B dense and ~30B-A3B MoE classes (or newer equivalents at eval time), all run on CPU with 56 GB RAM. The harness decides. |
| LLM-OQ-02 | Auto-execute small, non-destructive chat commands, or always confirm? | Always show the parsed command; auto-execute only if you enable it. |
| DASH-OQ-01 | Confirm the frontend stack (Svelte + PixiJS). | Keep the plan's choice. |
| DASH-OQ-02 | Do you want to reach the dashboard from another device on your LAN (e.g. a phone)? | Off by default; token-protected LAN mode as an option. |
