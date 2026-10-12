# 014 — Performance & Fidelity

| Field | Value |
|---|---|
| Status | Approved — 2026-10-12 |
| ID prefixes | `FID` (fidelity levels), `PERF` (performance, soak), `HW` (hardware portability and capacity limits) |
| Phase | Device layer and hardware probe from Phase 0–1 (HW-R-001..005, HW-R-010); capacity benchmark and limits from Phase 1 and enforced from Phase 5 (genesis/spawn); COARSE early (from Phase 1, for development and CI); full scope in Phase 9 (scale and hardening) |
| Plan refs | §4.6, §13, §16, §17, §15 Phase 9, §18 (performance) |
| Depends on | 001 (type graph), 002, 009, 011 |
| Used by | Every runtime component |
| Constitution | CONST-1.3 (global calibration of rate units), CONST-7.3 (honest emergence at every fidelity) |

## 1. Purpose

Make the colony **run on any supported GPU, from a 4 GB card to a data-center GPU, and on CPU alone**, from the same code and the same checkpoints. What changes between machines is only *how many flies* and *at which fidelity* they can run, and those limits come from measuring the machine, not from guessing. The reference target remains 100+ flies at 1 real hour = 1 fly day on an RTX 4060-class GPU. This rests on three **fidelity levels** that keep each fly's learned memories intact when it switches level, a **hardware capacity profile** that sets per-machine limits, measured performance targets and a 72-hour soak test.

## 2. Scope

**In scope:** FULL, HYBRID and COARSE definitions; neuron-level sets; calibrating type-level rate units; promotion and demotion; mixed-fidelity batches; logging fidelity; hardware portability, detection, capacity benchmarking and per-machine fly limits (§5); moving colonies and trained flies between machines; performance targets and benchmarks; VRAM, RAM and CPU budgets; the soak test; storage performance; hardware tiers.

**Out of scope:** the kernels themselves (002); the type-graph build (001).

## 3. Fidelity levels

| Level | What runs | Use |
|---|---|---|
| FULL | Every neuron | Focus flies, puzzle subjects, strong GPUs |
| HYBRID | Neuron-level mushroom body, central complex, sensory and descending/motor pathways. Everything else as cell-type-level rate units (~8–11k types). | 100+ flies in real time on a mid-tier GPU (RTX 4060 class) |
| COARSE | Everything at cell-type level except the mushroom body and central complex | Low-tier GPUs, CPU-only machines, development and CI |

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
| PERF-R-001 | M | **Reference target (Phase 9 gate):** 100 flies at HYBRID plus 10–15 focus flies at FULL run at ≥ 1.0 RTF on a **mid-tier reference GPU** (RTX 4060 8 GB class, ~270 GB/s) with the LLM running on CPU at the same time. Other machines are held to their own measured capacity profile (§5), not to this number. | T-PERF-P-001 |
| PERF-R-002 | M | Total VRAM use SHALL stay within the device's VRAM budget (total VRAM minus the reserve `hw.vram_reserve_frac`, HW-R-012), with a per-component breakdown reported. On the 8 GB reference GPU this means ≤ 7.0 GB. | T-PERF-P-001 |
| PERF-R-003 | M | On a **low-tier GPU** (4 GB class, e.g. GTX 1650, with 8 GB RAM): a COARSE colony of 10–30 flies and 3–5 FULL flies SHALL run. On **CPU only**, a small COARSE colony SHALL run (slower than real time, with stretched fly days). The CI test suite SHALL run on CPU within a time budget set in design. | T-PERF-P-002 |
| PERF-R-004 | M | THE SYSTEM SHALL benchmark with pytest-benchmark: RTF per fidelity and batch size per device; brain kernels; vision raycasting; odor grid; physics; Watcher decoders; log writing; checkpoint time. | T-PERF-P-001..006 |
| PERF-R-005 | M | THE SYSTEM SHALL measure and report how much less quiet and sleeping brains cost (event-driven savings). | T-BRAIN-P-002 |
| PERF-R-006 | M | IF RTF < 1 THEN fly days SHALL stretch in wall time and the dashboard shows it (CLOCK-R-006/008). Nothing degrades silently. | T-CLOCK-U-004 |
| PERF-R-007 | M | **72-hour soak test:** no crash; RAM and VRAM growth ≤ 5% after warm-up; no runaway events; per-fly firing-rate distributions stay inside the homeostatic bands; clock arithmetic exact; log completeness holds; disk use within the 011 budget. | T-PERF-S-001 |
| PERF-R-008 | M | A checkpoint of 100 flies SHALL complete in ≤ 60 s (proposal) without changing state. | T-PERF-P-005 |
| PERF-R-009 | M | Log writing to the configured `/flies` path SHALL sustain the required rate with 2× headroom. IF it cannot (e.g. a slow or cross-filesystem path such as WSL2 → `/mnt/<drive>`) THEN logs are staged on a fast local path and copied asynchronously (LOG-OQ-06). | T-LOG-P-001 |
| PERF-R-010 | M | The engine SHALL run on **native Windows and on Linux** (including WSL2) from the same code. The pure-PyTorch path (BRAIN-R-053) is the portable baseline on every platform; faster kernels (e.g. Triton) are used only where available and only after matching it within tolerance. Templates, checkpoints and logs live under configurable paths. | T-PERF-P-002, T-HW-U-005 |
| PERF-R-011 | M | Running the LLM on CPU SHALL reduce engine RTF by ≤ 5% (by pinning CPU cores or setting process priority). | T-PERF-P-006 |

## 5. Hardware portability and capacity limits

The colony must run on different GPUs. A weak GPU is not an error: it simply gets **fewer flies** and/or **lower fidelity**, and the system says so up front instead of crashing or silently slowing down. Two physical limits matter, and they are measured separately:

- **VRAM size → hard limit.** How many flies (per fidelity) physically fit in memory. Never exceeded.
- **Memory bandwidth → soft limit.** How many flies can run at the target speed (RTF ≥ `hw.rtf_target`, default 1.0). Exceeding it is allowed only with your confirmation, and fly days then stretch in wall time (PERF-R-006).

For example, an RTX 4000 Ada (20 GB, ~280 GB/s) has about the same *soft* limit as an RTX 4060 (8 GB, ~272 GB/s), but a much higher *hard* limit.

### 5.1 Device support and portability

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| HW-R-001 | M | THE SYSTEM SHALL run unchanged on any NVIDIA GPU supported by the pinned PyTorch CUDA build (minimum compute capability set in design from that build), and on CPU only. No code path SHALL assume a specific GPU model, VRAM size, bandwidth or device index. | T-HW-U-001, T-HW-U-005 |
| HW-R-002 | M | All device placement SHALL go through one device layer (`--device auto|cuda[:N]|cpu`, default `auto`). A lint check SHALL flag hard-coded device strings and VRAM/bandwidth literals outside that layer. | T-HW-U-005 |
| HW-R-003 | C | WHERE PyTorch supports another accelerator (AMD ROCm, Apple MPS, Intel XPU), THE SYSTEM MAY run on it through the pure-PyTorch path. It is not gated (HW-OQ-01). | review |
| HW-R-004 | M | Hardware SHALL NOT change the model. Device, tier and profile SHALL NOT alter any registry parameter, timestep, sensory resolution, rule or per-fly biology. They may only change: fly limits, the default fidelity of new flies, batch sizes, kernel choice and buffer sizes. Precision may differ only as already allowed (BRAIN-R-052, gated). | T-HW-U-006 |
| HW-R-005 | M | Every run manifest and checkpoint SHALL record the device: GPU name, VRAM, compute capability, driver, CUDA and PyTorch versions, kernel path, and the capacity profile in use (CONST-5.3). | T-HW-U-001 |

### 5.2 Detection, capacity benchmark and limits

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| HW-R-010 | M | WHEN the engine starts THE SYSTEM SHALL probe the hardware: GPUs (name, total and free VRAM, compute capability), system RAM, CPU cores and free disk at the configured paths. | T-HW-U-001 |
| HW-R-011 | M | THE SYSTEM SHALL provide a **capacity benchmark** (`colony hardware benchmark`) that measures, on this device, the VRAM per fly and the cost per fly-step at each fidelity and sex template, plus fixed world costs. The result is cached as the device's **capacity profile**, and is re-run automatically when the GPU, driver, PyTorch version, kernel path or template version changes. Before the first benchmark, the tier defaults in §5.4 apply. | T-HW-P-001 |
| HW-R-012 | M | From the capacity profile THE SYSTEM SHALL compute, for any mix of fidelities: the **hard limit** (flies that fit in VRAM minus a reserve `hw.vram_reserve_frac`) and the **soft limit** (flies that keep RTF ≥ `hw.rtf_target`). Both are shown in the CLI and dashboard, e.g. "this GPU: up to 38 HYBRID in real time, 64 max". | T-HW-U-002 |
| HW-R-013 | M | IF a command would exceed the **hard limit** (genesis, spawn, a restore, promotion to FULL, a transfer into a chamber on another batch) THEN THE WATCHER SHALL refuse it before acting, state the limit, and suggest what fits (fewer flies, a lower fidelity, or observe-only focus, FID-OQ-01). | T-HW-U-003 |
| HW-R-014 | M | IF a command would exceed the **soft limit** but not the hard limit THEN THE WATCHER SHALL require confirmation that shows the predicted real minutes per fly day. Accepted commands are audited with the prediction. | T-HW-U-003 |
| HW-R-015 | M | Growth by reproduction SHALL respect the hard limit through the existing cap mechanism: the effective adult cap is `min(adult cap, hard limit)` (LIFE-R-070/071), so surplus eggs are non-viable and no existing fly is ever killed (LIFE-R-073). The manifest and chronicle record when the hardware limit, rather than your cap, is the binding one. | T-HW-U-004 |
| HW-R-016 | M | IF the device runs out of memory despite the limits THEN THE ENGINE SHALL pause at the next step boundary, checkpoint, and report the cause. It SHALL NOT crash, drop flies or lower fidelity silently (auto-fidelity happens only if FID-R-011 is enabled). | T-HW-U-007 |

### 5.3 Moving colonies and trained flies between machines

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| HW-R-020 | M | Checkpoints SHALL be device-independent: state is stored in a portable format (CPU tensors, fixed dtypes), so a checkpoint made on one GPU restores on any other supported GPU or on CPU. | T-HW-I-001 |
| HW-R-021 | M | A fly's learned state (MB and CX plastic weights, homeostatic state), genome and history SHALL survive a move between machines bit-exact, so flies trained on one machine keep what they learned on another. | T-HW-I-001 |
| HW-R-022 | M | IF a restored colony exceeds the new device's hard limit THEN THE WATCHER SHALL refuse the restore and list the options (restore with some flies demoted to a lower fidelity, audited per FID-R-005/006; or use a larger device). It SHALL NOT remove flies to make them fit. | T-HW-U-003 |
| HW-R-023 | M | Runs on the same hardware and software stack are bit-identical (CONST-5.2, BRAIN-R-054). Across devices they SHALL be statistically equivalent on the validation and emergence suites; the manifest marks every device change on a timeline. | T-HW-V-001 |

### 5.4 Hardware tiers

Tiers give **starting defaults** only (the profile used before the first capacity benchmark, and the default fidelity for new flies). Once benchmarked, the measured limits replace them. Numbers are estimates from plan §16 (`ASSUMPTION` until Phase 1 measures them).

| Tier | Detected when | Example GPUs (bandwidth) | Default fidelity for new flies | Estimated capacity at 1 real h = 1 fly day |
|---|---|---|---|---|
| `cpu` | No supported GPU | — | COARSE | A few COARSE flies, slower than real time. Tests and CI. |
| `low` | < 6 GB VRAM | GTX 1650 4 GB (128 GB/s) | COARSE | ~3–5 FULL, or ~30 COARSE |
| `mid` | 6–12 GB | RTX 4060 8 GB (~272 GB/s), RTX 3060 12 GB (360 GB/s) | HYBRID | ~15–20 FULL, or 100–150 HYBRID + 10–15 FULL focus (reference target) |
| `high` | 12–24 GB | RTX 4000 Ada 20 GB (~280 GB/s), used RTX 3090 24 GB (936 GB/s) | HYBRID | Soft limit follows bandwidth (4000 Ada ≈ 4060; 3090 ~60–70 FULL); hard limit follows VRAM |
| `ultra` | > 24 GB | RTX 5090 32 GB (1.79 TB/s), H100/H200 | FULL | ~120–140 FULL + LLM; 250+ FULL on research GPUs |

The tier is picked from VRAM. Bandwidth varies a lot inside a tier, which is why the benchmark (HW-R-011), not the tier, sets the real limits. You can override the tier and the limits in `config/hardware.yaml`. The hard limit cannot be raised above what the benchmark measured.

## 6. Acceptance criteria

| ID | Criterion |
|---|---|
| PERF-AC-01 | **Phase 9 gate:** PERF-R-001 is met and measured on a mid-tier reference GPU (RTX 4060 class). |
| PERF-AC-02 | **Phase 9 gate:** the 72-hour soak test passes (PERF-R-007). |
| FID-AC-01 | The emergence suites pass at HYBRID and COARSE (or the differences are reported and accepted by you). |
| FID-AC-02 | Promotion → demotion round trips keep MB and CX weights bit-exact and are behaviorally neutral. |
| PERF-AC-03 | The benchmark report covers CPU, at least two different GPUs from different tiers, and every fidelity level. |
| HW-AC-01 | **Portability:** the same commit and the same checkpoint run with no code or config edits on CPU and on at least two different GPUs (proposal: one `low` or `mid`, one `high`). |
| HW-AC-02 | **Limits:** on each tested device, genesis or spawn beyond the hard limit is refused with a message stating the limit; beyond the soft limit it asks for confirmation and shows the predicted real minutes per fly day; reproduction stops at the hardware-bound cap without killing any fly. |
| HW-AC-03 | **Prediction:** the capacity profile's predicted RTF and VRAM for a given colony are within ±15% (proposal) of measured values on each tested device. |
| HW-AC-04 | **Trained flies travel:** a fly conditioned on one GPU (e.g. task #26), checkpointed, restored on CPU and on another GPU, keeps its MB/CX weights bit-exact and passes the memory retest. |
| HW-AC-05 | **No crash on exhaustion:** forcing VRAM exhaustion pauses the engine with a checkpoint and a clear report. |

## 7. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-FID-U-001..005 | unit | Level selection; neuron-level sets; promotion and demotion state handling; mixed batches; auto-fidelity policy. |
| T-FID-V-001 | validation | Rate-unit calibration vs FULL. |
| T-FID-V-002 | validation | Behavioral neutrality of switching. |
| T-FID-E-001 | emergence | Emergence suites at every fidelity. |
| T-PERF-P-001 | perf | RTF and VRAM on the mid-tier reference GPU (gate), and on every other available device. |
| T-PERF-P-002 | perf | Low-tier, CI and CPU-fallback budgets; native Windows and Linux. |
| T-PERF-P-003 | perf | Vision, odor and physics throughput. |
| T-PERF-P-004 | perf | Watcher decoder throughput at 100 flies. |
| T-PERF-P-005 | perf | Checkpoint time. |
| T-PERF-P-006 | perf | CPU contention with the LLM. |
| T-PERF-S-001 | soak | 72-hour soak. |
| T-HW-U-001 | unit | Hardware probe (mocked devices: none, 4 GB, 8 GB, 20 GB, multi-GPU); manifest device fields. |
| T-HW-U-002 | unit | Hard and soft limit computation from a capacity profile, for mixed fidelities. |
| T-HW-U-003 | unit | Refusal above the hard limit and confirmation above the soft limit for genesis, spawn, restore, promotion and transfer. |
| T-HW-U-004 | unit | Effective cap = min(your cap, hard limit); eggs non-viable at the cap; no fly killed. |
| T-HW-U-005 | unit | Device lint (no hard-coded devices or VRAM/bandwidth literals); `--device cpu` runs the whole stack. |
| T-HW-U-006 | unit | Changing tier/profile changes no registry value, timestep or sensory resolution. |
| T-HW-U-007 | unit | Simulated out-of-memory → pause + checkpoint + report. |
| T-HW-I-001 | invariant | Checkpoint GPU → CPU → other GPU round trip: learned state and genome bit-exact. |
| T-HW-V-001 | validation | Cross-device statistical equivalence on the validation and emergence suites. |
| T-HW-P-001 | perf | Capacity benchmark run time and prediction accuracy per device. |

## 8. Assumptions and open questions

| ID | Question | Proposal | Decision |
|---|---|---|---|
| FID-OQ-01 | **Focus changes the model.** Promoting a fly to FULL when you focus on it changes how its brain is simulated. That makes focus an (audited) intervention, not pure observation. | Keep it, since it is audited and tested for neutrality (FID-R-012). Also offer **observe-only focus**: high-resolution recording at the current fidelity with no promotion. | Accepted (proposal), 2026-10-12 |
| FID-OQ-02 | Rate-unit calibration method. | Fit per type against FULL recordings over a standard stimulus battery. Choose between a gradient-based and a moment-matching fit in design. | Accepted (proposal), 2026-10-12 |
| FID-OQ-03 | Losing R-STDP weights on demotion. | R-STDP is off by default, so this rarely matters; warn when it does. | Accepted (proposal), 2026-10-12 |
| PERF-OQ-01 | 8 GB RAM on the laptop is tight for preprocessing and development. | Streaming covers it (CONN-R-053). A 16 GB upgrade would help but is not required. | Accepted (proposal), 2026-10-12 |
| PERF-OQ-02 | If the 4060 misses the target: stretch the fly day, lower the population, or use more HYBRID? | Default to stretching the fly day (honest and visible). The other options are your call at run time. | Accepted (proposal), 2026-10-12. Generalized by §5: on any device, the soft limit asks for confirmation and then stretches the fly day; the hard limit is never exceeded. |
| HW-OQ-01 | Which non-NVIDIA accelerators are supported? | NVIDIA (CUDA) and CPU are Must and gated. AMD ROCm, Apple MPS and Intel XPU are Could: best effort through the pure-PyTorch path, not gated in v1. | Accepted (proposal), 2026-10-12 |
| HW-OQ-02 | VRAM reserve kept free. | `hw.vram_reserve_frac` = 0.15 (`ASSUMPTION`, registry), covering fragmentation, the display and other apps. | Accepted (proposal), 2026-10-12 |
| HW-OQ-03 | Multiple GPUs in one machine? | v1 uses one GPU (selectable). Splitting batches across GPUs is a Could for Phase 10. | Accepted (proposal), 2026-10-12 |
| HW-OQ-04 | A hardware-bound population cap means colonies on different machines can evolve differently. Is that acceptable? | Yes. It is the same mechanism as your own cap and is recorded in the manifest and chronicle (HW-R-015), so results stay honest and comparable. | Accepted (proposal), 2026-10-12 |
| HW-OQ-05 | Ship a GPU "known profiles" table so new users get good limits before benchmarking? | Yes: benchmark results can be exported and committed under `config/hardware/profiles/`; a matching profile is used until the local benchmark runs. | Accepted (proposal), 2026-10-12 |
