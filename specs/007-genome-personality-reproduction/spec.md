# 007 — Genome, Personality & Reproduction

| Field | Value |
|---|---|
| Status | Draft — awaiting review |
| ID prefix | `GENE` |
| Phase | 5 (Colony) |
| Plan refs | §4.5, §5.5 (sex ratio), §7 (babies), §10.3 (genesis, spawn, life knobs) |
| Depends on | 001 (cross-dataset matching), 002 (brain build), 003, 006, 009 (Control API) |
| Used by | 010 (assigned vs expressed personality), 011 (profiles, family tree, evolution) |
| Constitution | CONST-1 (presets bias genes, never behavior), CONST-5 (seeded inheritance) |

## 1. Purpose

Make every fly an individual and let the colony evolve. A **genome** scales biological knobs. **Developmental noise** makes even identical genomes differ. **Personality presets** bias genomes, never behavior. Reproduction mixes parents' genomes with mutation, so selection can act across generations. This spec also defines **genesis** and **spawn**.

## 2. Scope

**In scope:** genome structure and the gene catalog; genome → brain and body parameters; developmental noise; the 12 presets; genesis; spawn; fertilization, inheritance and mutation; paternity; the offspring sex-ratio controller; identity and naming; lineage; evolution metrics; the Phase-5 life-cycle gate.

**Out of scope:** measuring expressed personality (010 owns the assays; this spec consumes them); egg and development physiology (006).

## 3. Requirements

### 3.1 Genome

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| GENE-R-001 | M | A genome SHALL be an ordered set of 200–400 genes defined in a versioned gene catalog (`config/genes.yaml`). Each gene has: id, name, target knob, effect type (multiplicative, on a log scale), allele bounds, default distribution, sex of expression (both / male / female), and a citation or `ASSUMPTION` for the target's biological relevance. | T-GENE-U-001 |
| GENE-R-002 | M | Target knobs SHALL cover: neuromodulator tone (DA, 5-HT, OA); excitability of cell-type groups (e.g. courtship drive P1/pC1, aggression Tk/P1a, sleep dFB); sensory gain per sense; mushroom-body learning rate; homeostatic set-points; body size; metabolic rate; lifespan factor; fecundity; circadian period and phase. | T-GENE-U-001 |
| GENE-R-003 | M | Genes SHALL act only as parameter values applied when the brain and body are built (BRAIN-R-001). No gene encodes a behavior, a rule or an action. | T-GENE-I-001, review |
| GENE-R-004 | M | Gene targets SHALL be defined through cross-dataset cell-type matching, so a gene affects homologous neurons in both sexes. Sex-specific cell types are handled through sex of expression. | T-GENE-U-002 |
| GENE-R-005 | M | Each gene SHALL carry one allele value per fly, and inheritance is per-gene crossover (plan default). A diploid option is GENE-OQ-01. | T-GENE-U-003 |

### 3.2 Developmental noise

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| GENE-R-010 | M | WHEN a brain is built, THE ENGINE SHALL apply per-fly seeded jitter to neuron thresholds and gains (registry σ), plus a left–right asymmetry component for bilateral pairs. The noise seed is fresh for every individual and never inherited. | T-GENE-U-004 |
| GENE-R-011 | M | Developmental noise SHALL also apply to body parameters (e.g. size) within registry σ. | T-GENE-U-004 |

### 3.3 Personality presets (assigned personality)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| GENE-R-020 | M | THE SYSTEM SHALL define 12 presets as documented gene-offset sets (mean shift and optional variance), editable in `config/genesis.yaml`: Bold Explorer, Shy Homebody, Aggressive Fighter, Gentle Pacifist, Social Butterfly, Loner, Quick Learner, Slow & Steady, Romantic, Picky (female only), Night Owl, Glutton. Each preset lists its target genes, the rationale, and the traits it is expected to shift. | T-GENE-U-005 |
| GENE-R-021 | M | A preset SHALL only change the distribution the genome is sampled from. | T-GENE-I-001 |
| GENE-R-022 | M | IF a preset is assigned to a sex it doesn't apply to (e.g. Picky to a male) THEN THE WATCHER SHALL reject the command and explain why. | T-GENE-U-005 |
| GENE-R-023 | M | THE WATCHER SHALL accept custom genomes (full, or partial overrides of a preset), validated against allele bounds. | T-GENE-U-005 |

### 3.4 Genesis

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| GENE-R-030 | M | WHEN `genesis` runs, THE SYSTEM SHALL create 100 adult flies (70 male, 30 female) by default. It applies the preset mix from `genesis.yaml` (counts or proportions, including "neutral"), spreads the flies across the dome, gives them full reserves, and sets their initial age and state per GENE-OQ-03. The clock starts at Day 1, 06:00. | T-GENE-U-006 |
| GENE-R-031 | M | The sex ratio at genesis SHALL be exactly the configured one (70:30 by default). | T-GENE-I-002 |
| GENE-R-032 | M | IF a colony already exists in the current timeline THEN `genesis` SHALL be refused, unless you confirm starting a new timeline. | T-GENE-U-006 |

### 3.5 Spawn

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| GENE-R-040 | M | `spawn N` SHALL accept: sex (M, F, or a ratio), preset or custom genome, stage (egg / larva / pupa / adult), and location (zone, coordinates, or auto). By default an adult spawn is placed as a late-stage pupa that then ecloses (naturalized). Placement follows the occluded-placement rule (WORLD-R-071). | T-GENE-U-007 |
| GENE-R-041 | M | Spawned flies SHALL have no parents: they are lineage roots, flagged `origin: spawned`. | T-GENE-U-007 |
| GENE-R-042 | M | A spawn SHALL respect the population caps unless you confirm an override. | T-GENE-U-007 |

### 3.6 Reproduction and inheritance

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| GENE-R-050 | M | WHEN a mated female lays a fertilized egg, THE ENGINE SHALL build the offspring genome by per-gene crossover of the mother and the father, then add Gaussian mutation with σ = mutation rate (a Watcher knob) on log-scale allele values, clamped to bounds. It uses the mother's seeded reproduction stream. | T-GENE-U-003 |
| GENE-R-051 | M | IF a female holds sperm from several males THEN paternity SHALL follow a registry sperm-precedence rule (see GENE-OQ-04). | T-GENE-U-008 |
| GENE-R-052 | M | Offspring sex SHALL follow the sex-ratio mode. In `maintain` mode (default, target 70:30), each egg's probability of being male is adjusted by the deviation of the current population ratio from the target (controller documented in design). In `natural` mode it is 50:50. | T-GENE-U-009 |
| GENE-R-053 | M | Memories SHALL NOT be inherited: plastic weights start at template baseline. | T-GENE-U-010 |
| GENE-R-054 | M | THE SYSTEM SHALL record lineage for every fly: parents, generation (max of the parents' generations + 1), genome, and noise seed. | T-GENE-U-010 |

### 3.7 Identity and naming

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| GENE-R-060 | M | Each fly SHALL get an ID of the form `F` + a zero-padded sequence number (at least 4 digits), never reused. Its name is drawn deterministically (by seed) from a name list, and its folder is `F0001-rex`. | T-GENE-U-011 |
| GENE-R-061 | S | You MAY rename a fly. That changes only its display name; the ID and folder stay fixed. | T-GENE-U-011 |

### 3.8 Evolution metrics

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| GENE-R-070 | M | THE WATCHER SHALL compute, per fly day and per generation: allele mean and variance for each gene, and selection differentials (reproductive success against allele value). They are written to `evolution.parquet` (011). | T-GENE-U-012 |

## 4. Acceptance criteria

| ID | Criterion |
|---|---|
| GENE-AC-01 | Genesis produces exactly 70 males and 30 females with the configured preset mix. |
| GENE-AC-02 | **Phase 5 gate:** at least one full courtship → copulation → egg → larva → pupa → adult cycle happens with no scripts. The offspring's genome is a valid crossover + mutation of its logged parents. |
| GENE-AC-03 | In `maintain` mode, the adult sex ratio stays within ±5 percentage points of target over 5 generations (given enough births). |
| GENE-AC-04 | Offspring allele distributions match theory for crossover + mutation (statistical test over many synthetic matings). |
| GENE-AC-05 | Two flies with identical genomes but different noise seeds have different brains, and their measured traits differ. |
| GENE-AC-06 | A preset report lists, for every preset, whether its expected traits shifted relative to neutral controls. This is an honest report, not a pass/fail gate (CONST-7.3). |

## 5. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-GENE-U-001 | unit | Gene catalog schema and knob coverage. |
| T-GENE-U-002 | unit | Homologous targeting across sexes; sex-limited expression. |
| T-GENE-U-003 | unit | Crossover, mutation, clamping, determinism. |
| T-GENE-U-004 | unit | Developmental noise, asymmetry, non-inheritance. |
| T-GENE-U-005 | unit | Presets: schema, sex compatibility, custom genomes. |
| T-GENE-U-006 | unit | Genesis defaults and refusal on an existing colony. |
| T-GENE-U-007 | unit | Spawn options, naturalized placement, caps. |
| T-GENE-U-008 | unit | Sperm precedence. |
| T-GENE-U-009 | unit | Sex-ratio controller in both modes. |
| T-GENE-U-010 | unit | No memory inheritance; lineage records. |
| T-GENE-U-011 | unit | IDs and names. |
| T-GENE-U-012 | unit | Evolution metrics. |
| T-GENE-I-001 | invariant | Genes and presets touch only parameter values (static audit). |
| T-GENE-I-002 | invariant | 70:30 at genesis. |
| T-GENE-E-001 | emergence | Full life-cycle gate (Phase 5). |
| T-GENE-V-001 | validation | Preset expression report. |

## 6. Assumptions and open questions

| ID | Question | Proposal |
|---|---|---|
| GENE-OQ-01 | One allele per gene with per-gene crossover (the plan's choice) vs diploid genes with dominance (more realistic, keeps hidden variation). | Keep the plan's single-allele model for v1 (simpler, easier to read), with a diploid option noted for v2. |
| GENE-OQ-02 | Who drafts the first gene catalog (200–400 genes)? | I draft it in `design.md` from the knob categories; you review it. |
| GENE-OQ-03 | Genesis flies: age, maturity, mated state. | Ages spread over 2–5 fly days, sexually mature, unmated, full reserves. |
| GENE-OQ-04 | Sperm competition model. | Last-male precedence with probability 0.8 (`ASSUMPTION`, registry). |
| GENE-OQ-05 | In `maintain` mode, is the 70:30 target measured on adults, or on adults plus developing young? | Adults + pupae, to avoid oscillation. |
| GENE-OQ-06 | Name list source and style (e.g. "rex", "jasmine"). | A built-in list of ~2,000 short names; you can supply your own list. |
