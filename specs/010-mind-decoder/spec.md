# 010 — Mind Decoder (behavior, feelings, thoughts, relationships, personality)

| Field | Value |
|---|---|
| Status | Draft — awaiting review |
| ID prefix | `MIND` |
| Phase | 3–5 (behavior classifier, needed by the Watcher and the gates); 6 (emotion and thought decoders, relationships, calibration) |
| Plan refs | §1 (feelings, think), §4.5 (measured personality), §7 (relationships), §8 |
| Depends on | 002 (taps), 005 (primitive activations), 008, 009 |
| Used by | 007 (expressed personality), 008 (context for translation), 011 (mind logs, diaries), 012 (task-trial context), 013 (gauges, thought stream) |
| Constitution | CONST-2.2 (read-only), CONST-7 (honest interpretation) |

## 1. Purpose

Everything the Watcher *interprets* about a fly lives here: what it is **doing** (behavior classifier), what it **feels** (emotion decoder), what it is **thinking** (thought decoder), whom it **likes or hates** (relationships), and **who it is** (measured personality). Every output is an interpretation with evidence and a confidence. None of it ever reaches the fly.

## 2. Scope

**In scope:** the ethogram and behavior classification; fight outcomes and dominance; the emotion vector and labels; thought records and narration lines; the list of key pathways; relationship accumulators and scores; personality assays and profiles; the calibration suite; versioning and reproducibility.

**Out of scope:** writing files (011); translating signals (008); LLM prose (013).

## 3. General

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| MIND-R-001 | M | Every decoder SHALL run inside the Watcher, only on Observation Stream data and Watcher-derived statistics, and SHALL be read-only. | T-MIND-I-001 |
| MIND-R-002 | M | Every output record SHALL carry `interpreted: true`, `evidence` (named signals with values and baseline statistics), `confidence` ∈ [0, 1], and the decoder id and version. | T-MIND-U-001 |
| MIND-R-003 | M | Decoding SHALL be reproducible: running decoder version V again on a recorded stream gives identical outputs. | T-MIND-I-002 |
| MIND-R-004 | M | IF confidence falls below the label's threshold THEN the output SHALL be `unclear` (CONST-7.2). | T-MIND-U-001 |
| MIND-R-005 | M | THE SYSTEM SHALL keep a versioned list of ~150 **key pathways**: named neuron sets used by the decoders and by brain logging. Examples: PAM and PPL1 dopamine neurons, MBON groups, P1/pC1, aggression neurons, LPLC2, Giant Fiber, DN groups, dFB, R5, EPG/PFL, NPF neurons, insulin-producing cells, clock neurons. | T-MIND-U-002 |

## 4. Behavior classifier (ethogram)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| MIND-R-010 | M | THE WATCHER SHALL classify behavior using a versioned ethogram, at least: walking, running, turning, stopping, backward walking; resting; sleep bout (≥ 5 min immobility; time base WATCH-OQ-01); grooming by body part; feeding; drinking; takeoff, flight, landing; escape; egg-laying; courtship elements; acceptance and rejection elements; copulation; aggression elements; approach and avoid (relative to entities); exploring. | T-MIND-V-001 |
| MIND-R-011 | M | Classification SHALL use body kinematics, contacts and motor-primitive activations. Each bout produces start and stop events with its target (if any), confidence and evidence. | T-MIND-V-001 |
| MIND-R-012 | M | The classifier SHALL be validated against engine ground truth where one exists (primitive activation, contacts) and against labelled synthetic scenarios. Proposed target: ≥ 90% precision and recall on core behaviors. | T-MIND-V-001 |
| MIND-R-013 | M | THE WATCHER SHALL decide the winner and loser of each fight encounter from retreat and chase criteria, and keep a dominance score per group (e.g. Elo or David's score). | T-MIND-U-003 |
| MIND-R-014 | M | THE WATCHER SHALL detect "decisions": the onset of a behavior bout or of a primitive. They trigger thought records (R-030). | T-MIND-U-004 |

## 5. Emotion decoder

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| MIND-R-020 | M | For every adult, at 1 Hz of neural time, THE WATCHER SHALL produce an **emotion vector**: valence ∈ [−1, 1], arousal ∈ [0, 1], and label scores for happy/content, sad/dejected, frustrated, angry (targeted), love/attraction (targeted), fear, lonely, curious, sleepy, hungry and thirsty. | T-MIND-U-005 |
| MIND-R-021 | M | Each label's inputs SHALL follow the evidence table below, versioned in `config/decoder/emotions.yaml`. Each input is either a key pathway or trace, or a Watcher behavioral statistic. | T-MIND-U-005 |
| MIND-R-022 | M | Targeted labels (angry, love) SHALL name their target: the fly being attended, faced or touched while the drive is high. They are promoted to relationship-level "hate" or "love" only if they persist across ≥ N encounters (registry). | T-MIND-U-006 |
| MIND-R-023 | M | THE WATCHER SHALL log a **mood-change event** when a label crosses its threshold, using registry hysteresis to avoid flicker. | T-MIND-U-007 |
| MIND-R-024 | M | Composite labels (e.g. frustrated = high drive + repeated goal failure + bursty activity) SHALL be marked composite in their evidence. | T-MIND-U-005 |

Evidence table (plan §8):

| Label | Neural and behavioral evidence | Typical trigger |
|---|---|---|
| Happy / content | Reward DANs (PAM) ↑, NPF ↑, sated, punishment DANs (PPL1) low | Eating when hungry, mating, finding shelter |
| Sad / dejected | Sustained low activity + low reward DA after uncontrollable stress | Repeated failure, isolation |
| Frustrated (composite) | High drive + repeated goal failure + bursty activity | Rejection, blocked food |
| Angry (targeted) | Aggression-state neurons (e.g. P1a/pC1d, Tk-FruM) and OA ↑, aimed at one fly, persisting | A rival at a food patch |
| Love / attraction (targeted) | Courtship drive (P1/pC1) aimed at one fly, repeated approach, post-mating reward | A preferred mate |
| Fear | Looming detectors (LPLC2 → GF) + persistent defensive arousal | Shadows, attacks |
| Lonely | Low social contact over fly days + isolation-linked state changes | Isolation |
| Curious | Novelty dopamine responses, exploration drive | A new chamber or food |
| Sleepy / hungry / thirsty | Sleep drive (R5, dFB) and interoceptive states | Physiology |

## 6. Thought decoder

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| MIND-R-030 | M | THE WATCHER SHALL write a thought record for every adult every 1 s of neural time and at every decision (R-014). | T-MIND-U-008 |
| MIND-R-031 | M | Thought record fields: `senses` (top-k deviations from the fly's baseline, with left/right, e.g. "vinegar ↑ left"); `drives` (hunger, thirst, sleep, courtship, aggression, fear, curiosity, each ∈ [0, 1]); `memory` (mushroom-body output valence for the dominant current cue, approach-MBON minus avoidance-MBON output, e.g. "remembers this smell as good"); `intent` (the DN group ramping above baseline, the predicted primitive and lead time); `heading_goal` (compass bump phase and central-complex steering signal). | T-MIND-U-008 |
| MIND-R-032 | M | THE WATCHER SHALL render each record as a template narration line, e.g. "(thinking) Sweet smell to the left… hungry… turning left." No LLM is involved. | T-MIND-U-009 |
| MIND-R-033 | M | THE WATCHER SHALL measure and report intent accuracy: how often the predicted primitive actually happens within the lead window. | T-MIND-V-002 |

## 7. Relationships

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| MIND-R-040 | M | For each ordered pair of flies (A→B), THE WATCHER SHALL accumulate: time in proximity, courtship bouts directed at B, matings, fights won and lost, mean valence and arousal while near B, and drive aimed at B (courtship, aggression). | T-MIND-U-010 |
| MIND-R-041 | M | THE WATCHER SHALL compute directed **affinity** ("love") and **rivalry** ("hate") scores with documented formulas and temporal decay (registry). | T-MIND-U-010 |
| MIND-R-042 | M | THE WATCHER SHALL produce a daily relationship-graph snapshot. The documentation SHALL state that flies do not pair-bond: "love" means sustained, specific attraction. | T-LOG-U-006 |

## 8. Measured personality (expressed personality)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| MIND-R-050 | M | THE WATCHER SHALL run these passive assays continuously for each adult, with definitions below. | T-MIND-U-011 |
| MIND-R-051 | M | THE WATCHER SHALL keep a profile per fly: its trait scores, population percentiles, and assigned preset vs expressed traits. It is updated every fly day and stored in `profile.json`. | T-MIND-U-011 |
| MIND-R-052 | M | IF there is not enough data for a trait (e.g. learning speed before any learning event) THEN the trait SHALL be `NA`. | T-MIND-U-011 |

| Trait | Operational definition (draft) |
|---|---|
| Activity | Fraction of awake time spent moving |
| Exploration | Area covered per fly day (grid cells visited) |
| Boldness | Time in the open plaza; latency to enter novel areas; escape threshold to shadows (inverse) |
| Sociability | Mean nearest-neighbor distance (inverse) |
| Aggression rate | Aggression elements per fly hour of social contact |
| Courtship intensity | Courtship elements per fly hour near receptive partners (males) |
| Handedness | Left/right turn bias at choice points and free walking |
| Learning speed | Trials to criterion in tasks, or natural learning events |
| Sleep amount | Sleep per fly day (WATCH-OQ-01 definition) |

## 9. Calibration

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| MIND-R-060 | M | THE SYSTEM SHALL include a calibration suite of scenario runs, including: feed a hungry fly → happy ↑; repeated rejection → frustrated ↑; looming → fear ↑; isolation over N fly days → lonely ↑; new chamber → curious ↑; sleep deprivation → sleepy ↑; starvation → hungry ↑; dehydration → thirsty ↑; a rival repeatedly at the same food → angry at that rival ↑. | T-MIND-V-003 |
| MIND-R-061 | M | Thresholds SHALL be fitted on calibration scenarios and checked on held-out scenarios. Each decoder version is pinned with a stored calibration report. | T-MIND-V-003 |
| MIND-R-062 | M | Calibration SHALL change only decoder parameters, never engine or brain parameters. | T-MIND-I-001 |

## 10. Acceptance criteria

| ID | Criterion |
|---|---|
| MIND-AC-01 | The behavior classifier meets its precision and recall targets on the validation set. |
| MIND-AC-02 | **Phase 6 gate:** in held-out calibration scenarios, each label moves in the expected direction, significantly vs control, for at least the labels listed in R-060. Any label that fails is reported and shown as low-confidence until fixed. |
| MIND-AC-03 | 100% of mind records carry evidence, confidence and version. |
| MIND-AC-04 | Re-decoding a recorded stream is identical. |
| MIND-AC-05 | Attaching every decoder leaves engine state bit-identical (with WATCH-R-050). |
| MIND-AC-06 | Profiles show assigned vs expressed personality for every adult after 1 fly day. |

## 11. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-MIND-U-001..011 | unit | Record schema and `unclear`; key-pathway list; fight outcomes and dominance; decision detection; emotion vector; targeting; hysteresis; thought fields; narration; relationships; personality assays. |
| T-MIND-V-001 | validation | Behavior classifier vs ground truth. |
| T-MIND-V-002 | validation | Intent accuracy. |
| T-MIND-V-003 | validation | Emotion calibration suite (held out). |
| T-MIND-I-001 | invariant | Read-only; calibration touches only the decoder. |
| T-MIND-I-002 | invariant | Reproducible decoding. |

## 12. Assumptions and open questions

| ID | Question | Proposal |
|---|---|---|
| MIND-OQ-01 | Sleep-bout time base. | See WATCH-OQ-01. |
| MIND-OQ-02 | Is the label set final? Add e.g. "calm" or "stressed"? | Keep the plan's set; "calm" = low arousal with neutral valence, shown as a derived state. |
| MIND-OQ-03 | Confidence calibration method. | Logistic calibration on calibration-suite scenarios per label. |
| MIND-OQ-04 | Classifier method: rules on kinematics, or a model trained on synthetic labelled data? | Rules first (transparent, easy to cite as evidence); add a learned model only where rules fail. Either way, evidence is stored. |
| MIND-OQ-05 | Should the sampling rate be adaptive (e.g. faster for focus flies)? | 1 Hz for all, 10 Hz for focus flies. |
