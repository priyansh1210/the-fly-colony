# 002 — Brain Engine

| Field | Value |
|---|---|
| Status | Approved — 2026-10-12 |
| ID prefix | `BRAIN` |
| Phase | 1 (simulator and validation). Plasticity lands in Phases 2–4. |
| Plan refs | §4.2, §4.3, §4.4, §4.5 (the brain side), §13, §15 Phase 1, §18 |
| Depends on | 000, 001 |
| Used by | 004, 005, 006, 007, 010, 014 |
| Constitution | CONST-1 (neuron-only minds), CONST-2.5 (taps don't disturb), CONST-5 (determinism), CONST-6 |

## 1. Purpose

Simulate every adult fly's brain from its sex's connectome template, batched on the GPU. The simulation must be reproducible, validated against the published reference model, and able to change through biologically grounded plasticity. The brain is the **only** place where a fly's decisions come from.

## 2. Scope

**In scope:** LIF spiking neurons; graded (non-spiking) units; synapses and delays; background noise; neuromodulator and neuropeptide traces; the receptor-expression table; body→brain routes (the mechanism only; the route catalog lives in 004/006); plasticity rules; per-fly individuality in the shared-topology batch; determinism; CPU fallback; brain checkpoint state; read-only observation taps; the validation harness against Brian2 and the Shiu et al. model.

**Out of scope:** where genome and noise values come from (007); sensory transduction (004); motor readout (005); the fidelity levels themselves (014).

## 3. Definitions

| Term | Meaning |
|---|---|
| LIF | Leaky integrate-and-fire neuron model. |
| Graded unit | A non-spiking neuron modelled by a continuous potential with a rectified output. |
| Trace | A slow concentration variable per compartment or neuropil (e.g. dopamine in MB compartment γ1). |
| Pre-/post-gain | Per-fly multipliers on a neuron's output and input: the effective weight for fly *f* is `w_f(i→j) = p_f(i) · W(i→j) · q_f(j)`. |
| Reference mode | 0.1 ms timestep, used for validation. |
| RTF | Real-time factor: simulated neural seconds per wall-clock second. |

## 4. Requirements

### 4.1 Building a brain

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| BRAIN-R-001 | M | WHEN an adult fly comes into being (eclosion, genesis or spawn-as-adult) THE ENGINE SHALL build its brain from exactly three inputs: its sex's BrainTemplate, its genome-derived parameters (007) and its developmental noise (007). Nothing else sets brain parameters. | T-BRAIN-U-001 |
| BRAIN-R-002 | M | THE ENGINE SHALL keep one copy of each template's connectivity per device, shared by every fly of that sex, and store per-fly parameters and state separately. | T-BRAIN-U-002 |
| BRAIN-R-003 | M | THE ENGINE SHALL express individuality as per-fly, per-neuron pre-gain and post-gain vectors, plus per-neuron threshold and intrinsic-parameter offsets. | T-BRAIN-U-002 |
| BRAIN-R-004 | M | THE ENGINE SHALL store each fly's plastic synapse sets (mushroom body KC→MBON, central complex ring→EPG, and the optional R-STDP set) as small per-fly weight blocks that override the shared weights. | T-BRAIN-U-003 |
| BRAIN-R-005 | M | THE ENGINE SHALL add brains to and remove them from a running batch (births, deaths, fidelity changes) without a restart and without changing any other fly's state or random stream. | T-BRAIN-I-002 |

### 4.2 Neuron and synapse models

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| BRAIN-R-010 | M | THE ENGINE SHALL model spiking neurons as LIF units (membrane time constant, rest, threshold, reset, refractory period), with default values from Shiu et al. 2024 held in the registry. | T-BRAIN-U-004 |
| BRAIN-R-011 | M | THE ENGINE SHALL model synapses as exponential or α-shaped currents with registry time constants and a uniform transmission delay (default: the reference model's value). | T-BRAIN-U-004 |
| BRAIN-R-012 | M | THE ENGINE SHALL take synaptic signs from the template (CONN-R-012). | T-BRAIN-U-004 |
| BRAIN-R-013 | M | THE ENGINE SHALL give every neuron independent background Poisson input, with registry rate and weight, from the fly's own seeded stream. | T-BRAIN-U-005 |
| BRAIN-R-014 | M | THE ENGINE SHALL model graded units as continuous potentials with time constants and rectified outputs, using flyvis parameters for matching cell types and registry values for the rest. | T-BRAIN-U-006 |
| BRAIN-R-015 | M | THE ENGINE SHALL couple graded and spiking units in both directions: graded → spiking as a continuous current proportional to presynaptic output × weight, and spiking → graded as a synaptically filtered spike train. | T-BRAIN-U-006 |
| BRAIN-R-016 | M | THE ENGINE SHALL accept external input only at sensory neurons (from 004) and through the interoceptive routes (R-033). | T-BRAIN-I-004 |
| BRAIN-R-017 | M | THE ENGINE SHALL expose DN, motor-neuron and neurosecretory activity only as filtered rates grouped by the I/O map, for 005 and 006 to consume. | T-BRAIN-U-007 |

### 4.3 Time stepping

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| BRAIN-R-020 | M | THE ENGINE SHALL support a reference mode with dt = 0.1 ms. | T-BRAIN-V-001 |
| BRAIN-R-021 | M | THE ENGINE SHALL use a production dt (target 0.25–0.5 ms) only after it passes the **timestep gate** for that template version: firing-rate correlation ≥ 0.9 against the reference on the validation assay set, and the same outcome on every Phase-2 emergence assay. The gate result is stored with the template. | T-BRAIN-V-002 |
| BRAIN-R-022 | M | IF the configured dt has not passed the gate for the loaded template THEN THE ENGINE SHALL refuse to start in production mode. It may still run in an explicitly flagged experimental mode. | T-BRAIN-U-008 |
| BRAIN-R-023 | M | THE ENGINE SHALL run brain, physics, senses and vision on one fixed, integer-ratio schedule (e.g. physics every k brain steps, vision at 100 Hz of neural time). The schedule is part of the config snapshot. | T-BRAIN-U-009 |

### 4.4 Neuromodulation and internal state

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| BRAIN-R-030 | M | Dopaminergic, serotonergic and octopaminergic neurons SHALL be ordinary spiking neurons in the network. Their spikes SHALL drive concentration traces per target compartment (MB compartments) or per neuropil, with registry rise and decay constants. | T-BRAIN-U-010 |
| BRAIN-R-031 | M | THE ENGINE SHALL model peptide signaling (NPF, sNPF, Tk, DH44, Crz, insulin-like peptides, sex-peptide pathway, AKH from the body) as slow regional or global traces, released by identified neurons (CONN-R-015) or by physiology (006), with registry decay constants. | T-BRAIN-U-010 |
| BRAIN-R-032 | M | Traces SHALL modulate target neurons' gain or excitability and gate plasticity according to a versioned receptor-expression table by cell type (Fly Cell Atlas; `ASSUMPTION` where data is missing). | T-BRAIN-U-011 |
| BRAIN-R-033 | M | THE ENGINE SHALL let body state change brain parameters only through routes listed in the interoceptive route catalog (SENSE-R-060). Each route has a source variable, targets, a transfer function and a citation. | T-BRAIN-I-004 |
| BRAIN-R-034 | M | THE ENGINE SHALL NOT change brain state or parameters from any other non-neural source at runtime. | T-BRAIN-I-004, review |

### 4.5 Plasticity (Phases 2–4)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| BRAIN-R-040 | M | THE ENGINE SHALL change KC→MBON weights by a dopamine-gated rule per MB compartment: KC activity coinciding with compartment dopamine inside an eligibility window depresses the synapse; dopamine without KC activity lets it recover or potentiate (Hige 2015, Cohn 2015-style rules). Rates, windows and bounds are in the registry, and the learning rate is scaled by the genome. | T-BRAIN-U-012 |
| BRAIN-R-041 | M | THE ENGINE SHALL change ring-neuron→EPG weights by a Hebbian-type co-activity rule (Kim et al. 2019; Fisher et al. 2019), with the sign convention in the registry, so that a fly forms a stable mapping from visual scene to heading. | T-BRAIN-U-013 |
| BRAIN-R-042 | M | THE ENGINE SHALL apply slow homeostatic intrinsic plasticity to spiking neurons, moving threshold or gain toward a set-point firing rate. Set-points are scaled by the genome; the time constant is in the registry. | T-BRAIN-U-014 |
| BRAIN-R-043 | M | WHILE a fly is in the engine sleep state (R-045) THE ENGINE SHALL downscale plastic weights toward baseline and apply the registry consolidation rule. | T-BRAIN-U-015 |
| BRAIN-R-044 | C | WHERE `brain.plasticity.rstdp` is enabled (default off) THE ENGINE SHALL apply reward-modulated STDP in the lateral horn and SMP as a research option. | T-BRAIN-U-016 |
| BRAIN-R-045 | M | THE ENGINE SHALL compute each fly's sleep state from the fly's own signals (activity of sleep-promoting circuits such as dFB, plus body quiescence) using registry thresholds, never from Watcher classifications. | T-BRAIN-U-015 |
| BRAIN-R-046 | M | Every plastic weight SHALL stay inside registry bounds. | T-BRAIN-U-012 |
| BRAIN-R-047 | M | IF a fly's population firing rate or any plastic block leaves its registry safe envelope THEN THE ENGINE SHALL publish a `brain.runaway` event and take an automatic checkpoint. It SHALL NOT alter the brain to correct it. | T-BRAIN-I-005 |

### 4.6 Batched GPU execution

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| BRAIN-R-050 | M | THE ENGINE SHALL step all flies of the same sex and fidelity in one batched call. | T-BRAIN-P-001 |
| BRAIN-R-051 | M | Spike propagation SHALL be event-driven: its cost scales with the number of spikes × out-degree, not with the total synapse count. | T-BRAIN-P-002 |
| BRAIN-R-052 | M | Neuron state SHALL be fp32. Weights MAY be fp16 only if the timestep gate passes with fp16 weights. | T-BRAIN-V-002 |
| BRAIN-R-053 | M | THE ENGINE SHALL provide a pure-PyTorch path (no Triton) for CPU and native Windows, matching the GPU path within tolerance on the validation assays (bit-identity not required). | T-BRAIN-V-004 |
| BRAIN-R-054 | M | In deterministic mode (the default), the same seed, template, registry, config and command log SHALL give bit-identical brain state on the same hardware, driver and software. Kernels must not depend on nondeterministic reduction order such as float atomics. | T-BRAIN-I-001 |
| BRAIN-R-055 | M | Each fly SHALL have its own seeded random streams, independent of batch composition and order. | T-BRAIN-I-002 |

### 4.7 Observation taps (read-only)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| BRAIN-R-060 | M | THE ENGINE SHALL publish to the Observation Stream: activity per neuropil (~80), activity per key pathway (~150; list owned by 010), modulator and peptide traces, DN group rates, sensory channel summaries, per-compartment plastic-weight summaries, and the sleep-state indicator. | T-BRAIN-U-017 |
| BRAIN-R-061 | M | WHERE a fly is in focus mode or inside a flight-recorder window THE ENGINE SHALL publish that fly's full spike raster. | T-BRAIN-U-017 |
| BRAIN-R-062 | M | Taps SHALL NOT change any state: runs with taps on and off are bit-identical. | T-BRAIN-I-003 |

### 4.8 State and checkpointing

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| BRAIN-R-070 | M | THE ENGINE SHALL save and restore the complete brain state: membrane potentials, synaptic currents, refractory counters, delay buffers, graded states, traces, plastic weights, homeostatic parameters, RNG states and step counters. A restored brain continues bit-identically. | T-BRAIN-I-006 |

### 4.9 Reference validation (Phase 1 gate)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| BRAIN-R-080 | M | THE SYSTEM SHALL include a reference harness that runs Brian2 with `philshiu/Drosophila_brain_model` on FAFB, plus a validation assay set of at least: sugar GRN activation → proboscis motor neuron (MN9) activation; bitter GRN activation inhibiting that response; water GRN activation; and a mechanosensory (Johnston's organ) → grooming-DN pathway, following Shiu et al. 2024. | T-BRAIN-V-001 |
| BRAIN-R-081 | M | The engine's agreement with the reference SHALL be ≥ 0.9 Pearson correlation of per-neuron firing rates over responsive neurons, with the same top-k activated neurons within tolerance. | T-BRAIN-V-001 |
| BRAIN-R-082 | M | THE SYSTEM SHALL run the same assays on the male template and report cross-sex comparability (CONN-R-031). | T-BRAIN-V-003 |
| BRAIN-R-083 | M | THE SYSTEM SHALL benchmark RTF and VRAM on CPU and on every available GPU (at least two from different tiers, e.g. a GTX 1650 / RTX 4060 class card and the RTX 4000 Ada dev machine) for batch sizes 1, 4, 16 and more, per fidelity. These runs feed the capacity profile (HW-R-011); targets are in 014. | T-BRAIN-P-001 |

## 5. Acceptance criteria

| ID | Criterion |
|---|---|
| BRAIN-AC-01 | **Phase 1 gate:** the validation assays match the Brian2 reference (correlation ≥ 0.9, sugar → MN9 activation reproduced). |
| BRAIN-AC-02 | A production dt is selected and passes the timestep gate. |
| BRAIN-AC-03 | Two runs from the same inputs give identical full-state hashes after 60 s of neural time; adding or removing a fly leaves every other fly's state hash unchanged. |
| BRAIN-AC-04 | Checkpoint → restore → continue is identical to an uninterrupted run. |
| BRAIN-AC-05 | Runs with taps on and off are bit-identical. |
| BRAIN-AC-06 | The CPU fallback matches the GPU path within tolerance. |
| BRAIN-AC-07 | In silico, pairing an odor with a punishment-DAN burst lowers that odor's response at the paired MBON and not at unpaired MBONs. Ring→EPG mapping stabilizes in a fixed visual scene. |
| BRAIN-AC-08 | 24 neural hours of spontaneous activity show no runaway, and an induced runaway (in a test) is detected and checkpointed. |
| BRAIN-AC-09 | RTF and VRAM benchmarks are recorded for CPU and for at least two GPUs from different tiers (HW-AC-01). |

## 6. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-BRAIN-U-001 | unit | A brain's parameters are fully determined by template + genome + noise. |
| T-BRAIN-U-002 | unit | Shared topology; gain-vector math matches the explicit per-fly weight matrix on a small graph. |
| T-BRAIN-U-003 | unit | Plastic blocks override shared weights correctly. |
| T-BRAIN-U-004 | unit | LIF and synapse integration against analytic solutions. |
| T-BRAIN-U-005 | unit | Poisson noise rate and per-fly independence. |
| T-BRAIN-U-006 | unit | Graded dynamics and graded↔spiking coupling. |
| T-BRAIN-U-007 | unit | Output rate filtering and I/O-map grouping. |
| T-BRAIN-U-008 | unit | Production mode refuses an ungated dt. |
| T-BRAIN-U-009 | unit | Multi-rate schedule is exact over long runs. |
| T-BRAIN-U-010 | unit | Trace kinetics for modulators and peptides. |
| T-BRAIN-U-011 | unit | Receptor-table gain modulation. |
| T-BRAIN-U-012 | unit | MB plasticity rule and bounds. |
| T-BRAIN-U-013 | unit | CX ring→EPG rule. |
| T-BRAIN-U-014 | unit | Homeostatic convergence to the set-point. |
| T-BRAIN-U-015 | unit | Sleep-state computation and downscaling. |
| T-BRAIN-U-016 | unit | R-STDP is off by default and works when enabled. |
| T-BRAIN-U-017 | unit | Tap contents and rates; focus raster output. |
| T-BRAIN-V-001 | validation | Shiu et al. assays vs the Brian2 reference. |
| T-BRAIN-V-002 | validation | Timestep and precision gate. |
| T-BRAIN-V-003 | validation | Male-template assays and cross-sex comparability. |
| T-BRAIN-V-004 | validation | CPU vs GPU path agreement. |
| T-BRAIN-I-001 | invariant | Bit-identical determinism. |
| T-BRAIN-I-002 | invariant | Adding or removing a fly doesn't perturb others. |
| T-BRAIN-I-003 | invariant | Taps don't disturb. |
| T-BRAIN-I-004 | invariant | No input path outside sensory neurons and catalogued routes (static + runtime check). |
| T-BRAIN-I-005 | invariant | Runaway detection doesn't modify the brain. |
| T-BRAIN-I-006 | invariant | Checkpoint round trip. |
| T-BRAIN-P-001 | perf | RTF and VRAM per GPU, batch size and fidelity. |
| T-BRAIN-P-002 | perf | Cost scales with spike count. |

## 7. Assumptions and open questions

| ID | Question | Proposal | Decision |
|---|---|---|---|
| BRAIN-OQ-01 | Reuse `annel0/flybrain` GPU kernels? | Evaluate its license and fit in Phase 1; fall back to our own Triton kernels. | Accepted (proposal), 2026-10-12 |
| BRAIN-OQ-02 | Which central-brain neurons should be graded (beyond the optic lobe)? | Start with flyvis types plus a literature list in the registry, and revisit after the Phase 2 gates. | Accepted (proposal), 2026-10-12 |
| BRAIN-OQ-03 | Spatial model for neuropeptides: global or regional volume transmission? | Regional by neuropil where release sites are known, otherwise global. | Accepted (proposal), 2026-10-12 |
| BRAIN-OQ-04 | Homeostatic plasticity timescale: neural time or life-clock time? Under 24× compression the two differ a lot. | Life-clock time (it is a "days-long" process), flagged `ASSUMPTION`, and checked in the 72 h soak. | Accepted (proposal), 2026-10-12 |
| BRAIN-OQ-05 | Exact sleep-state criterion used for downscaling. | dFB activity above threshold plus ≥ N fly minutes of quiescence, per the registry. | Accepted (proposal), 2026-10-12 |
| BRAIN-OQ-06 | Deterministic event-driven kernels can be slower. What performance penalty is acceptable? | ≤ 20%; otherwise discuss a "fast nondeterministic" mode that is never used for invariant tests. | Accepted: ≤ 20% cost; no nondeterministic mode unless discussed. 2026-10-12. |
| BRAIN-OQ-07 | Are fp16 weights acceptable? | Only if the gate passes (R-052). | Accepted (proposal), 2026-10-12 |
