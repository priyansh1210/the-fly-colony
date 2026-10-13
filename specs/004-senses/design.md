# 004 — Senses: Design (Phase 2 scope)

| Field | Value |
|---|---|
| Status | Phase 2 design, 2026-10-13 |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |

## 1. Modules

```
src/flycolony/senses/
  layout.py      SensoryLayout: per template, every driven neuron and graded photoreceptor with its channel
  transduce.py   shared transfer functions: Hill, adaptation (first-order), noise-free; genome gains
  taste.py       contact chemistry → GRN rates
  smell.py       odor samples → ORN rates (DoOR tuning, adaptation)
  mechano.py     Johnston's organ (wind, gravity), head bristles (impacts)
  thermo.py      arista hot/cold cells, hygro dry/moist cells
  vision.py      eye lattice, ray caster, photoreceptor spectral responses, column mapping
  intero.py      interoceptive routes that act at the sensory layer (gain routes) + relay hooks
  senses.py      SenseBatch: runs the channels on the schedule, produces engine input, summaries
```

- **Isolation (SENSE-R-001, T-SENSE-I-001).** `senses` may import only `world`, `body`, `brain.select`, `registry` and `config`. It never imports `watcher`, `tasks`, physiology internals or another fly's brain. The import contract is added to `pyproject.toml`, and `tools/lint.py` checks it.
  - Each channel function receives the world group, the body batch and the fly's own state, and nothing else.
  - The runtime probe (T-SENSE-I-001) runs a step under a tracing wrapper that fails on reads of any other object.

## 2. Engine input path (engine extension)

The Phase-1 drive API (`BrainBatch.set_drive`) rebuilds Python tables on every call and pre-draws Poisson events for constant rates. Closed-loop sensing changes rates every millisecond, so the engine gains a vectorized sensory input:

- **Layout.**
  - `SensoryLayout` lists, per template, the Poisson-driven sensory neurons (all I/O-map `sense` groups except photoreceptors) and the graded photoreceptor units.
  - It is registered once with `BrainBatch.attach_senses(layout)`.
  - Driving a non-sensory neuron raises at attach time, as in BRAIN-R-016.
- **Rates.**
  - Each senses step writes a rate tensor `[B, n_driven]` (Hz).
  - The brain draws one Bernoulli event per driven neuron and step with p = rate·dt. It uses the counter-based RNG (`STREAM_DRIVE`, keyed by fly seed, neuron and step), so results stay device- and batch-independent (BRAIN-R-054/055).
  - At about 5k driven neurons per fly, that is 5k uniform draws per fly per step.
- **Photoreceptors.**
  - Each vision step writes a graded input `[B, n_photo]` (mV, depolarisation from rest). It is added to the graded units' input like the graded coupling; between frames it is held or linearly interpolated (registry `senses.vision.interp`, SENSE-R-013).
  - No neuron state is ever written directly.
- **Compatibility.** `set_drive` remains for the Phase-1 assays and the motor harness. A neuron is driven by either the layout or `set_drive`, never both.

## 3. Taste (SENSE-R-030..032)

- **Inputs.** For each contact site touching a drop (003 §6.4), the drop composition gives tastant concentrations: sucrose (mol/L), bitter (denatonium-equivalent mol/L), salt (NaCl mol/L), and osmolality for water sensing.
- **Classes.** Labellar GRN classes map to I/O groups:

  | Class (receptor) | I/O group | Stimulus |
  |---|---|---|
  | sugar (Gr5a/Gr64f) | `taste.labellar.sugar` | sucrose |
  | bitter (Gr66a) | `taste.labellar.bitter` | bitter |
  | water (ppk28) | `taste.labellar.water` | low osmolality |
  | low salt (Ir56b/Ir94e-like) | `taste.labellar.sugar_low_salt` | NaCl, low range |
  | high salt (Ppk23/Gr66a high salt) | `taste.labellar.high_salt_heavy_metal` | NaCl, high range |
  | glutamate | `taste.labellar.glutamate` | (Phase 4 food chemistry) |

- **Transfer.** `rate = r_spont + gain_hunger · r_max · c^n / (c^n + EC50^n)`, then first-order adaptation toward a fraction of the onset response.
  - Parameters in `config/params/senses.yaml` with citations: Hiroi et al. 2002 and Dahanukar et al. 2007 (sugar dose responses); Meunier et al. 2003 (bitter); Cameron et al. 2010 (ppk28 water).
  - The water cell is inhibited by osmolality with a registry half-point.
- **Laterality (SENSE-R-005).** Left and right labellar GRNs are split by the template's `side` and sampled from the two labellum halves, which sit a registry half-width apart.
- **Hunger route (SENSE-R-032).** The gains come only from catalogued routes `hunger_sweet` (Inagaki et al. 2012: gain ↑ with energy deficit) and `hunger_bitter` (LeDue et al. 2016: gain ↓).
  - These are `kind: sensory_gain` entries in `config/senses/routes.yaml`, read by `intero.py`.
  - Their source is the physiology energy deficit (the minimal Phase-2 energy model in 006).

## 4. Smell (SENSE-R-020..023)

- **Tuning (SENSE-R-021, -022).**
  - The DoOR 2.0 consensus response matrix (Münch & Galizia 2016; DoOR.data, CC BY-SA 4.0) gives a response per receptor and odorant in [0, 1].
  - DoOR's receptor → glomerulus mapping assigns each receptor to an I/O group `olfaction.orn.<glomerulus>`.
  - `tools/gen_door_tuning.py` converts the dataset to `config/senses/door_tuning.yaml` (receptor, glomerulus, odorant, response, source), with the CC BY-SA notice.
  - Pairs missing from DoOR for the 12 world odorants are `ASSUMPTION` entries (0 unless cited).
  - Special receptors come from their own citations: cVA (Or67d → DA1, Or65a → DL3); CO₂ (Gr21a/Gr63a → V); geosmin (Or56a → DA2); ammonia and acids (Ir92a → VM1; Ir64a → DC4/DP1m).
- **Transfer.** Per glomerulus g and antenna a:
  - `x_g = Σ_odor R[g, odor] · h(c_odor(a))`, with `h(c) = c^n/(c^n + EC50^n)` and EC50 per odor species (registry);
  - `rate = r_spont[g] + r_max · x_g / (1 + x_g) − adaptation`;
  - adaptation is a first-order variable with τ = `senses.smell.adapt_tau_ms` (Nagel & Wilson 2011).
- **Sampling.**
  - Antennae sample the odor grid at their own 3D positions: trilinear interpolation, head ± lateral offset.
  - ORNs are split by `side`. FAFB ORN `side` is the antenna side; the bilateral projection of ORNs to both antennal lobes is in the connectome, not in the transduction.
  - Palp glomeruli (VA4, VC1, VC2, VM7d, VA7l, 1 per DoOR mapping) sample at the palp position.
- **Acceptance.** `T-SENSE-V-003` checks that simulated tuning reproduces the DoOR matrix (r ≥ 0.9, SENSE-AC-03) at the reference concentration.

## 5. Mechanosensation (SENSE-R-040, -041)

- **Johnston's organ, sustained deflection (C/E).** The air velocity relative to the head (wind at the head minus body velocity) is projected on each antenna's sensitive axis (registry angles), and gravity is projected on the same axis.
  - Deflection `δ = k_air · v_rel + k_g · g_axis`.
  - JO-C neurons respond to one sign of δ, and JO-E neurons to the other. They are split by cell type prefix (`JO-C*`, `JO-E*`) within `mechano.jo.wind_gravity`.
  - Rate is a rectified Hill function of |δ| with slow adaptation (Yorozu et al. 2009; Mamiya & Dickinson 2015). The left/right antenna asymmetry for oblique wind gives SENSE-AC-06.
- **JO-A/B (sound).** Driven by near-field particle velocity (Phase 5, WORLD-R-042). In Phase 2 they receive the high-pass part of δ, which is zero in steady wind.
- **Head bristles.** A head contact or impact above a threshold gives a brief rate pulse to the bristle neurons of that side (`touch.head_bristle`). Nociceptive inputs are not in the brain-only template (SENSE-OQ-01).

## 6. Temperature and humidity (SENSE-R-050, -051)

- **Arista cells.** Hot and cold cells (I/O groups for the arista thermo cells, Marin et al. 2020) respond to the rate of change of local air temperature: a phasic response with a registry τ, of opposite sign for hot and cold (Gallio et al. 2011; Budelli et al. 2019).
- **Hygro cells.** Dry and moist cells respond tonically to relative humidity with opposite slopes (Enjin et al. 2016; Knecht et al. 2017).
- **AC neurons** (internal warmth) are not in the I/O map. Flagged; added when mapped.
- **Group names.** The I/O groups are named as Marin et al. classify them. Their assignment to hot/cold/dry/moist/evaporative-cooling transduction is a table in `config/senses/channels.yaml` with citations.

## 7. Vision (SENSE-R-010..015)

### 7.1 Eye model

- **Lattice.** Each eye is a hexagonal lattice of `senses.vision.n_ommatidia` columns (721, the flyvis extent-15 lattice, Lappalainen et al. 2024), with inter-ommatidial angle Δφ = 4.6° (Land 1997; registry). Hex coordinates (u, v) map to viewing directions by an azimuthal-equidistant projection around the eye's centre direction (registry azimuth ±(75°), elevation 0°; `ASSUMPTION`).
- **Acceptance.** Each ommatidium integrates a Gaussian acceptance function of half-width Δρ = 5° (Götz 1964), sampled with 7 rays per ommatidium (centre + hexagon at Δρ/2, Gaussian weights; registry).

### 7.2 Ray casting (SENSE-R-012)

- **Implementation.** Analytic ray–primitive intersection in batched torch (no mesh): arena surfaces (cylinder, box), discs (food, water), other flies (ellipsoids), looming disks on the sky, and the sky dome beyond the arena.
- **Rays.** 2 eyes × 721 × 7 ≈ 10k rays per fly per frame. At 100 Hz for 100 flies that is 1.0e8 rays/s. Analytic intersection with fewer than 20 primitives keeps this inside the 014 budget; it is measured in T-SENSE-P-001.
- **Radiance per hit, in three spectral channels (UV, blue, green):**
  - surfaces: illuminance × albedo(texture) per channel;
  - sky: the gradient of 003 §4.3, with the e-vector and degree of polarization;
  - looming disk: the dark disk albedo.
- **Spectral classes.** Photoreceptor classes combine the channels with sensitivity weights (registry: R1–6 broadband; R7p UV, R7y UV, R8p blue, R8y green; Salcedo et al. 1999; Sharkey et al. 2020).
- **Dorsal rim.** Dorsal-rim ommatidia (top rows of the lattice, registry count) give a polarization-sensitive response from the e-vector at their direction (Labhart & Meyer 1999).

### 7.3 Photoreceptor transduction

- **Response.** Each photoreceptor's graded input is a log-compressive, adapting response (Juusola & Hardie 2001): `x = log(I / I_adapt)`, where I_adapt follows I with τ = `senses.vision.adapt_tau_ms`, mapped to mV by a registry gain and clipped.
- **Darkness** gives the hyperpolarised floor, which is how night reaches the brain (MOTOR-AC-05).

### 7.4 Ommatidium → photoreceptor neuron mapping

Driving the template's photoreceptor neurons (`vision.photoreceptor.r1_6`, `.r7`, `.r8`, `.dorsal_rim`) with their own ommatidium's signal needs each neuron's eye position.

- **Full mode (column map present).**
  - FlyWire's visual-column assignment (Matsliah et al. 2024, Codex "Visual Neuron Columns", `data/raw/flywire_columns/`) gives each columnar neuron its column and hex coordinates.
  - R7 and R8 map to their column's ommatidium.
  - R1–R6 map to the ommatidium of the cartridge they innervate. Neural superposition is simplified to the same column (`ASSUMPTION`; the true ±1-column offsets are a later refinement).
  - The template's hex coordinates are registered to the model lattice by matching the equator and the anterior–posterior axis. The registration and the share of photoreceptors that get a column are reported.
- **Luminance mode (no column map).** Each eye's photoreceptors of a spectral class receive that eye's mean response for the class. There is no spatial vision. The looming gate (MOTOR-AC-03) cannot pass in this mode, and gate reports state the mode.
- **Missing columns.** Photoreceptors with no column (unassigned, or the left optic lobe if the assignment is right-only) use their eye's luminance mode, and the report counts them.

### 7.5 Fly-eye preview (SENSE-R-015)

`vision.preview(fly)` returns the sampled `[2, 721, classes]` array and the lattice coordinates: a read-only copy of what was fed to the brain (T-SENSE-U-003).

## 8. Interoceptive routes and the synthetic VNC relay

- **Routes.**
  - Routes that act at the sensory layer (`sensory_gain`) are applied in `intero.py`. Routes that act on brain excitability (sleep pressure → dFB; circadian) go through `brain.modulation.apply_route` (BRAIN-R-033).
  - Phase-2 entries:
    - `hunger_sweet`, `hunger_bitter` (sensory gain);
    - `sleep_pressure` → dFB / R5 (excitability ↑, `ASSUMPTION`, Donlea et al. 2014; Liu et al. 2016).
- **Synthetic VNC relay (SENSE-OQ-01).** Phase 2 adds the relay mechanism with its first entry. Walking state (|forward speed|) drives ascending neurons of walking-related types from a cited list, flagged `ASSUMPTION` (Chen et al. 2023 for ascending neuron classes). Leg taste and the sex-peptide pathway are Phase-5 entries.

## 9. Observation output (SENSE-R-006)

- Each senses step, `SenseBatch.summary()` returns per-channel means per fly and per side, plus source attribution for odor (WORLD-R-041). It goes to the stream as read-only CPU copies.
- A test checks that bit-identical runs result with the summary on and off (T-SENSE-I-002).

## 10. Registry (`config/params/senses.yaml`) and tables

- All transfer parameters above are registry entries.
- `config/senses/channels.yaml` maps channel → I/O group → transduction class, with citations.
- `config/senses/door_tuning.yaml` is generated, never hand-edited.

## 11. Deviations and notes

- **Noise.** Transduction is noise-free. Poisson spiking of the driven neurons supplies the variability, as in Shiu et al.
- **Legs.** Leg GRNs and leg touch are VNC inputs, absent in v1 templates. They enter through the relay (Phase 5 for taste).
- **Ocelli** are omitted (SENSE-R-014, C).
