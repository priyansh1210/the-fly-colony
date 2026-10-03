# The Fly Colony: Master Plan (Spec-Driven Development)

## 0. Context

`D:\the-fly-colony` is empty (no code, not a git repo). You want a virtual world containing a colony of **100 fruit flies** (70 male, 30 female). Each fly is controlled only by a simulated real fruit-fly brain, meaning the connectome (the complete neuron-by-neuron wiring map). No behaviors are hard-coded. The flies live on a compressed clock (1 real hour = 1 fly day). They feel, talk (fly-style), fight, mate and have babies, and they are given tasks.

A hidden **Watcher** observes everything while it is awake and writes a timestamped record of what every fly does, signals, "thinks" and feels into `/flies`. When the Watcher sleeps, the colony sleeps. You control the Watcher, and the Watcher controls the environment (time scale, weather, food, puzzles, spawning). The flies must never be able to detect the Watcher.

This file is the master plan. Following spec-driven development (SDD), the first step after approval is writing the **constitution + spec files**, not code.

### Decisions locked in (from our Q&A)
| Topic | Decision |
|---|---|
| Minds | **Real connectome brains only.** Tasks are physical puzzles and image tasks built into the world. The Watcher can place any fly into any puzzle or image chamber. "Speech" means real fly signals (song, pheromones, displays) that the Watcher translates. Feelings are decoded from neural activity. |
| Life | **Full life cycle** (egg → larva → pupa → adult → aging → death). The Watcher can also **spawn N flies** on demand. |
| Hardware | Planned rig: **RTX 4060 + 56 GB RAM** (the laptop, GTX 1650 4 GB / 8 GB RAM, is for development). See §16. An RTX 4060 has 8 GB of dedicated VRAM. A "20 GB" figure in Windows includes shared system RAM, which is too slow to help. |
| Watcher voice | **Local LLM**, model not chosen yet. The plan uses a pluggable runtime and an evaluation harness to pick one. The LLM lives only inside the Watcher. It never touches a fly's brain. |

---

## 1. Reality check: what is real vs. interpreted

| You asked for | What the system will actually do |
|---|---|
| "Only the fly neuron brain, no hard-coding" | Every decision comes from simulated connectome neurons. Non-neural code is limited to **physics, senses (world → sensory neurons), muscles (motor neurons → body movement) and body chemistry**. The rule: *the mind decides, the body executes.* |
| "They build themselves" | Brains change through biologically real **plasticity**: mushroom-body learning gated by dopamine, compass learning in the central complex, homeostasis, and sleep-dependent downscaling. Colonies change through **evolution**: babies inherit a genome from both parents plus mutations, and survival/mating decide which genes spread. At about 12–14 real hours per generation, you can watch evolution over days. |
| Solve DSA problems | Flies can't read. DSA problems are **embodied in the world**: a maze is graph search, a multi-route maze is shortest path, food patches with random rewards are a multi-armed bandit, visiting 5 patches is a TSP. The Watcher solves each puzzle with the real algorithm and scores the fly against the optimum. Some puzzles will exceed what a fly can do, and that is a valid result. |
| Feelings (happy, sad, frustrated, love, hate) | Flies have measurable internal states: persistent, scalable, with positive or negative valence (so-called "emotion primitives"). The Watcher **decodes** these from dopamine, serotonin, octopamine, neuropeptide and drive-circuit activity, then labels them in English with the evidence and a confidence. The labels belong to the Watcher; the flies have no words. |
| Speak / communicate | Real fly channels: **courtship song** (pulse and sine wing song), **aggression sounds**, **pheromones** (cVA, 7-T, 7,11-HD), **touch** (tapping, boxing), and **visual displays** (wing threat, female rejection signals). The Watcher "hears" every signal and translates it into English, for example "I'm courting you" or "Back off". |
| Think | "Thoughts" are decoded neural states: what the fly is sensing, which drive dominates, which memory is being recalled, and which action is ramping up before it happens. They are logged as interpreted inner monologue and marked `interpreted: true`. |
| Research risk | Whole-brain spiking models are research-grade. Under 1% of cell types have measured physiology, and about 57% of a plain LIF brain stays silent because the optic lobe uses graded, non-spiking signals. Mitigations: a hybrid graded/spiking model, a connectome-constrained visual model, and **global** parameter calibration (never behavior scripts). Every phase has emergence gates. Some behaviors may emerge weakly or not at all. |

---

## 2. Constitution (non-negotiable rules → `specs/000-constitution.md`)

1. **Neuron-only minds.** No behavior trees, state machines, scripted reactions or LLMs inside any fly. A code review fails if non-brain code chooses an action.
2. **Watcher invisibility.** No fly-perceivable channel originates from the Watcher: no object, shadow, sound, odor or neural stimulation. Observation must not disturb the colony. This is proven by a determinism test: a run with the Watcher attached is bit-identical to a run without it. Watcher interventions are **environmental only** and **naturalized** (§10.1).
3. **Total observability while awake.** Every event carries three timestamps. **Nothing happens while the Watcher sleeps** because the world is suspended.
4. **Chain of command.** You → Watcher → Environment. Nothing else can change the world. Every intervention is audited.
5. **Reproducibility.** Seeded RNG, a deterministic engine, versioned connectome templates, and checkpoints you can restore or branch.
6. **Biological grounding.** Every parameter lives in a Parameter Registry with a source citation or an `ASSUMPTION` flag.
7. **Honest interpretation.** Every decoded feeling, thought or translation stores its evidence (the neural signals behind it) and a confidence value.

---

## 3. System architecture

```
 YOU ── CLI / Web Dashboard / chat ──► WATCHER (process B, CPU)
                                        │  Observer · Behavior classifier · Mind decoder
                                        │  Translator · Narrator · Chronicle · Controller · Scheduler
                                        │         ▲ ─────── local LLM server (process C, CPU) ───────┘
       Environment Control API          │         │
   (world-level commands ONLY; schema   ▼         │ one-way, read-only Observation Stream
    cannot address neurons)      ENGINE (process A, GPU)   (shared-memory ring buffer)
                                 World (Dome + Chambers) · Bodies · Senses · Brains (batched)
                                 Physiology · Clocks · Checkpointer
 WATCHER writes ► /flies (per-fly records) · /watcher (its own journal + intervention audit)
```
- The Engine **publishes** observations and **accepts only** world-level commands. Its modules cannot import the Watcher; this is enforced by an `import-linter` contract.
- The Watcher never writes into engine state, except through the Control API, which is validated by a schema.

---

## 4. The brain: neuron-only minds

### 4.1 Connectome templates (one per sex)
| Sex | v1 template (brain only, readout at descending neurons) | v2 (full CNS, with a FlyGym body) |
|---|---|---|
| ♀ Female | **FlyWire FAFB v783** (139,255 neurons, ~54.5M synapses). The same dataset as the validated Shiu et al. 2024 model. | **BANC** (~188k neurons, brain + nerve cord, 199M synapses) |
| ♂ Male | **MaleCNS v1.0** brain portion (the full CNS has 166.7k neurons; it includes male-specific types such as P1) | MaleCNS v1.0 full CNS |

- Phase 0 converts each dataset into a **BrainTemplate** containing:
  - a neuron table: id, cell type, class, side, neuropil, predicted neurotransmitter, and a spiking-or-graded flag
  - a CSR edge list with weight = synapse count × sign
  - an **I/O map**: sensory neuron groups ↔ sense channels, and descending-neuron groups ↔ motor primitives
  - neuropil membership, used for logging and visualization
- Stored as safetensors + Parquet with checksums and a version manifest. **Check data licenses in Phase 0**; non-commercial terms may apply.
- Weights from the two datasets are normalized so the same assays behave comparably in both sexes. Cross-dataset cell-type matches come from the MaleCNS↔FlyWire comparison.

### 4.2 Neuron and synapse model (hybrid)
- **Central brain:** leaky integrate-and-fire (LIF) neurons with α/exponential synapses and a uniform synaptic delay, starting from Shiu et al. defaults.
  - Sign by neurotransmitter: ACh is excitatory; GABA and glutamate (mostly) are inhibitory.
  - Background Poisson noise supplies spontaneous activity.
- **Optic lobe and other non-spiking neurons:** graded-potential rate units. Parameters are initialized from **flyvis**, the connectome-constrained visual model of Lappalainen et al. 2024, where it applies.
- **Timestep:** 0.1 ms in the reference simulation. The production timestep (target 0.25–0.5 ms) is chosen only after it matches the reference within tolerance (a gate test).
- **GPU kernels:**
  - Event-driven spike propagation over a **shared topology** per sex.
  - Individuality is expressed as per-fly per-neuron **pre/post gain vectors**, so the effective weights for fly *f* are `diag(g_f)·W·diag(r_f)`. This keeps the big matrix shared across the whole batch.
  - Plastic synapses are stored per fly as small separate blocks.

### 4.3 Neuromodulation and internal states
- Modulatory neurons fire spikes like any other neuron. Their spikes feed slow **concentration traces** per compartment or neuropil for:
  - dopamine (DA)
  - serotonin (5-HT)
  - octopamine (OA)
  - neuropeptides: NPF, sNPF, Tk, DH44, AKH, insulin-like peptides, Crz, sex peptide (SP) signaling
- These traces modulate target neurons' gain and gate plasticity, using a receptor-expression table by cell type (Fly Cell Atlas; `ASSUMPTION` where missing).
- Body state reaches the brain only through documented physiological routes:
  - hunger changes the gain of sugar and bitter taste neurons
  - mating status reaches the female brain through sex-peptide sensory neurons
  - the circadian clock sets clock-neuron excitability

### 4.4 Plasticity ("building themselves")
| Where | Rule | Gives the fly |
|---|---|---|
| Mushroom body KC→MBON synapses | Dopamine-gated depression/potentiation (Hige 2015, Cohn 2015-style rules) | Learning odors, places and contexts as good or bad |
| Central complex ring→EPG synapses | Hebbian mapping of visual scenes to heading | Its own compass and place memory |
| All spiking neurons | Slow homeostatic intrinsic plasticity | Long-run stability, so there is no runaway activity |
| During sleep | Synaptic downscaling + consolidation | Sleep has a real function |
| Optional flag (off by default) | Reward-modulated STDP in the lateral horn / SMP | A research experiment |

### 4.5 Individuality, personality and genome
- **Genome:** about 200–400 "genes". Each gene scales a biological knob:
  - neuromodulator tone (DA, 5-HT, OA)
  - excitability of cell-type groups, e.g. courtship-drive P1/pC1, aggression Tk/P1a, sleep dFB
  - sensory gains per sense
  - mushroom-body learning rate and homeostatic set-points
  - body size, metabolic rate, lifespan factor, fecundity, circadian phase
- **Developmental noise:** a per-fly seeded jitter on neuron thresholds and gains, plus left–right asymmetry. This matches real fly individuality, such as handedness from wiring asymmetry. The noise is **not** inherited exactly.
- **Personality presets:** "assigning" a personality biases the genome, never behavior.
  - The presets: Bold Explorer, Shy Homebody, Aggressive Fighter, Gentle Pacifist, Social Butterfly, Loner, Quick Learner, Slow & Steady, Romantic (high courtship drive), Picky (female, high rejection threshold), Night Owl, Glutton.
  - Each preset is a documented set of gene offsets. You can edit `config/genesis.yaml`.
- **Measured personality:** the Watcher runs passive "assays" continuously on each fly: activity, exploration, boldness, sociability (nearest-neighbor distance), aggression rate, courtship intensity, handedness, learning speed, and sleep amount. Profiles show **assigned vs. expressed** personality.
- **Inheritance:** a baby's genome is a per-gene crossover of both parents plus Gaussian mutation (rate is a Watcher knob), and the baby gets fresh developmental noise. Memories are not inherited.

### 4.6 Fidelity levels (per fly, switchable by the Watcher)
| Level | What runs | Use |
|---|---|---|
| **FULL** | Every neuron | Focus flies, puzzle subjects, strong GPUs |
| **HYBRID** | Neuron-level mushroom body, central complex, sensory and descending/motor pathways. The rest is cell-type-level rate units (about 8–11k types). | Lets 100+ flies keep 1 real hour = 1 fly day on an RTX 4060 |
| **COARSE** | All cell-type level, except the mushroom body and central complex | Laptop development and CI tests |

Learned memories live in the mushroom body and central complex, which are neuron-level at every fidelity. So promoting a fly from HYBRID to FULL when the Watcher focuses on it keeps its memories. HYBRID and COARSE must pass the same emergence gates, and each fly's logs record which fidelity it ran at.

---

## 5. The body and the world

### 5.1 The Colony Dome (main world)
- **Size:** a 50 cm diameter floor, 30 cm high, like a real population cage. A fly is about 2.5 mm long and walks 1–3 cm/s, so crossing the dome takes about 25 s.
- **Zones:**
  - **Orchard:** fruit patches that ripen → ferment → rot, each stage changing its odor profile (ethanol, acetic acid, ethyl acetate), plus yeast for protein, which females need for eggs.
  - **Water springs.**
  - **Nursery:** egg-laying substrate where larvae develop; pupae sit on the walls.
  - **Perches:** leaves and branches for resting and night.
  - **Open plaza:** a social area.
  - **Challenge Grounds:** voluntary mazes with food at the end.
- **Sky and weather:**
  - day/night light ramp, sun position, and a polarized-light pattern (flies really navigate by these, using the central complex)
  - temperature, humidity, and wind from vents, which carries odor plumes
  - optional natural threats: looming shadows
- **Puzzle Chambers:** separate sub-worlds with no physical path from the dome; a fly gets there only by a Watcher transfer (§10.4).

### 5.2 Physics (v1: reduced body, "ColonyBody")
- A 2.5D rigid body on surfaces plus simplified 3D flight (takeoff → steered flight → landing), batched on the GPU for all flies. It handles fly–fly contact for tapping, boxing and holding.
- **v2 upgrade path:** a full biomechanical **FlyGym 2.x / NeuroMechFly** body (MuJoCo-Warp on GPU) with motor-neuron readout, for high-end GPUs.

### 5.3 Senses: world → real sensory neurons in the connectome
| Sense | World model | Enters brain via |
|---|---|---|
| Vision | GPU raycast from each eye's ~750 ommatidia (hexagonal lattice) at 100 Hz | Photoreceptors / first-order visual neurons (flyvis-style) |
| Smell | 3D odor grid of about 10–20 odorants, including cVA, CO₂ and geosmin. Wind carries it and it diffuses. Left and right antennae sample it separately. | Olfactory receptor neurons, using receptor tuning from the DoOR database |
| Taste (contact) | Leg and proboscis contact with food, water, bitter, salt, and pheromones on other flies | Gustatory neurons (sugar Gr5a/64f, bitter Gr66a, water ppk28, pheromone ppk23) |
| Hearing, wind, gravity | Near-field song particle velocity, wind, body orientation | Johnston's organ neuron groups |
| Temperature / humidity | Local air values | Arista hot/cold cells, hygrosensory neurons |
| Touch / pain | Contacts, lunge impacts | Mechanosensory / nociceptive inputs |
| Body state | Energy, water, mated status, egg load, body motion | Documented interoceptive / ascending routes (§4.3) |

### 5.4 Motor: descending neurons → body "motor primitives" (the muscle layer)
Walk forward/back (e.g. MDN for backward walking) · steer (DNa01/DNa02) · escape takeoff (Giant Fiber) · flight steering and landing · grooming (grooming DNs) · proboscis extension / feeding · wing extension + song (e.g. pIP10) · lunge / wing-threat · abdomen bend / copulation · vaginal-plate opening (female acceptance) · ovipositor extrusion (rejection) · egg-laying (oviDNs).
- The mapping comes from connectome annotations (BANC and MaleCNS descending-neuron function labels) and lives in versioned I/O-map files.
- Descending neurons without a known function are still logged, just not mapped to a movement.
- **Mating needs two brains:** the male's copulation output **and** the female's vaginal-plate opening. Nothing is scripted.

### 5.5 Physiology and life cycle (default: 1 real hour = 1 fly day)
| Stage / process | Fly time | Real time | Simulated as |
|---|---|---|---|
| Egg | ~1 day | ~1 h | Timer + viability |
| Larva (L1–L3) | ~4 days | ~4 h | Growth, feeding on nursery food, density-dependent survival. *(v2 option: real larval connectome, 3,016 neurons)* |
| Pupa | ~4 days | ~4 h | Metamorphosis, then the adult brain is built from the sex template + genome + fresh noise |
| Sexual maturity | ~0.5–1 day after emerging | 30–60 min | Physiological flag that gates receptivity signaling |
| Adult lifespan | Median ~45 days (set by genome and diet) | ~2 real days | Gompertz aging mortality; starvation and dehydration are also possible |
| Generation time | ~12–14 days | ~12–14 h | About 2 generations per real day |

- **Metabolism:** energy (sugar), protein (yeast), and water reserves.
- **Female:** egg maturation needs protein and mating. After mating, sex peptide makes her unreceptive for a few days and increases egg-laying.
- **Aging:** stamina declines and sleep fragments (both real in old flies).
- **Death:** the body remains as a visible corpse that decays over time (real flies react to dead flies).
- **Population control:**
  - larval competition for food (real density dependence)
  - a Watcher-set **adult population cap** (default 150) and larva cap (default 300); eggs above the cap are simply non-viable
- **Sex ratio of offspring:** default is to **maintain 70:30 M:F**; can be switched to natural 50:50.

---

## 6. Time and clocks
- **Neural time** (brain + physics): runs at biological speed. A pacer keeps it at `sim_speed × wall-clock` (default 1.0).
- **Life clock** (day/night, circadian clock, hunger, sleep pressure, aging, development, egg maturation): runs compressed.
  - `life_time = neural_time × 86400 / D`, where **D = neural seconds per fly day** (default 3600, i.e. 1 real hour).
  - The Watcher can change both **D** and **sim_speed** live.
  - 1 fly minute = 2.5 real seconds; 1 fly hour = 2.5 real minutes.
- **Consequence:** moment-to-moment behavior is **not** sped up. A 20-minute copulation takes 20 real minutes, a third of a fly day. Each fly day holds one real hour of lived experience.
- If the hardware runs slower than real time, fly days stretch in wall time. The dashboard always shows the actual "real minutes per fly day".
- **Circadian clock:** a molecular-oscillator model in the clock neurons, period = 1 fly day, entrained by light. Default is 12 h light : 12 h dark; seasons are adjustable.
- **Genesis** = Day 1, 06:00 (dawn).

---

## 7. Social life
- **Communication = signals as first-class events.** Each signal has an id, emitter, type, parameters (e.g. song pulse interval, bout length, intensity) and a **receiver list**: the flies whose sensory neurons actually received it above threshold, computed physically, so overhearing happens naturally.
- **Courtship:** orient → follow → tap (tastes her pheromones) → sing → lick → attempt copulation.
  - The female's brain accepts (slows down, opens the vaginal plate) or rejects (runs, flicks wings, kicks, extrudes the ovipositor).
  - Rejected males show courtship conditioning; mated females carry cVA, which makes them less attractive.
- **Fights:** approach, wing threat, fencing, lunging, boxing, holding, tussling, chasing.
  - Contact physics transfers impulses, and injury points temporarily reduce stamina. Wing damage is optional.
  - Deaths from fighting are off by default.
  - Winner and loser effects and dominance hierarchies can emerge from neural state.
- **Babies:** mating → eggs laid on nursery substrate → hatch → larva → pupa → emerge as a new fly. The Watcher creates the new fly's `/flies` folder with its parents, genome, name and lineage, and announces the birth in the chronicle.
- **Relationships (Watcher-side):** for each pair of flies, the Watcher tracks proximity time, courtship, matings, fights won/lost, and neural state in each other's presence. This produces **affinity** ("love") and **rivalry** ("hate") scores. Note: flies don't pair-bond, so "love" means a sustained, specific attraction.

---

## 8. Feelings and thoughts (Watcher's Mind Decoder)
| Label | Neural evidence (decoder inputs) | Typical trigger |
|---|---|---|
| Happy / content | Reward dopamine neurons (PAM) up, NPF up, sated, low punishment dopamine (PPL1) | Eating when hungry, mating, finding shelter |
| Sad / dejected | Sustained low activity + low reward dopamine after uncontrollable stress (learned-helplessness-like) | Repeated failure, isolation |
| Frustrated *(composite)* | High drive (courtship or hunger) + repeated goal failure + bursty activity | Rejection, blocked food |
| Angry / hate (toward a specific fly) | Aggression-state neurons (e.g. P1a/pC1d, Tk-FruM) and octopamine up, aimed at one fly, persisting across encounters | Rival at a food patch |
| Love / attraction (toward a specific fly) | Courtship-drive neurons (P1/pC1) aimed at one fly, repeated approach, post-mating reward | Preferred mate |
| Fear | Looming detectors (LPLC2 → Giant Fiber) + persistent defensive arousal | Shadows, attacks |
| Lonely | Low social contact over fly days + isolation-linked state changes | Isolation |
| Curious | Novelty dopamine responses, exploration drive | New chamber or food |
| Sleepy / hungry / thirsty | Sleep-drive (R5, dFB) and interoceptive states | Physiology |

- **Emotion vector:** valence and arousal plus the labels above, sampled at 1 Hz of neural time, with evidence and confidence.
- **Thought record:** written every second and at every decision. Fields:
  - `senses`: the top deviations, e.g. "vinegar ↑ on the left", "moving fly ahead"
  - `drives`: hunger, thirst, sleep, courtship, aggression, fear, curiosity
  - `memory`: the mushroom-body output's good/bad prediction for the current cue ("remembers this smell as good")
  - `intent`: the descending-neuron group ramping up, i.e. "about to turn left"
  - `heading_goal`: the central-complex compass/steering state
- **Narration:** "(thinking) Sweet smell to the left… hungry… turning left."
- Decoder thresholds are calibrated on known situations (feed a hungry fly → happy; repeated rejection → frustrated) and versioned.

---

## 9. Tasks: Task Engine + starter catalog of 70

**Task spec (YAML):** id, name, category, DSA analog, chamber/zone layout, incentive (reward: sugar or a cool spot; punishment: heat or bitter), schedule/trigger, eligible flies, success criterion, metrics, difficulty levels, randomization.
- **Scoring:** the Watcher computes the optimum with the real algorithm (BFS, Dijkstra, TSP solver, bandit oracle) and scores the fly on:
  - path efficiency (optimal ÷ actual)
  - trials to criterion
  - errors (e.g. revisiting arms = working-memory errors)
  - latency
- **Example output:** "F012 solved Dijkstra-maze L3 at 87% efficiency after 6 trials."
- **Assigning a task:** the Watcher either transfers the fly into a chamber (§10.4) or arranges the dome so the fly meets the puzzle (e.g. food placed behind a maze near its favorite perch).

**A. Graph and search (DSA embodied):**
1. T-maze choice
2. Y-maze spontaneous alternation
3. Dead-end corridor (backtracking)
4. Depth-3 tree maze (DFS)
5. Grid maze (path finding)
6. Multi-route maze (shortest path / BFS)
7. Terrain-cost routes (Dijkstra, least cost)
8. 8-arm radial maze (visited-set memory)
9. Detour around a transparent barrier
10. Odor gradient ascent (greedy search)
11. Sequential halving corridor (binary-search analog)
12. 5-patch foraging tour (TSP)
13. Novel-arena coverage (graph traversal)
14. Shifting-wall maze (dynamic re-planning)
15. Loop-trap maze (cycle detection and escape)
16. Which enclosure has the exit (connected components)
17. Sweetness-ordered visits (sorting/sequence)
18. Nested dead-ends, returning in reverse order (stack/LIFO)
19. Regenerating patches, revisit in depletion order (queue/FIFO)
20. Near-small vs far-large reward (greedy vs optimal)

**B. Loops and rhythms:**
21. Patrol ring with ordered checkpoints (roam in a loop)
22. Figure-8 route
23. Time-place learning (food at a fixed fly-hour)
24. Orbit a landmark
25. Return home to a perch (path integration)

**C. Learning and memory:**
26. Odor + heat aversive conditioning
27. Odor + sugar appetitive conditioning
28. Visual pattern learning (image task)
29. Color learning
30. Visual place learning in a heat maze
31. Reversal learning
32. Extinction
33. Second-order conditioning
34. Trace conditioning
35. Long-term memory retest after 1 and 3 fly days
36. Context-dependent memory
37. Novelty preference / latent inhibition

**D. Decisions:**
38. Multi-armed bandit
39. Patch-leaving (marginal value)
40. Risk: constant vs variable reward
41. Tasty odor + bitter food conflict
42. Speed–accuracy (decaying food)
43. Delay discounting
44. Egg-laying site choice
45. Satiety-dependent choice

**E. Social:**
46. Male finds and courts a receptive female
47. Female mate choice by song quality
48. Mate copying
49. Hold a food territory
50. Dominance hierarchy
51. Social learning of egg-laying sites
52. cVA aggregation
53. Collective escape from a looming shadow
54. Group foraging efficiency
55. Isolation then reintroduction
56. Courtship conditioning
57. Scramble competition

**F. Survival:**
58. Find water in a drought
59. Food scarcity
60. Predator-shadow avoidance
61. Find preferred temperature (~25 °C)
62. Plume tracking (surge upwind / cast)
63. Reach a shelter perch before dark
64. Avoid toxic food
65. Light/gravity orientation

**G. Motor skills:**
66. Gap crossing (improves with practice)
67. Climbing wall
68. Flying through gates (slalom)
69. Narrow bridge / rough terrain
70. Landing on a swinging fruit

---

## 10. The Watcher

### 10.1 Invisibility guarantees
1. No world entity, sound, odor, light or shadow represents the Watcher.
2. It reads the one-way observation stream only.
3. Every command is **naturalized**:
   - light and temperature ramp gradually
   - food "ripens" into place
   - spawned flies emerge from pupae
   - transfers use sleep or a blink (§10.4)
4. There is no neural stimulation API at all.
5. Tests enforce these: an `import-linter` contract, plus a check that a Watcher-attached run and a Watcher-detached run produce bit-identical states.

### 10.2 Awake / asleep
| State | What happens |
|---|---|
| AWAKE | Full simulation and full logging. Fly-nights (every fly day) happen normally and fly sleep bouts are logged (sleep = ≥5 min immobility, the standard fly definition). |
| GOING-TO-SLEEP | Default: wait for the next fly-night and until ≥95% of flies are asleep (at most 1 fly day). `sleep now` skips the wait. |
| ASLEEP | Checkpoint, then the engine is **suspended**. Neural time and the life clock freeze, so the flies don't age and nothing happens unobserved. To the flies it is one seamless night. |
| WAKING | Resume, then dawn. |

The sleep schedule can be manual, a fixed real-world schedule (e.g. 23:00–07:00), or tied to PC sleep.

### 10.3 Your powers (via the Watcher)
- **Time:** set fly-day length (D), sim_speed, pause/resume, fast-forward (if the hardware allows).
- **Watcher:** sleep, wake, schedule, logging verbosity, focus a fly (FULL fidelity + high-resolution recording), narration style.
- **Environment:** light/day length/season, temperature, humidity, wind, food type/amount/scarcity, water, add or remove obstacles and zones, predator-shadow events.
- **Life:**
  - `genesis` (100 flies, 70:30, personality mix)
  - **`spawn N`** (sex, preset or custom genome, stage egg/larva/pupa/adult, location; adults emerge from pupae by default)
  - population and larva caps, egg viability, mutation rate, offspring sex ratio
  - remove a fly (naturalized departure; requires confirmation)
- **Tasks:** create a chamber or puzzle, assign or transfer a fly, set difficulty, view scores and leaderboards.
- **Time travel:** checkpoint, restore, **branch** ("what-if" timelines).
- **Queries:** e.g. "what did F042 do today", "who fought whom", "family tree of F007", "evolution report".

### 10.4 Puzzle chambers, image tasks and transfers
- **Chambers** are separate sub-worlds: mazes (drawn as graphs in the dashboard puzzle builder), T/Y mazes, heat-place arenas, odor arenas, social arenas (e.g. two rivals, or a courtship pair), and **image arenas**.
- **Image arena:**
  - A cylindrical panorama like a real fly-lab LED arena. You upload **any image or video**, and it is resampled to the ommatidial lattice (~750 px per eye, about 5° per pixel).
  - The dashboard shows a **fly-eye preview** of exactly what the fly sees.
  - Modes: free viewing (log neural responses), preference, discrimination learning (image A = cool/sugar, image B = heat), motion/optic-flow tests.
- **Transfers without revealing the Watcher:**
  - **Sleep transfer** (default): the fly is moved while asleep and wakes in the chamber.
  - **Blink transfer**: the fly's senses are held at a dark or neutral baseline for about 200 ms while it is moved.
  - The return trip works the same way. The fly's physiology keeps running inside the chamber.

### 10.5 Local LLM (Watcher-only)
- **Runtime:** a llama.cpp server or Ollama, behind an OpenAI-compatible HTTP interface. The model is set in `config/watcher.yaml`.
- **Placement:** runs on **CPU/RAM** by default (56 GB allows 8–14B dense or small MoE models such as the Qwen3-30B-A3B class, or newer equivalents), so the GPU stays free for the brains.
- **Uses:**
  1. Per-fly **daily diary prose**, written from the structured facts
  2. The colony chronicle
  3. **Q&A over logs**, using read-only DuckDB query tools
  4. **Plain-English commands** turned into typed Control API commands, validated by schema, with confirmation for destructive or large actions
- **Grounding guard:**
  - every sentence must cite event IDs
  - a validator rejects any unknown entity, number or event and falls back to the template diary
  - template diaries are always produced first, so logs never depend on the LLM
- **Model selection (Phase 6):** an eval harness with 50 fact bundles (faithfulness must be 100% or it falls back to templates) and 100 sample commands (≥95% parse accuracy). The best model that fits is chosen.
- **Throughput budget:** ~200-token daily summaries for 100 flies at 24 fly days per real day ≈ 5–6 tokens/s sustained, which is feasible on CPU.

---

## 11. The `/flies` record (what the Watcher writes)
```
flies/
  README.md                     roster: id, name, sex, stage, age, parents, status, preset, measured personality
  _colony/
    chronicle/day-0001.md       births, deaths, matings, fights, notable events
    family-tree.json · relationships-graph/day-0001.json · population-stats.parquet · evolution.parquet
  F0001-rex/
    profile.md | profile.json   sex, birth time, parents, genome summary, assigned vs expressed personality, fidelity history
    diary/day-0001.md           narrative timeline: every notable act, speech, thought, feeling (template + LLM prose)
    timeline/day-0001.jsonl     EVERY event (complete, machine-readable)
    speech/day-0001.jsonl       every signal sent/received, with English translation
    mind/day-0001.parquet       feelings, drives and thoughts at 1 Hz neural time
    brain/day-0001.zarr         activity per neuropil (~80) and key pathway (~150) at 4–10 Hz
    health/day-0001.parquet     energy, water, protein, injuries, mated status, egg load, age
    tasks/attempts.jsonl        task attempts and scores
    recordings/                 full spike rasters (focus mode and event flight-recorder only)
watcher/
  journal/day-0001.md · interventions.jsonl (every command: who, what, when) · sleep-log.jsonl
```
- **Every record** carries `real_ts` (ISO-8601 wall clock), `sim_ts` (neural seconds since genesis), `fly_ts` ("Day 12, 14:03:22"), `event_id`, `fly_id`, `interpreted` (bool), `evidence`, `confidence`.
- **"Everything" means:** every behavior start and stop, contact, signal (sent and received), feeding, sleep bout, mood change past a threshold, thought sample, decision, task attempt, life event and intervention.
- **Raw neural data exception:** 100 full brains produce about 85M spikes/s (~29 TB/day), so full spike rasters are kept only in **focus mode** or in the **flight recorder**. The flight recorder is a rolling RAM buffer dumped around mating, fights, births and deaths.
- **Volume (100 flies, 24 fly days per real day):** about 10–15 GB per real day compressed. D: has 353 GB free, which is about 3–4 weeks.
- **Retention:** closed days are compressed with zstd, brain summaries older than 7 days are downsampled, and events and diaries are kept forever.
- **Completeness test:** every event in the engine stream must appear in `/flies`.

---

## 12. Control console and dashboard
- **CLI (`colony`, Typer):** `genesis`, `run`, `watcher sleep|wake|schedule`, `time set --fly-day 60m`, `spawn 10 --sex female --preset curious`, `chamber create`, `transfer F012 --to maze-1 --mode sleep`, `checkpoint|restore|branch`, `ask "..."`.
- **Web dashboard** (local, FastAPI + WebSocket, Svelte + PixiJS):
  - live top-down colony view (sex colors, mood halos, **speech bubbles with translations**)
  - fly inspector (profile, live mood and drive gauges, thought stream, neuropil activity map, **fly-eye view**, diary)
  - colony stats, family tree, relationship graph
  - puzzle builder and task scores
  - time controls
  - Watcher panel (awake/asleep, schedule, audit log, **chat with the Watcher LLM**)
  - later: 3D brain viewer (Three.js with FlyWire neuropil meshes)

## 13. Tech stack
- **Language and GPU:** Python 3.12. PyTorch 2.x on CUDA 12 with **Triton** kernels (LIF, graded units, event propagation). A pure-PyTorch fallback runs on Windows and CPU for tests.
- **Where it runs:** the engine runs in **WSL2 Ubuntu 24.04**. Templates and checkpoints go on the WSL ext4 filesystem; `/flies` is written to `D:\the-fly-colony\flies` through `/mnt/d`.
- **Brain references and inputs:**
  - Brian2 plus `philshiu/Drosophila_brain_model` as the validation reference
  - evaluate `annel0/flybrain`, a GPU LIF simulator for MaleCNS/FlyWire, for kernel reuse (check its license)
  - `flyvis` for vision
  - `neuprint-python` / Codex downloads, with Polars + DuckDB for streaming preprocessing
- **Engine plumbing:** world, odor and vision run as custom batched GPU PyTorch modules. `flygym` 2.x is for v2 only.
- **Watcher and dashboard:** Watcher on asyncio + FastAPI; observation stream in a shared-memory ring buffer (pyzmq fallback). Logs in Parquet/Arrow, JSONL and Markdown, with Zarr for brain traces; DuckDB for queries.
- **Supporting tools:** config in YAML + pydantic; RNG in NumPy/PyTorch generators, seeded per subsystem; tests with pytest, hypothesis and pytest-benchmark; lint with ruff and **import-linter**.

## 14. Repository and spec layout (SDD)
```
the-fly-colony/
  specs/000-constitution.md
  specs/NNN-<feature>/{spec.md, design.md, tasks.md}     # Spec-Kit-style; `specify` CLI optional
     001-connectome-pipeline  002-brain-engine  003-body-world  004-senses  005-motor
     006-physiology-lifecycle  007-genome-personality-reproduction  008-communication
     009-watcher-core-clocks-sleep  010-mind-decoder  011-flies-logging  012-task-engine-chambers
     013-console-dashboard-llm  014-performance-fidelity
  src/flycolony/{connectome,brain,body,world,senses,motor,physiology,genetics,comms,engine,
                 watcher,tasks,console}/
  config/{colony.yaml, genesis.yaml, watcher.yaml, params/registry.yaml}
  flies/  watcher/  world/checkpoints/  data/(gitignored)  tests/{unit,validation,emergence,invariants,perf}
```
- **Each `spec.md`** contains: purpose, EARS-style requirements with IDs (e.g. `BRAIN-R-012: WHEN a sugar GRN group is stimulated THE SYSTEM SHALL…`), acceptance criteria, and linked test IDs. Then `design.md` gives the how, and `tasks.md` gives ordered tasks, each tied to tests.
- **Workflow per feature:** spec → you review → design → tasks → implement → acceptance tests green.
- `git init` happens in Phase 0, after your confirmation.

---

## 15. Roadmap (every phase ends in a gate)
| # | Phase | Key deliverables | Gate |
|---|---|---|---|
| S | **Specs** | Constitution + the 14 `spec.md` files | You approve the specs |
| 0 | Foundations and data | Repo, config, parameter registry, downloads, BrainTemplates, license check | Neuron and synapse counts match published figures; checksums pass |
| 1 | Brain engine | Batched hybrid LIF/graded GPU simulator; benchmark | Matches the Shiu/Brian2 reference (e.g. sugar-neuron → feeding-motor-neuron activation; spike-rate correlation ≥0.9). Real-time factor (RTF) measured on the 4060 and the 1650. |
| 2 | One embodied fly | ColonyBody, dome, senses, descending-neuron motor readout, closed loop | **Emergence gates, with no scripts:** sugar → feeding; bitter → rejection; looming → escape; odor plume → approach; darkness + sleep pressure → sleep |
| 3 | Watcher core | Observation stream, clocks, `/flies` writers, sleep/suspend, audit | Watcher-attached ≡ detached (bit-identical); completeness test; suspend/resume is lossless |
| 4 | Physiology and life cycle | Metabolism, circadian clock, sleep homeostasis, aging, death, development | Day/night activity profile emerges; starvation/aging curves match their specs |
| 5 | Colony | 10 → 100 flies, both sex templates, genome/presets, social senses, courtship, fights, mating, eggs → babies, spawn, caps | 70:30 genesis; at least one full courtship → copulation → egg → adult cycle **without scripts**; caps hold |
| 6 | Mind and voice | Emotion/thought decoder, translator, template narrator, relationships, LLM runtime + eval harness + model pick | Decoder calibration suite; LLM faithfulness 100% or fallback; command parsing ≥95% |
| 7 | Tasks | Task spec DSL, chambers, sleep/blink transfer, image arena, optimal solvers, first 10 tasks, then all 70 | Transfer invisibility test; scores reproducible |
| 8 | Console | CLI, API, web dashboard, puzzle builder, fly-eye view, chat | Every §10.3 power works end to end |
| 9 | Scale and hardening | HYBRID/COARSE fidelity with promotion, performance tuning, retention, checkpoints/branches | 100 flies at ≥1.0 RTF on the 4060 (HYBRID); 72-hour soak test with no drift, crash or runaway |
| 10 | Future | FlyGym full body + BANC/MaleCNS full CNS, larval connectome, evolution experiments | — |

## 16. Hardware
The bottleneck is **GPU memory bandwidth**, not VRAM size. The estimates below extrapolate a published benchmark (MaleCNS at 2.4× real time for one fly, 8.9× for a batch of 4 in fp16, on an RTX 3060 at 360 GB/s), less 30% overhead for world, vision and logging. **Phase 1 benchmarks them for real.**

| Tier | GPU (bandwidth) | RAM / CPU | Storage | FULL-brain flies at 1 real h = 1 fly day |
|---|---|---|---|---|
| Your laptop (dev) | GTX 1650 4 GB (128 GB/s) | 8 GB / i5-11300H | D: 353 GB free | ~3–5 FULL, or ~30 COARSE. Code, tests, small runs. 8 GB RAM means streaming-only preprocessing. |
| **Your planned rig** | **RTX 4060 8 GB (~272 GB/s)** | 56 GB / ≥8 cores recommended | 1–2 TB NVMe | **~15–20 FULL**, or **100–150 HYBRID + 10–15 FULL focus**, or 100 FULL at ~0.2× (1 fly day ≈ 5 real hours). VRAM needed ≈ 3–4 GB, so it fits. The LLM runs on CPU. |
| Best value upgrade | Used RTX 3090 24 GB (936 GB/s) | 64 GB | 2 TB NVMe | ~60–70 FULL (about 3.4× a 4060 for this workload) |
| **Ideal** | **RTX 5090 32 GB (1.79 TB/s)** | 64–128 GB DDR5 / 12–16 cores (e.g. Ryzen 9 9950X) | 2 TB NVMe + 8 TB HDD archive | **~120–140 FULL** + LLM; 1000 W+ PSU, good cooling, UPS for 24/7 runs |
| Research | H100/H200, or 2× RTX 5090 | 128 GB+ / 16–32 cores | 4 TB NVMe | 250+ FULL, or FlyGym full-body physics |

Cloud GPU rental (5090/H100 class) is a pay-per-hour alternative for long full-fidelity runs.

## 17. Risks → mitigations
| Risk | Mitigation |
|---|---|
| Behaviors don't emerge from an uncalibrated connectome | Hybrid graded/spiking model, flyvis, global-only calibration, staged emergence gates, and accepting a partial repertoire with honest reporting |
| 4060 throughput | HYBRID fidelity, event-driven kernels (sleeping brains cost less), stretching the fly day |
| Sensor and motor mapping errors | Derived from annotations, with a validation test per channel |
| Differences between the male and female datasets | Weight normalization; the same assays run on both sexes |
| Plasticity runaway on long runs | Homeostasis, weight bounds, soak tests, a watchdog |
| LLM hallucination | Grounding validator + template fallback |
| Log volume | Tiered logging, flight recorder, retention policy |
| Data licenses | Checked in Phase 0 |
| WSL2 I/O or driver issues | Engine data on ext4; a native-Windows pure-PyTorch fallback |

## 18. Verification (end to end)
- **Unit:** neuron and synapse integration, CSR ops, clock math (D, sim_speed ↔ life clock), genome crossover/mutation, sex-ratio controller, caps.
- **Validation:** reproduce Shiu et al. predictions on FAFB (tolerance-based); the production timestep must match the 0.1 ms reference.
- **Emergence:** the Phase 2 and 5 behavior assays run from sensory inputs only; a grep plus review confirms no behavior code outside the brain.
- **Invariants:**
  - `import-linter` isolation
  - **Watcher-attached vs detached bit-identical run** over 2 fly days
  - blink/sleep transfer produces no Watcher-specific sensory signature
  - log completeness (engine events ⊆ `/flies`)
  - 70:30 at genesis
  - suspend → resume is lossless
- **Performance:** RTF and VRAM benchmarks per fidelity level on the 1650 and the 4060; a 72-hour soak test.
- **Manual acceptance:**
  1. Run genesis and watch one fly day on the dashboard.
  2. Open `flies/F00xx/diary/day-0001.md` and check the timestamps, speech translations, thoughts and feelings.
  3. Transfer a fly into an image arena showing your uploaded picture, and check the fly-eye preview and the score.
  4. Put the Watcher to sleep and confirm the world freezes, then wake it and confirm dawn resumes.
  5. `spawn 5` and confirm the pupae emerge and profiles are created.
  6. Change the fly day to 30 minutes and confirm the day/night cycle adapts.
