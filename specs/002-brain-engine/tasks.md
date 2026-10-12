# 002 — Brain Engine: Tasks

| Field | Value |
|---|---|
| Status | Phase 1 (simulator and validation) |
| Design | [design.md](design.md) |

Ordered work. Each task names the requirements it implements and the tests that prove it. `[x]` = done and its tests pass. Plasticity rules are scheduled by the spec for Phases 2–4 (section G).

## A. Engine core

- [x] **A1** Registry `config/params/brain.yaml`: Shiu et al. LIF/synapse values with citations; noise, graded, trace, gate, numerics and safety entries (ASSUMPTIONs flagged). *BRAIN-R-010, -011, -013*
- [x] **A2** Exact propagators and Brian2 step rounding (refractory `timestep()`, delays rounded half up). *BRAIN-R-010, -011, -020* · T-BRAIN-U-004
- [x] **A3** Counter-based per-fly RNG (int64 hash, device-independent). *BRAIN-R-013, -055*
- [x] **A4** Shared topology per template/device/variant, signs from the template, male weight normalization. *BRAIN-R-002, -012, CONN-R-031*
- [x] **A5** `BrainBatch`: Brian2 schedule, refractory write-block, event-driven delivery, int64 fixed-point sums, Poisson drive on sensory neurons only, background noise in event blocks. *BRAIN-R-010..013, -016, -050, -051, -054* · T-BRAIN-U-004, -005, T-BRAIN-P-002
- [x] **A6** Individuality (`FlyBrainSpec`: pre/post gains, threshold/rest offsets) and per-fly plastic blocks overriding shared weights. *BRAIN-R-001, -003, -004* · T-BRAIN-U-001, -002, -003
- [x] **A7** Add/remove flies mid-run without perturbing others (queue/event re-addressing). *BRAIN-R-005, -055* · T-BRAIN-I-002
- [x] **A8** Graded units: flyvis types + registry list (APL), per-type flyvis time constants (`tools/gen_flyvis_params.py`, 50-model ensemble), rate-equivalent coupling held at 1 kHz. *BRAIN-R-014, -015, BRAIN-OQ-02* · T-BRAIN-U-006

## B. Modulation, routes, outputs, observation

- [x] **B1** Amine and peptide traces (dual exponential, regional by output fraction, neurosecretory → global, normalised units). *BRAIN-R-030, -031, BRAIN-OQ-03* · T-BRAIN-U-010
- [x] **B2** Versioned receptor table with cited entries; bounded gain and excitability effects. *BRAIN-R-032* · T-BRAIN-U-011
- [x] **B3** Interoceptive route catalog (`config/senses/routes.yaml`, owner 004) and `apply_route` as the only body→brain entry; static check that nothing else writes brain state. *BRAIN-R-033, -034* · T-BRAIN-U-011, T-BRAIN-I-004
- [x] **B4** Filtered DN/motor/neurosecretory group rates from the I/O map. *BRAIN-R-017* · T-BRAIN-U-007
- [x] **B5** Read-only observation taps (neuropil, sensory channel, pathway, groups, traces, plastic summaries, focus raster). *BRAIN-R-060..062* · T-BRAIN-U-017, T-BRAIN-I-003
- [x] **B6** Runaway watchdog: `brain.runaway` event + checkpoint request, never alters the brain. *BRAIN-R-047 (detection)* · T-BRAIN-I-005

## C. Time stepping and state

- [x] **C1** Multi-rate integer schedule in `colony.yaml`. *BRAIN-R-023* · T-BRAIN-U-009
- [x] **C2** Timestep gate records with model hash; production refuses an ungated dt; experimental flag. *BRAIN-R-021, -022* · T-BRAIN-U-008
- [x] **C3** Checkpoint/restore of the complete state (portable CPU tensors, safetensors), bit-identical continuation, GPU→CPU restore. *BRAIN-R-070, HW-R-020* · T-BRAIN-I-006
- [x] **C4** Determinism: bit-identical runs on CPU and GPU; event-block size independence. *BRAIN-R-054* · T-BRAIN-I-001

## D. Validation (Phase-1 gate)

- [x] **D1** Brian2 reference harness running the unmodified Shiu et al. `model.py` (numpy codegen) with the paper's own v630 neuron lists (`config/brain/shiu2024_neurons.yaml`). *BRAIN-R-080*
- [x] **D2** Engine vs Brian2 on sugar, sugar×bitter, water and JO-CE (r ≥ 0.9, top-k overlap, expectations). r ≥ 0.9997. *BRAIN-R-081, BRAIN-AC-01* · T-BRAIN-V-001
- [x] **D3** Timestep gate for the production model, both templates: dt 0.5 ms passes (fixed a batch↔modulation reference cycle that leaked GPU memory across assays). *BRAIN-R-021, BRAIN-AC-02* · T-BRAIN-V-002
- [x] **D4** Male-template assays and cross-sex comparability: per-type weight normalization (`conn.norm.male_mode`), mirror-image assay for the truncated MaleCNS MN9 R, male timestep gate on mapped stimuli. *BRAIN-R-082* · T-BRAIN-V-003
- [x] **D5** CPU vs GPU agreement (bit-identical sugar assay). *BRAIN-R-053, BRAIN-AC-06* · T-BRAIN-V-004

## E. Performance and capacity

- [x] **E1** Capacity benchmark (`colony hardware benchmark`): step-time and memory fits, hard/soft limits, cached profile. *HW-R-011, -012* · T-BRAIN-P-001
- [x] **E2** Benchmarks recorded for CPU and this GPU (design §13). The benchmark now stops before oversubscribing free VRAM and fits only in-memory rows. *BRAIN-R-083*
- [ ] **E3** Second GPU tier (GTX 1650 / RTX 4060 class). Blocked: no such GPU on the dev PC; run `colony hardware benchmark` there and commit the profile. *BRAIN-AC-09, HW-AC-01*

## F. Phase-1 gate

- [x] **F1** All Phase-1 acceptance criteria green (AC-01..06, AC-09 for the available device); reports in `reports/`. AC-09's second GPU tier stays open (E3).

## G. Later phases (scheduled by the spec)

- [ ] **G1** MB dopamine-gated KC→MBON rule per compartment (MB compartments from DAN/MBON types). *BRAIN-R-040, -046* · T-BRAIN-U-012 (Phase 2–4)
- [ ] **G2** Ring→EPG Hebbian rule. *BRAIN-R-041* · T-BRAIN-U-013
- [ ] **G3** Homeostatic intrinsic plasticity (life-clock time). *BRAIN-R-042* · T-BRAIN-U-014
- [ ] **G4** Sleep state and downscaling. *BRAIN-R-043, -045* · T-BRAIN-U-015
- [ ] **G5** R-STDP research option (set defined, off by default). *BRAIN-R-044* · T-BRAIN-U-016
- [ ] **G6** 24 neural hours spontaneous / 72 h soak. *BRAIN-AC-08* (Phase 9 soak)
- [ ] **G7** Timestep gate re-run with the Phase-2 emergence assays. *BRAIN-R-021*
