# 000 — Constitution

| Field | Value |
|---|---|
| Status | Draft — awaiting review |
| Applies to | Every spec, design, task, line of code, config file, test and tool in this repository |
| Plan refs | §2 (with §1, §3, §10.1) |
| Cited as | `CONST-<article>.<clause>`, e.g. `CONST-2.5` |
| Amendments | Only with the project owner's explicit approval, recorded in §11 |

This document holds the rules that make The Fly Colony what it is. If anything conflicts with it (a spec, a design, a convenient shortcut), the constitution wins and the other thing is wrong. Specs 001–014 cite the articles they implement.

---

## 1. Definitions

| Term | Meaning |
|---|---|
| **Fly** | One simulated *Drosophila melanogaster* at any life stage. In v1 only adults have a brain. |
| **Mind** | An adult fly's simulated connectome brain: neurons, synapses, neuromodulator and peptide traces, plastic weights, homeostatic state. |
| **Body layer** | The only non-neural code allowed to act on or around a fly: world and physics, senses, motor primitives, physiology (CONST-1.2). |
| **Action selection** | Deciding what a fly does, toward whom, when and for how long. It belongs to the mind alone. |
| **Watcher** | The hidden observer and controller. It reads the colony, writes the record, and carries out your commands on the environment. |
| **Fly-perceivable channel** | Anything that can reach a fly's sensory neurons, or change its body, its brain parameters or its world in a way that could later reach its senses. |
| **Naturalized intervention** | An environmental change delivered in a form the world could produce without an agent: a gradual ramp, a natural process (ripening, eclosion, decay), or a change applied only where and when no awake fly can perceive the act of changing. |
| **Emergence gate** | A behavioral test that starts only from sensory input, with no behavior code anywhere, and that a phase must pass. |

---

## 2. Article 1 — Neuron-only minds

**CONST-1.1** Every choice an adult fly makes comes from its simulated neurons. No behavior trees, finite-state machines, utility or reward functions, planners, scripted reactions, behavior lookup tables, trained policies or LLMs exist inside or around any fly.

**CONST-1.2 The mind decides, the body executes.** Non-neural code is limited to four layers, each with a hard boundary:

| Layer | May | May not |
|---|---|---|
| World and physics | Move bodies by forces and contacts. Run weather, odor transport, food ripening and decay. | Move, steer, attract or repel a fly because of its state, needs or goals. |
| Senses | Turn world state at a fly's sensors into sensory-neuron input. Apply documented gains: genome, adaptation, interoceptive routes. | Filter or boost input by relevance ("highlight food when hungry") except through a documented physiological route. |
| Motor primitives (muscles) | Turn descending- and motor-neuron activity into movement, within biomechanical limits. | Start, chain, sequence or choose between actions. Finish an action the neurons stopped driving, except ballistic actions with a fixed physical duration (jump, lunge, egg deposition). |
| Physiology | Run metabolism, hormones, circadian oscillator, development and aging. Affect the brain only through documented interoceptive routes. | Read brain activity to decide outcomes. The only exceptions are motor effort (for energy cost) and secretion by identified neurosecretory neurons. |

**CONST-1.3 Calibration is global only.** Model parameters may be tuned only globally, meaning per template, sex, cell type, neuron class or registry parameter, applied to all flies alike. Tuning happens offline and is recorded in the Parameter Registry together with the calibration run. Calibration objectives may be behavioral (e.g. "sugar evokes feeding"). No parameter may depend at runtime on a situation, a behavior, or one fly's state.

**CONST-1.4 Test-only stimulation.** Tests may drive neurons directly through a test fixture. That fixture is not part of the production package, and production code cannot import it. At runtime there is no path that stimulates neurons.

**CONST-1.5 Pre-adult stages (v1).** Eggs, larvae and pupae have no simulated brain and no behavior. They are developmental processes: growth, survival and timing. Where a pre-adult outcome needs a place (e.g. the pupation site), the place is drawn from a documented biological distribution. A v2 larval connectome would bring larvae under CONST-1.1.

**Enforcement:** the compliance checklist (§9); `import-linter` contracts; a static audit that body-layer modules reference no behavior labels; emergence gates that start only from sensory input (specs 005, 007, 008).

---

## 3. Article 2 — Watcher invisibility

**CONST-2.1** No world entity, sound, odor, light, shadow, vibration or contact represents the Watcher.

**CONST-2.2** The Watcher reads only the one-way Observation Stream. Reading never changes engine state.

**CONST-2.3** The Watcher changes the world only through the Environment Control API. The API schema cannot address neurons, synapses, neuromodulator traces or any other internal brain state. **No neural stimulation API exists.**

**CONST-2.4** Every intervention is naturalized, using the method declared for its command type in the naturalization catalog (spec 009).

**CONST-2.5** Observing causes no disturbance. Given the same checkpoint, config and command log, a run with the Watcher attached is **bit-identical** to a run with it detached.

**CONST-2.6** Interventions leave no Watcher-specific sensory signature. For transfers this is tested explicitly (spec 012).

**Enforcement:** T-WATCH-I-001 (attached ≡ detached), `import-linter` contracts, Control API schema tests (009), the transfer invisibility test (012).

---

## 4. Article 3 — Total observability while awake

**CONST-3.1** While the Watcher is awake, every engine event is recorded in `/flies` with three timestamps: `real_ts`, `sim_ts` and `fly_ts`.

**CONST-3.2** Nothing happens unobserved. When the Watcher sleeps, the engine is suspended and all clocks freeze. If the Watcher lags, crashes or cannot write (e.g. the disk is full), the engine pauses rather than running ahead.

**CONST-3.3** The only exception is data volume. Full spike rasters are kept only in focus mode and in flight-recorder windows. Neural summaries are always kept.

**Enforcement:** log completeness test (011), backpressure test and suspend/resume test (009).

---

## 5. Article 4 — Chain of command

**CONST-4.1** You → Watcher → Environment. Only the Watcher's Controller changes the world, and only on your behalf. That means one of:
- a command you give (CLI, dashboard, or a chat request the LLM parsed and you confirmed where confirmation is required), or
- a standing policy you configured (sleep schedule, task schedule, auto-return).

**CONST-4.2** Every command, accepted or rejected, is audited: its source, what it was, when (three timestamps), how it was naturalized, and the result.

**CONST-4.3** Nothing else changes the world. There are no background scripts, no LLM with direct access, and no test hooks in production.

---

## 6. Article 5 — Reproducibility

**CONST-5.1** All randomness comes from seeded generators, with one stream per subsystem and per fly.

**CONST-5.2** The same checkpoint, config, registry, templates and command log give a **bit-identical** run on the same hardware and software stack. Across different hardware the result is statistically equivalent.

**CONST-5.3** Connectome templates, the Parameter Registry, decoder and translator versions, and configs are all versioned. Every run and checkpoint records the versions it used.

**CONST-5.4** Checkpoints can be restored and branched. Nothing is silently deleted: a restore archives the abandoned future instead of erasing it.

---

## 7. Article 6 — Biological grounding

**CONST-6.1** Every model parameter lives in the Parameter Registry (spec 001) with either a source citation or an `ASSUMPTION` flag and its rationale.

**CONST-6.2** Model code contains no magic numbers.

**CONST-6.3** Every release reports what share of the parameters behind each spec are `ASSUMPTION`s.

---

## 8. Article 7 — Honest interpretation

**CONST-7.1** Every decoded feeling, thought, behavior label and signal translation is marked `interpreted: true`. It stores its evidence (the neural or physical signals behind it), a confidence value, and the version of the decoder or translator that produced it.

**CONST-7.2** "Unclear" is a valid output. The Watcher never invents certainty.

**CONST-7.3** Behaviors that fail to emerge are reported as failures. All runs of an emergence gate are reported, including the failed ones. A gate passed only by breaking CONST-1.3 does not count.

**CONST-7.4** The flies have no words. The English belongs to the Watcher.

---

## 9. Compliance checklist (every change)

- [ ] No non-brain code chooses, starts, sequences or ends an action (CONST-1).
- [ ] Every new parameter is in the registry with a source or an `ASSUMPTION` flag (CONST-6).
- [ ] No new path leads from the Watcher, console or LLM into engine state except the Control API (CONST-2, CONST-4).
- [ ] New randomness uses a seeded per-subsystem or per-fly stream (CONST-5).
- [ ] Every new interpreted output carries evidence, confidence and a version (CONST-7).
- [ ] Every new engine event reaches `/flies` (CONST-3).

## 10. Precedence

The constitution overrides specs, specs override designs, and designs override tasks. To amend the constitution: write a proposal (the new text, the reason, the affected specs) → get your approval → add a changelog entry → update the affected specs.

## 11. Changelog

| Date | Change | Approved by |
|---|---|---|
| 2026-09-26 | Initial draft from master plan §2. Added CONST-1.3 (global-only calibration), CONST-1.4 (test-only stimulation) and CONST-1.5 (pre-adult scope) to make plan §1 explicit. | pending |
