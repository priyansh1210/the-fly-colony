# 004 — Senses

| Field | Value |
|---|---|
| Status | Draft — awaiting review |
| ID prefix | `SENSE` |
| Phase | 2 |
| Plan refs | §5.3, §4.3 (body→brain routes), §10.4 (blink baseline) |
| Depends on | 001 (I/O map), 002, 003 |
| Used by | 005 (closed loop), 006 (routes), 008 (reception), 010, 012, 013 (fly-eye view) |
| Constitution | CONST-1.2 (senses layer), CONST-2 (no Watcher inputs), CONST-6 |

## 1. Purpose

Turn the world at each fly's sensors into input for the real sensory neurons of its connectome. This is the fly's only window onto the world. Transduction is physical and physiological only. It never judges what matters to the fly.

## 2. Scope

**In scope:** vision (compound eyes, polarization), smell (antennae, maxillary palps), taste and contact chemistry, hearing / wind / gravity (Johnston's organ), touch and nociception, temperature and humidity, the interoceptive route catalog, the neutral baseline used by blink transfers, and the fly-eye preview export.

**Out of scope:** the fields themselves (003); the neurons' dynamics (002); how a neural response is interpreted (010).

## 3. General requirements

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| SENSE-R-001 | M | THE ENGINE SHALL compute every sensory input only from world state at the fly's sensor positions and from the fly's own body state. It never reads Watcher data, task scores, or any other fly's internal state. | T-SENSE-I-001 |
| SENSE-R-002 | M | Every sense channel SHALL map to sensory neuron groups through the I/O map (CONN-R-020), with a citation per entry. | T-CONN-U-004 |
| SENSE-R-003 | M | Each channel SHALL define its transduction as stimulus → receptor response (tuning, adaptation, noise) → sensory-neuron drive (current or rate). All parameters are in the registry. Genome sensory gains (007) apply multiplicatively. | T-SENSE-U-001 |
| SENSE-R-004 | M | Transduction SHALL NOT depend on behavioral context. The only state-dependent effects allowed are documented interoceptive routes (R-060) and genome gains. | review, T-SENSE-I-001 |
| SENSE-R-005 | M | Paired sensors (eyes, antennae, legs, labellum halves where mapped) SHALL be sampled separately, left and right. | T-SENSE-V-002 |
| SENSE-R-006 | M | THE ENGINE SHALL publish per-channel sensory summaries and per-source attribution (WORLD-R-041) on the Observation Stream. This data is read-only and never fed back into the simulation. | T-SENSE-I-002 |

## 4. Channel requirements

### 4.1 Vision

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| SENSE-R-010 | M | Each eye SHALL be a hexagonal lattice of ~750 ommatidia (count, layout and orientation from the registry, matching the flyvis lattice), rendered by GPU raycasting at 100 Hz of neural time with a ~5° acceptance angle. | T-SENSE-U-002 |
| SENSE-R-011 | M | Each ommatidium SHALL produce intensity per photoreceptor spectral class (R1–R6 broadband; R7/R8 subtypes UV, blue, green) and, in the dorsal rim area, a polarization response. | T-SENSE-U-002 |
| SENSE-R-012 | M | The rendered scene SHALL include all geometry, other flies, eggs, pupae, corpses, food, sky, sun, shadows and image panoramas, with correct occlusion. | T-SENSE-U-002 |
| SENSE-R-013 | M | Photoreceptor output SHALL feed the first-order visual neurons through the flyvis interface. Between frames, input is held or interpolated per the registry. | T-SENSE-V-004 |
| SENSE-R-014 | C | Ocelli MAY be added later. | — |
| SENSE-R-015 | M | THE ENGINE SHALL export the sampled ommatidial array of any fly as a read-only **fly-eye preview** for the dashboard (013) and the image arena (012). | T-SENSE-U-003 |

### 4.2 Smell

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| SENSE-R-020 | M | The left and right antennae and the maxillary palps SHALL sample the odor grid at their own 3D positions. | T-SENSE-V-002 |
| SENSE-R-021 | M | Olfactory receptor neuron (ORN) classes, one per glomerulus, SHALL use tuning from the DoOR database with adaptation dynamics. Odor × receptor pairs missing from DoOR are `ASSUMPTION` entries. | T-SENSE-V-003 |
| SENSE-R-022 | M | THE ENGINE SHALL include ecologically special receptors: cVA (Or67d, Or65a), CO₂ (Gr21a/Gr63a), geosmin (Or56a), plus acid- and ammonia-sensing IRs as registered. | T-SENSE-V-003 |
| SENSE-R-023 | M | ORN drive SHALL enter the template's ORN neurons, grouped by glomerulus. | T-CONN-U-004 |

### 4.3 Taste and contact chemistry

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| SENSE-R-030 | M | WHEN a contact site (labellum/proboscis, tarsi, ovipositor) touches a substance or another fly, THE ENGINE SHALL compute the local concentrations of sugars, bitter compounds, water, salts and pheromones (7-T, 7,11-HD, cVA). These drive gustatory receptor neuron classes: sugar (Gr5a/Gr64f), bitter (Gr66a), water (ppk28), pheromone (ppk23 and others as registered), salt (as registered). | T-SENSE-V-001 |
| SENSE-R-031 | M | Labellar and pharyngeal GRNs SHALL drive their neurons in the template (SEZ). Leg GRNs SHALL be handled per SENSE-OQ-01. | T-SENSE-V-001 |
| SENSE-R-032 | M | Hunger SHALL modulate GRN gains only through the catalogued routes (R-060). | T-SENSE-V-008 |

### 4.4 Mechanosensation

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| SENSE-R-040 | M | Johnston's organ SHALL respond to antennal deflection, with subgroups A/B driven by near-field sound and vibration (song) and C/E driven by sustained deflection (wind, gravity) (Kamikouchi et al. 2009). Deflection is computed from particle velocity (WORLD-R-042), wind, and gravity relative to the head. | T-SENSE-V-005, T-SENSE-V-006 |
| SENSE-R-041 | M | Body contacts and impacts SHALL drive the mechanosensory neurons present in the template. Strong impacts and noxious heat SHALL drive the nociceptive inputs present. | T-SENSE-V-009 |
| SENSE-R-042 | M | Proprioceptive and body-motion signals SHALL be handled per SENSE-OQ-01. | review |

### 4.5 Temperature and humidity

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| SENSE-R-050 | M | Arista hot and cold cells SHALL respond to changes in local air temperature, and internal warmth sensors (AC neurons) to absolute temperature above a threshold, with registry dynamics. | T-SENSE-V-007 |
| SENSE-R-051 | M | Hygrosensory neurons (dry and moist cells) SHALL respond to local humidity. | T-SENSE-V-007 |

## 5. Interoceptive route catalog (body → brain)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| SENSE-R-060 | M | THE SYSTEM SHALL keep a versioned catalog of interoceptive routes in the I/O map. Each route lists: source body variable (from 006), target neurons or traces, transfer function, time base and citation (or `ASSUMPTION`). THE ENGINE SHALL reject any route not in the catalog (BRAIN-R-033). | T-BRAIN-I-004 |

Initial catalog (to be completed in design, with every entry cited):

| Route | Body source | Target | Effect | Basis |
|---|---|---|---|---|
| Hunger → sweet taste | energy deficit | sugar GRNs | gain ↑ | Inagaki et al. 2012 |
| Hunger → bitter taste | energy deficit | bitter GRNs | gain ↓ | LeDue et al. 2016 |
| Thirst → osmolality sensing | water deficit | interoceptive SEZ neurons | activity ↑ | literature (registry) |
| Mated status | sex peptide in reproductive tract | sex-peptide sensory pathway to the brain | receptivity pathway activity ↓ | literature (registry) |
| Circadian | oscillator phase (006) | clock neuron groups | excitability | registry |
| Sleep pressure | homeostat (006) | sleep-promoting neurons (e.g. R5, dFB) | excitability ↑ | `ASSUMPTION` |
| Maturity | age since eclosion (006) | receptivity and courtship-related neurons | gating | `ASSUMPTION` |
| Egg load | ovary state (006) | egg-laying circuit | drive | `ASSUMPTION` |
| Body motion | body kinematics (003) | ascending neurons | activity | see SENSE-OQ-01 |

## 6. Neutral baseline (blink transfers)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| SENSE-R-070 | M | WHILE a blink transfer is active for a fly (012), THE ENGINE SHALL compute that fly's sensory input from a registry-defined neutral baseline scene (dark, still air, ambient odor background, no contact) for the blink duration (default ~200 ms). This is done at the sensing layer; no neuron state is ever written. | T-TASK-I-001 |

## 7. Acceptance criteria

| ID | Criterion |
|---|---|
| SENSE-AC-01 | Sugar at the labellum raises sugar-GRN drive and not bitter-GRN drive, and vice versa. |
| SENSE-AC-02 | An odor source to the fly's left drives left ORNs more than right ORNs. |
| SENSE-AC-03 | Simulated ORN tuning correlates with DoOR ≥ 0.9 across the registered odor set. |
| SENSE-AC-04 | A looming disk activates the looming-detector pathway (LPLC2) through the flyvis model and 002. |
| SENSE-AC-05 | Pulse song 2 mm away drives JO-A/B above threshold; the same song 5 cm away does not. |
| SENSE-AC-06 | Wind direction produces left/right asymmetry in JO-C/E. |
| SENSE-AC-07 | A temperature step produces the correct sign of response in hot and cold cells. |
| SENSE-AC-08 | A hungry fly's sugar-GRN response exceeds a sated fly's for the same stimulus. |
| SENSE-AC-09 | A static audit plus a runtime probe confirms no sensory input comes from outside the world and body. |
| SENSE-AC-10 | Vision renders 100 flies × 2 eyes at 100 Hz within the budget set in 014. |

## 8. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-SENSE-U-001 | unit | Transduction functions, adaptation, genome gains. |
| T-SENSE-U-002 | unit | Raycast renderer against known scenes (lattice, spectra, polarization, occlusion). |
| T-SENSE-U-003 | unit | Fly-eye preview equals the sampled input. |
| T-SENSE-V-001 | validation | Taste channels. |
| T-SENSE-V-002 | validation | Lateralization of smell and taste. |
| T-SENSE-V-003 | validation | DoOR tuning and special receptors. |
| T-SENSE-V-004 | validation | Looming → LPLC2 through flyvis. |
| T-SENSE-V-005 | validation | JO response to song vs distance. |
| T-SENSE-V-006 | validation | JO response to wind and gravity. |
| T-SENSE-V-007 | validation | Thermo- and hygrosensation. |
| T-SENSE-V-008 | validation | Hunger → GRN gain route. |
| T-SENSE-V-009 | validation | Touch and nociception. |
| T-SENSE-I-001 | invariant | No forbidden inputs (`import-linter` + runtime probe). |
| T-SENSE-I-002 | invariant | Attribution data never feeds back into the simulation. |
| T-SENSE-P-001 | perf | Vision render throughput (~15M rays/s for 100 flies). |

## 9. Assumptions and open questions

| ID | Question | Proposal |
|---|---|---|
| SENSE-OQ-01 | **v1 templates are brain-only.** Leg taste (critical for courtship tapping), leg touch, proprioception and the sex-peptide pathway all start in the ventral nerve cord (VNC) and reach the brain only through ascending neurons. How do we drive them? | Drive the relevant ascending neurons from a documented, cited mapping of body state ("synthetic VNC relay"), each flagged `ASSUMPTION`, and replace the relay with the real VNC in v2. Start with the minimum set: leg pheromone taste, leg sugar taste, walking state, sex-peptide pathway. |
| SENSE-OQ-02 | Vision frame rate (100 Hz) vs photoreceptor dynamics and the flyvis integration step. | Keep 100 Hz rendering with interpolation; validate the looming response. Raise the rate only for chambers if needed. |
| SENSE-OQ-03 | Final odorant list. | Shared with WORLD-OQ-01. |
| SENSE-OQ-04 | Definition of the neutral baseline for blinks. | Darkness at the current night level, still air, background odor. Verified by the 012 invisibility test. |
| SENSE-OQ-05 | Converting uploaded RGB images to UV/blue/green photoreceptor channels. | Documented approximation (`ASSUMPTION`). See TASK-OQ-05. |
