# 002 — Brain Engine: Design

| Field | Value |
|---|---|
| Status | Draft (Phase 1, written after spec approval, 2026-10-12) |
| Implements | [spec.md](spec.md) BRAIN-R-001..034, -047 (watchdog), -050..055, -060..062, -070, -080..083; the Phase-1 part of 014 §5 (HW-R-011, -012) |
| Tasks | [tasks.md](tasks.md) |
| Reports | [reports/](reports/) |

This document describes **how** spec 002 is built. Choices the spec left open are marked **Decision**. Plasticity rules (BRAIN-R-040..046) and the sleep state (R-045) are scheduled for Phases 2–4 by the spec. Phase 1 provides their storage and hooks (per-fly plastic blocks, the runaway watchdog, the sleep field in taps).

---

## 1. Package layout

```
src/flycolony/brain/
  params.py      registry values -> per-dt constants (exact propagators, Brian2 step rounding)
  rng.py         counter-based per-fly random numbers (int64 hash, same bits on every device)
  topology.py    shared CSR connectivity per template/device/variant; event-row expansion
  engine.py      BrainBatch: state, step, add/remove, drive, outputs, watchdog, checkpoint
  modulation.py  amine/peptide traces, receptor table, interoceptive routes
  taps.py        read-only observation taps
  schedule.py    integer-ratio multi-rate schedule
  gate.py        timestep gate records, production refusal, model hash
  select.py      neuron selections (Shiu lists, I/O map channels, cell types)
  assays.py      validation assays and the batched assay runner
  validation.py  engine vs Brian2, timestep gate, male assays
  build.py       BrainSetup from config + registry (plastic sets, output groups, flyvis taus)
src/flycolony/hardware/capacity.py   capacity benchmark and limits (HW-R-011/012)
tools/reference_brian2.py           Brian2 reference harness (unmodified Shiu et al. model.py)
tools/gen_flyvis_params.py          graded time constants from the flyvis ensemble
config/brain/   assays, Shiu neuron lists, receptor table, plastic sets, flyvis time constants
config/senses/routes.yaml           interoceptive route catalog (owned by 004)
config/params/brain.yaml, hardware.yaml   registry entries
```

## 2. Neuron and synapse model (BRAIN-R-010..013)

The spiking model is the Shiu et al. 2024 LIF model, with every value from the registry (`brain.lif.*`, `brain.syn.*`):

    dv/dt = (v_rest - v + g) / tau_m        dg/dt = -g / tau_syn        (unless refractory)
    spike: v > v_thresh  ->  v = v_reset, g = 0, refractory t_ref
    synapse: g_post += w after a uniform delay; w = signed synapse count x w_per_synapse

- **Exact integration.** The engine stores `u = v - v_rest` and advances `(u, g)` with the exact one-step propagator (`params.membrane_propagator`, float64 constants, like Brian2's `linear` method).
- **Brian2 schedule.** One step runs: refractory check → integration → threshold → synaptic delivery, Poisson input → reset (Brian2's `groups, thresholds, synapses, resets`).
- **Refractory writes are dropped.** In Brian2, a variable marked `(unless refractory)` gets a *conditional write*: every write to it, including synaptic `g += w` and `PoissonInput`, is skipped while the neuron is refractory or has just spiked. Only the reset is exempt (`brian2/groups/neurongroup.py`: the Resetter overrides `not_refractory`; Synapses and PoissonInput do not). The engine reproduces this. Without it, strongly driven neurons fired about 2× faster than in Brian2 (sugar assay r = 0.95 → 0.9998 after the fix).
- **Discretization.** The refractory period is `int(t_ref/dt + 1e-3)` steps (Brian2 `timestep()`), and delays are rounded half up (Brian2 spike queue). At 0.1 ms that is 22 and 18 steps.
- **External input** is Poisson drive on **sensory neurons only** (`BrainBatch.set_drive`, BRAIN-R-016). It is a membrane kick of `brain.input.w_poisson` (68.75 mV = 250 × w_syn), and driven neurons have no refractory period (`brain.input.driven_t_ref` = 0), both as in the reference.
- **Background noise (BRAIN-R-013)** is a per-neuron Poisson kick `brain.noise.w` at `brain.noise.rate`. The reference model has none, so reference mode sets the rate to 0. **Decision (ASSUMPTION):** 100 Hz × 1.5 mV. This scan on the female template gives a median of 2 Hz over spiking neurons, 39% silent, a mean of 10 Hz and no runaway. Global calibration against spontaneous-rate data is Phase 2.

## 3. Determinism and batch independence (BRAIN-R-054, -055, -005)

- **Integer sums.** Synaptic input, graded coupling, modulator release and receptor effects are summed as **int64 fixed point** (`brain.num.fixed_point_bits` = 24, i.e. 2^-24 mV). Integer addition is associative, so the GPU's parallel scatter gives the same bits in any order, and a fly's sum never depends on other flies. There are no float atomics anywhere. The cost is one rounding per contribution, far below fp32 noise.
- **Duplicate-safe scatter.** After the integer scatter, every duplicate target writes the same final value, so the scattered write is deterministic too.
- **Single-op float math.** Each per-neuron float operation is one elementwise op with precomputed constants (no runtime `exp`), so it is exact IEEE arithmetic on CPU and GPU. In reference mode the CPU and GPU paths therefore agree **spike for spike** (T-BRAIN-V-004).
- **Counter-based RNG.** Every random number is `hash(fly key, stream, step, neuron)`: a 2-round 32-bit integer hash evaluated in int64 lanes, with multipliers below 2^31 so nothing overflows. Nothing depends on batch size, slot or other flies, and there is no generator state to save.
- **Event blocks.** Drive events (Bernoulli per step) and background events (geometric waiting times) are drawn for `brain.num.event_block_steps` steps at a time to cut kernel launches. Draws are counter-based, so any block size gives identical results (tested with 1000, 7 and 1). Checkpoints store each neuron's next background event, which makes them independent of block alignment.
- **Births and deaths** (`add`/`remove`) touch only their own rows. Queued spikes and pending events are re-addressed to the new slots. Test T-BRAIN-I-002 removes and adds flies mid-run, mid-block, and checks that another fly's state hash is unchanged on CPU and GPU.

## 4. Event-driven propagation (BRAIN-R-051)

The spikes emitted `delay` steps ago are expanded to their CSR rows (`topology.expand_rows`: repeat-interleave of row starts), so the work is proportional to spikes × out-degree. A silent brain propagates nothing, whatever its synapse count (T-BRAIN-P-002). The uniform delay is a ring of per-step spike lists.

## 5. Graded units (BRAIN-R-014, -015; BRAIN-OQ-02)

- **Which neurons.** The template's flyvis types (`conn.graded_cell_types`, 63,502 FAFB neurons) plus a literature list in the registry (`brain.graded.extra_cell_types`: APL, which signals with graded, local inhibition; Amin et al. 2020). Without that entry, APL saturated near 360 Hz in spontaneous activity.
- **Dynamics.** A graded unit is the same membrane equation without spikes (threshold +∞). Its time constant comes from **flyvis** where available. `tools/gen_flyvis_params.py` reads the 50-model pretrained ensemble (MIT, checksum-pinned, loaded with `weights_only=True`) and writes the median per type to `config/brain/flyvis_time_constants.yaml`.
  - flyvis trains at dt = 20 ms and clamps τ at dt, so 48 of 59 types sit at that floor and are flagged `at_floor`.
  - 11 types resolve longer constants (e.g. C2 239 ms).
  - Other graded units use `brain.graded.tau`.
- **Coupling (rate-equivalent).** A graded unit's output is `gain × max(0, v − v_thresh_graded)`, saturating at `brain.graded.max_rate`. It drives its targets like a spiking neuron firing at that rate: each step it adds `w × rate × dt` to the target's `g`. Spiking → graded is the ordinary filtered spike train.
  - **Decision:** graded outputs are recomputed every `brain.graded.update_interval` (1 ms) and held in between. Graded units have τ ≥ 20 ms, and recomputing every step costs about 4M edge updates per fly per step on FAFB.
- The reference variant (`graded=False`) simulates every neuron as LIF, as Shiu et al. do.

## 6. Individuality and plastic blocks (BRAIN-R-001..004)

- **Inputs.** A brain is built from exactly its template and a `FlyBrainSpec`: seed, per-neuron pre/post gains, threshold and rest offsets. 007 will fill the spec from genome and developmental noise.
- **Effective weight.** `p_f(i) · W(i→j) · q_f(j)`: the pre-gain multiplies each contribution, and the post-gain multiplies the integer-summed input.
- **Shared topology.** One copy per (template, device, variant) is cached in `build.topology` (BRAIN-R-002).
- **Plastic sets** (`config/brain/plastic_sets.yaml`):
  - KC→MBON: 62,261 FAFB edges.
  - ER→EPG: 8,451 FAFB edges.
  - R-STDP LH/SMP: off by default.

  Each fly holds its own fp32 weights for these edges, and delivery uses them instead of the shared weight.

## 7. Neuromodulation and interoceptive routes (BRAIN-R-030..034; BRAIN-OQ-03)

- **Release.** Releasing neurons are the template's modulatory list (amines and the 31 cited peptides, CONN-R-015). A spike releases into every neuropil where the neuron has output synapses, weighted by its output fraction there. Neurosecretory cells release into a global compartment (**Decision**, BRAIN-OQ-03).
- **Trace dynamics.** Each trace is a dual exponential, `c = x_decay − x_rise`, with amine and peptide constants from the registry. It is updated every `brain.trace.update_interval` (1 ms), and releases in between are summed exactly.
- **Units (Decision).** Release is normalised by the compartment's total releaser output fraction and by τ_decay. A steady trace of 1.0 then means the releasers there fire at `brain.trace.unit_rate` (10 Hz). Without this, traces grew with the number of releasers, and every receptor effect saturated.
- **Receptor table** (`config/brain/receptors.yaml`, versioned). Each entry has a cited existence and sign for the effect: sNPF and insulin on DM1 ORNs, Tk on DM5 ORNs, dopamine on sugar GRNs, octopamine on HS/VS cells, and AKH on octopaminergic neurons.
  - Gain effects multiply input gain by `1 + Σ s·c`, bounded by `brain.trace.max_gain_change`.
  - Excitability effects lower the threshold.
  - Magnitudes are ASSUMPTIONs until Phase-2 calibration. Neurons not in the table are unmodulated.
- **Routes** (`config/senses/routes.yaml`, owned by 004): AKH from the corpora cardiaca, hemolymph sugar → DH44 excitability, and sex peptide. `Modulation.apply_route` is the only body→brain entry; an uncatalogued route raises `RouteError` (BRAIN-R-034). A static invariant test checks that no module outside `flycolony.brain` assigns brain state.

## 8. Outputs, taps, watchdog (BRAIN-R-017, -047, -060..062)

- **Output groups** are the I/O map's motor entries (DN and motor-neuron groups) plus neurosecretory cells by type. Their rates are exponentially filtered (`brain.out.rate_tau`) and read with `group_rates()` by 005 and 006.
- **`ObservationTaps`** accumulate, per fly:
  - activity per neuropil (primary neuropil, 79 FAFB);
  - per sensory channel;
  - per pathway (the list arrives with 010);
  - group rates;
  - trace summaries;
  - the mean weight of each plastic set;
  - focus-fly spike rasters.

  Taps hold their own counters and only read the batch, so runs with taps on and off are bit-identical (T-BRAIN-I-003). The sleep state is reported as `null` until R-045 lands.
- **Watchdog (R-047).** It checks the population rate over `brain.safety.window` against `brain.safety.max_population_rate`, emits `brain.runaway` with `action: checkpoint`, and never alters the brain. The test compares state with the watchdog firing on every window against a run where it never fires.

## 9. Time stepping (BRAIN-R-020..023)

- Reference dt = 0.1 ms.
- **Timestep gate** (`colony brain gate`). It runs the production model at each candidate dt (`brain.dt.candidates`, 0.25 and 0.5 ms; both divide the physics, senses and vision periods) on the validation assays, against the same model at 0.1 ms. A dt passes if r ≥ `brain.gate.min_corr` and the top-k overlap ≥ `brain.gate.min_top_k_overlap` on every assay, and the qualitative outcome is the same.
  - The emergence half of the gate is recorded as pending until Phase 2 defines those assays.
  - Records live in `data/templates/<id>.gates/` (the template itself is immutable) and are copied to `reports/`.
  - Each record carries a **model hash**: the registry's `brain.*` and `conn.norm.*` values plus the brain tables (receptors, plastic sets, flyvis τ). Changing any of them invalidates the gate.
- **Production refusal (R-022).** `gate.resolve_dt` refuses an ungated dt in production. `experimental` mode runs it flagged; `reference` mode is the Shiu configuration.
- **Schedule (R-023).** `Schedule.build` refuses any period that is not a whole number of brain steps. The schedule is part of `colony.yaml` (`schedule:`), and so part of the config snapshot.

## 10. State and checkpoints (BRAIN-R-070, HW-R-020)

`state_dict()` returns CPU tensors plus JSON metadata:
- membrane, synapse, refractory and graded-held state;
- gains, thresholds and plastic blocks;
- RNG keys and canonical next background events;
- the delay queue and drive;
- traces, pending releases, receptor gains and route levels;
- the step counter.

`save_checkpoint` writes safetensors. A restored batch continues bit-identically, and a GPU checkpoint restores bit-exactly on CPU (T-BRAIN-I-006, device-portability test).

## 11. Reference validation (BRAIN-R-080, -081)

- **Harness.** `tools/reference_brian2.py` runs the **unmodified** `model.py` of philshiu/Drosophila_brain_model@91bdd1e (Brian2 2.10, numpy code generation; no C++ compiler needed) on `Completeness_783`/`Connectivity_783`. It uses 30 trials of 1 s.
- **Stimuli** are the paper's own neuron lists (`config/brain/shiu2024_neurons.yaml`, extracted from `figures.ipynb`). They are FlyWire v630 root ids, and almost all are unchanged in v783: sugar 20/21, bitter 20/21, water 18/18, JO-CE 69/70. The resolver drops and reports the missing ones. The paper's "right hemisphere" is FlyWire side `L` (FAFB is mirrored).
- **Assays:**

  | Assay | Stimulus | Readout | Figure |
  |---|---|---|---|
  | sugar | sugar GRNs | MN9 | Fig. 1 |
  | sugar_bitter | sugar + bitter GRNs | MN9 suppressed | Fig. 3a |
  | water | water GRNs | MN9 | Fig. 4 |
  | jon_ce | JO-CE | aBN1 | Fig. 5 |

- Results: see §13.

## 12. Male template (BRAIN-R-082, CONN-R-031)

- **Weights (`conn.norm.male_mode`).**
  - `per_type` (default): each male neuron's input weights are scaled by its matched type's FAFB/MaleCNS mean input-synapse ratio. The ratio comes from `type_stats.in_ratio` in the match table, takes the median over female matches, and is clipped to `male_scale` ÷/× `conn.norm.male_type_clip` (4).
  - Unmatched types use the global `conn.norm.male_scale` (0.552).
  - `global` applies 0.552 everywhere.
  - Reason for the default: MaleCNS synapse detection relative to FAFB varies by region (per-type factors: 5th–95th percentile 0.29–0.87), and one global factor over-drives some circuits. Example: under `global`, JO-CE drives antennal grooming at 92 Hz in the male against 8 Hz in the female.
- **Stimuli.** The female stimuli are mapped to male neurons with the same cell types, using the MaleCNS→FlyWire match or else the same type name. They keep the same side and the same count per type.
- **Truncated readouts → mirror-image assay.**
  - Check: each mapped male readout neuron's scaled input-synapse count is compared with the female readouts' mean.
  - If it falls below `brain.male.min_readout_input_frac` (0.25), the reconstruction is treated as truncated. The assay then runs mirror-image: stimulus and readout move to the opposite side, which keeps the paper's laterality.
  - Case found: MaleCNS MN9 R has 556 input synapses, against 6,012 for MN9 L and about 5,700 for each FAFB MN9 (CB0701). Read alone, it gives 0 Hz for every gustatory assay. All three MN9 assays therefore run mirrored.
  - Side labels are *not* mirrored globally between the datasets. Mapping the sides consistently either way gives the same whole-brain comparability; only this pathway's readout is affected.
- **Report.** For each assay:
  - the readout in both sexes;
  - the expectation outcome in the male;
  - whether the assay was mirrored, and the readout completeness;
  - the cross-sex correlation of mean rates per matched (cell type, side), over pairs responsive in either sex.
- **Pass.** The expectations hold in the male, and the correlation is ≥ `brain.male.min_type_side_corr` (0.3; a side-swapped mapping scores about 0). Results: §13.

## 13. Results (2026-10-12, RTX 4000 SFF Ada)

Reports: `reports/` (one JSON per run, with model hash and pipeline version). 30 trials × 1 s per assay.

**Engine vs Brian2 (BRAIN-AC-01, T-BRAIN-V-001).** Reference mode (Shiu parameters, dt 0.1 ms, no noise or modulation) against the unmodified Shiu et al. `model.py` (Brian2 numpy codegen, philshiu/Drosophila_brain_model@91bdd1e) with the same stimulus sets. Correlation and top-50 overlap exclude the driven neurons.

| Assay | r | top-50 | Readout: engine / Brian2 (Hz) |
|---|---|---|---|
| sugar | 0.9999 | 0.98 | MN9 78.4 / 78.0 |
| sugar_bitter | 0.9998 | 1.00 | MN9 4.4 / 5.2 (suppressed) |
| water | 0.9999 | 1.00 | MN9 6.3 / 6.1 |
| jon_ce | 0.9997 | 0.98 | aBN1 50.6 / 51.1 |

**Timestep gate (BRAIN-AC-02, T-BRAIN-V-002).** Production model (graded units, background noise, neuromodulation, plastic sets; fp32) at each candidate dt against the same model at 0.1 ms. Every assay passes on both templates, so `dt_ms: null` resolves to **0.5 ms**.

| Template | dt 0.25: r / top-50 | dt 0.5: r / top-50 |
|---|---|---|
| female-fafb783-t2 | ≥ 0.9995 / ≥ 0.96 | ≥ 0.9988 / ≥ 0.84 |
| male-malecns1-t2 | ≥ 0.9984 / 0.98 | ≥ 0.9977 / 0.92 |

The emergence assays of BRAIN-R-021 arrive in Phase 2, and the gate is re-run then (G7).

**Male template (T-BRAIN-V-003).** Reference mode, `per_type` normalization, stimuli and readouts mapped as in §12. The MN9 assays run mirror-image.

| Assay | Readout: female / male (Hz) | Expectation in male | type-side r |
|---|---|---|---|
| sugar | MN9 78.4 / 139.5 | > 0 ✓ | 0.79 |
| sugar_bitter | MN9 4.4 / 0.0 | < sugar ✓ | 0.43 |
| water | MN9 6.3 / 124.0 | > 0 ✓ | 0.40 |
| jon_ce | aBN1 50.6 / 54.3 | > 0 ✓ | 0.73 |

Cross-sex notes:

- **Qualitative behaviour is preserved.** Sugar and water drive MN9, bitter vetoes it, and JO-CE drives aBN1.
- **Gustatory gain is higher in the male.** MN9 fires at 140 vs 78 Hz for sugar and 124 vs 6 Hz for water. The intact male MN9 L receives 6,012 input synapses, on the high side of the FAFB MN9s, and per-type scaling normalizes type means, not individual neurons.
- **The water gap is the largest.** In the female, water sits near MN9's threshold (6 Hz), so a modest difference in drive gives a large difference in rate.
- **Under `global` normalization**, the type-side correlations are 0.62 / 0.56 / 0.30 / 0.27 (mean 0.44, against 0.59 for `per_type`). JO-CE then also drives antennal grooming at 92 Hz (female 8 Hz).

**CPU vs GPU (BRAIN-AC-06, T-BRAIN-V-004).** The sugar assay gives bit-identical rates on CPU and CUDA: counter-based RNG and int64 fixed-point sums.

**Capacity benchmark (BRAIN-R-083, BRAIN-AC-09 for this device).** Production model, dt 0.5 ms, spontaneous activity (mean 6.7 Hz female, 5.6 Hz male). Profiles are cached under `.colony/capacity/`.

| Device | Template | 1 fly: ms/step (RTF) | Best throughput (fly-s per s) | Hard limit (VRAM) |
|---|---|---|---|---|
| RTX 4000 SFF Ada 20 GB | female | 4.2 (0.12) | 0.30 at 16 flies | 26 |
| RTX 4000 SFF Ada 20 GB | male | 5.0 (0.10) | 0.21 at 16 flies | 23 |
| Core Ultra 9 285 (CPU) | female | 12.0 (0.042) | 0.047 at 8 flies | RAM |
| Core Ultra 9 285 (CPU) | male | 17.7 (0.028) | 0.032 at 4 flies | RAM |

- **Neither device reaches real time**, even with one fly, so the soft limit is 0 and fly days are stretched (PERF-R-006).
- **GPU throughput saturates at about 16 flies.** It is about 6× the CPU.
- **Memory.** The VRAM limit uses the allocator's *reserved* memory: about 650 MB per fly (457 MB actually allocated).
- **Over-budget batches are not measured.** The benchmark stops before a batch would exceed free VRAM minus `hw.vram_reserve_frac`. On Windows (WDDM), an oversubscribed batch silently pages to system RAM: a 32-fly male batch took 344 ms/step, and its row would have produced a negative fixed cost and a false "3 flies in real time".

## 14. Capacity benchmark (HW-R-011, -012; BRAIN-R-083)

- **Command.** `colony hardware benchmark` runs spontaneous activity in the production model for growing batch sizes. It fits wall time per step `a + b·flies` and memory `fixed + per_fly·flies`, then derives the limits:
  - **hard:** VRAM minus `hw.vram_reserve_frac`, divided by per-fly memory;
  - **soft:** the number of flies that keep RTF ≥ `hw.rtf_target`.
- **Caching.** The profile is keyed by GPU, driver, CUDA and torch versions, kernel path and template ids, and cached in `.colony/capacity/`. Only FULL fidelity exists in Phase 1.
- Results: see §13.

## 15. Deviations and notes

- **Paper neuron lists.** The paper's v630 lists are used as published (see §11), not re-derived from the I/O map. Two consequences:
  - The sugar list contains LB3c/LB3b/LB3d/LB4b GRNs, and the water list includes 7 LB3c. The I/O map's modality names for LB types (from 001) are therefore coarser than the paper's selections; noted for 004.
  - MaleCNS has no FlyWire match for the LB GRN types, so the male mapping falls back to identical type names.
- **Second GPU tier (BRAIN-AC-09 / HW-AC-01).** Only the RTX 4000 Ada is available on the dev PC. The benchmark runs on any machine (`colony hardware benchmark`) and writes its profile; the second-tier numbers are added when it runs on a 4060/1650-class machine.
- **Performance.** The pure-PyTorch production model runs at 4–5 ms per 0.5 ms step for one fly on the RTX 4000 Ada (RTF ≈ 0.1; §13). Small batches are launch-bound; at 16 flies the cost is spike propagation and per-step event handling. Fused kernels (Triton/CUDA graphs) are the Phase-9 optimisation path (014), and the deterministic integer-sum design carries over to them. Until then, neural time runs about 8× slower than wall time for one fly, and each simulated fly-second costs about 3.3 s of GPU time at the best throughput (16 flies).
- **The 72 h soak and 24 neural hours of spontaneous activity (BRAIN-AC-08)** belong to the Phase-9 soak test. Phase 1 checks the watchdog mechanism and short spontaneous runs.
