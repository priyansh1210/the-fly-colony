# 014 — Performance & Fidelity

| Field | Value |
|---|---|
| Status | Draft — awaiting review |
| ID prefixes | `FID` (fidelity levels), `PERF` (performance, soak, hardware) |
| Phase | COARSE early (from Phase 1, for laptop development and CI); full scope in Phase 9 (scale and hardening) |
| Plan refs | §4.6, §13, §16, §17, §15 Phase 9, §18 (performance) |
| Depends on | 001 (type graph), 002, 009, 011 |
| Used by | Every runtime component |
| Constitution | CONST-1.3 (global calibration of rate units), CONST-7.3 (honest emergence at every fidelity) |

## 1. Purpose

Make 100+ flies run at 1 real hour = 1 fly day on an RTX 4060, and make development possible on the GTX 1650 laptop. This rests on three **fidelity levels** that keep each fly's learned memories intact when it switches level, plus measured performance targets and a 72-hour soak test.

## 2. Scope

**In scope:** FULL, HYBRID and COARSE definitions; neuron-level sets; calibrating type-level rate units; promotion and demotion; mixed-fidelity batches; logging fidelity; performance targets and benchmarks; VRAM, RAM and CPU budgets; the soak test; WSL2 and storage performance; hardware tiers (informative).

**Out of scope:** the kernels themselves (002); the type-graph build (001).

## 3. Fidelity levels

| Level | What runs | Use |
|---|---|---|
| FULL | Every neuron | Focus flies, puzzle subjects, strong GPUs |
| HYBRID | Neuron-level mushroom body, central complex, sensory and descending/motor pathways. Everything else as cell-type-level rate units (~8–11k types). | 100+ flies in real time on an RTX 4060 |
| COARSE | Everything at cell-type level except the mushroom body and central complex | Laptop development and CI |

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| FID-R-001 | M | THE ENGINE SHALL support FULL, HYBRID and COARSE fidelity per fly, set by config and by Watcher commands (e.g. focus). | T-FID-U-001 |
| FID-R-002 | M | HYBRID SHALL simulate at neuron level every neuron in a versioned "neuron-level set" (MB, CX, sensory neurons, DN/MN and listed pathways), and aggregate the rest into type-level rate units using the type graph (CONN-R-040). | T-FID-U-002 |
| FID-R-003 | M | COARSE SHALL keep the MB and CX at neuron level. Sensory input and DN readout go through type-level units with fan-in/fan-out maps that preserve the I/O map's meaning. | T-FID-U-002 |
| FID-R-004 | M | Rate-unit parameters SHALL be calibrated globally, per cell type (CONST-1.3), to reproduce FULL's type-averaged rates on the validation assays and in spontaneous activity. The objective and the run are recorded in the registry. | T-FID-V-001 |
| FID-R-005 | M | **Promotion** (HYBRID/COARSE → FULL) SHALL keep MB and CX plastic weights and all neuron-level state. Type-level state becomes neuron-level initial conditions by a documented rule. The switch happens at a step boundary and is logged with three timestamps. | T-FID-U-003 |
| FID-R-006 | M | **Demotion** (FULL → HYBRID/COARSE) SHALL aggregate state and keep MB and CX plastic weights. | T-FID-U-003 |
| FID-R-007 | M | Plastic weights outside the MB and CX (the optional R-STDP set) SHALL exist only at FULL. IF a fly with such weights is demoted THEN THE WATCHER SHALL warn before the loss (FID-OQ-03). | T-FID-U-003 |
| FID-R-008 | M | The Phase-2 and Phase-5 emergence suites SHALL pass at HYBRID and COARSE with the same criteria as at FULL. Any difference is reported. | T-FID-E-001 |
| FID-R-009 | M | Every record SHALL carry the fidelity it was produced at (LOG-R-002), and every profile SHALL show the fly's fidelity history. | T-LOG-U-002 |
| FID-R-010 | M | THE ENGINE SHALL simulate flies at different fidelities at the same time. | T-FID-U-004 |
| FID-R-011 | S | WHERE an auto-fidelity policy is enabled (default **off**), THE WATCHER MAY demote non-focus flies when RTF < target. Every such change is audited. | T-FID-U-005 |
| FID-R-012 | M | Promotion and demotion SHALL be behaviorally neutral within tolerance: no burst of transient activity beyond a registry bound, and behavior statistics before and after the switch are indistinguishable (proposal: two-sample tests on activity, turning and feeding over matched windows). | T-FID-V-002 |

## 4. Performance

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| PERF-R-001 | M | **Target (Phase 9 gate):** 100 flies at HYBRID plus 10–15 focus flies at FULL run at ≥ 1.0 RTF on the RTX 4060 (8 GB) with 56 GB RAM, with the LLM running on CPU at the same time. | T-PERF-P-001 |
| PERF-R-002 | M | Total VRAM use on the 4060 SHALL stay ≤ 7.0 GB, with a per-component breakdown reported. | T-PERF-P-001 |
| PERF-R-003 | M | On the dev laptop (GTX 1650 4 GB, 8 GB RAM): a COARSE colony of 10–30 flies and 3–5 FULL flies SHALL run for development. The CI test suite SHALL run on the CPU fallback within a time budget set in design. | T-PERF-P-002 |
| PERF-R-004 | M | THE SYSTEM SHALL benchmark with pytest-benchmark: RTF per fidelity and batch size per GPU; brain kernels; vision raycasting; odor grid; physics; Watcher decoders; log writing; checkpoint time. | T-PERF-P-001..006 |
| PERF-R-005 | M | THE SYSTEM SHALL measure and report how much less quiet and sleeping brains cost (event-driven savings). | T-BRAIN-P-002 |
| PERF-R-006 | M | IF RTF < 1 THEN fly days SHALL stretch in wall time and the dashboard shows it (CLOCK-R-006/008). Nothing degrades silently. | T-CLOCK-U-004 |
| PERF-R-007 | M | **72-hour soak test:** no crash; RAM and VRAM growth ≤ 5% after warm-up; no runaway events; per-fly firing-rate distributions stay inside the homeostatic bands; clock arithmetic exact; log completeness holds; disk use within the 011 budget. | T-PERF-S-001 |
| PERF-R-008 | M | A checkpoint of 100 flies SHALL complete in ≤ 60 s (proposal) without changing state. | T-PERF-P-005 |
| PERF-R-009 | M | Log writing from WSL2 to `/mnt/d` SHALL sustain the required rate with 2× headroom. IF it cannot THEN logs are staged on ext4 and copied asynchronously (LOG-OQ-06). | T-LOG-P-001 |
| PERF-R-010 | M | The engine SHALL run in WSL2 Ubuntu 24.04, with templates and checkpoints on ext4. A native-Windows pure-PyTorch fallback SHALL exist for tests (BRAIN-R-053). | T-PERF-P-002 |
| PERF-R-011 | M | Running the LLM on CPU SHALL reduce engine RTF by ≤ 5% (by pinning CPU cores or setting process priority). | T-PERF-P-006 |

## 5. Hardware tiers (informative, from plan §16)

Estimates only; Phase 1 benchmarks replace them with measurements.

| Tier | GPU (bandwidth) | FULL-brain flies at 1 real h = 1 fly day |
|---|---|---|
| Dev laptop | GTX 1650 4 GB (128 GB/s) | ~3–5 FULL, or ~30 COARSE |
| Planned rig | RTX 4060 8 GB (~272 GB/s) | ~15–20 FULL, or 100–150 HYBRID + 10–15 FULL focus |
| Best value upgrade | Used RTX 3090 24 GB (936 GB/s) | ~60–70 FULL |
| Ideal | RTX 5090 32 GB (1.79 TB/s) | ~120–140 FULL + LLM |
| Research | H100/H200 or 2× RTX 5090 | 250+ FULL, or the FlyGym full body |

## 6. Acceptance criteria

| ID | Criterion |
|---|---|
| PERF-AC-01 | **Phase 9 gate:** PERF-R-001 is met and measured on the 4060. |
| PERF-AC-02 | **Phase 9 gate:** the 72-hour soak test passes (PERF-R-007). |
| FID-AC-01 | The emergence suites pass at HYBRID and COARSE (or the differences are reported and accepted by you). |
| FID-AC-02 | Promotion → demotion round trips keep MB and CX weights bit-exact and are behaviorally neutral. |
| PERF-AC-03 | The benchmark report covers both GPUs and every fidelity level. |

## 7. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-FID-U-001..005 | unit | Level selection; neuron-level sets; promotion and demotion state handling; mixed batches; auto-fidelity policy. |
| T-FID-V-001 | validation | Rate-unit calibration vs FULL. |
| T-FID-V-002 | validation | Behavioral neutrality of switching. |
| T-FID-E-001 | emergence | Emergence suites at every fidelity. |
| T-PERF-P-001 | perf | RTF and VRAM on the 4060 (gate). |
| T-PERF-P-002 | perf | Laptop, CI and CPU-fallback budgets. |
| T-PERF-P-003 | perf | Vision, odor and physics throughput. |
| T-PERF-P-004 | perf | Watcher decoder throughput at 100 flies. |
| T-PERF-P-005 | perf | Checkpoint time. |
| T-PERF-P-006 | perf | CPU contention with the LLM. |
| T-PERF-S-001 | soak | 72-hour soak. |

## 8. Assumptions and open questions

| ID | Question | Proposal |
|---|---|---|
| FID-OQ-01 | **Focus changes the model.** Promoting a fly to FULL when you focus on it changes how its brain is simulated. That makes focus an (audited) intervention, not pure observation. | Keep it, since it is audited and tested for neutrality (FID-R-012). Also offer **observe-only focus**: high-resolution recording at the current fidelity with no promotion. |
| FID-OQ-02 | Rate-unit calibration method. | Fit per type against FULL recordings over a standard stimulus battery. Choose between a gradient-based and a moment-matching fit in design. |
| FID-OQ-03 | Losing R-STDP weights on demotion. | R-STDP is off by default, so this rarely matters; warn when it does. |
| PERF-OQ-01 | 8 GB RAM on the laptop is tight for preprocessing and development. | Streaming covers it (CONN-R-053). A 16 GB upgrade would help but is not required. |
| PERF-OQ-02 | If the 4060 misses the target: stretch the fly day, lower the population, or use more HYBRID? | Default to stretching the fly day (honest and visible). The other options are your call at run time. |
