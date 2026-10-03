# 001 — Connectome Pipeline & Foundations

| Field | Value |
|---|---|
| Status | Draft — awaiting review |
| ID prefix | `CONN` |
| Phase | 0 (Foundations and data) |
| Plan refs | §4.1, §2 (Art. 5–6), §13, §14, §15 Phase 0 |
| Depends on | 000 |
| Used by | 002, 004, 005, 007, 010, 014 |
| Constitution | CONST-5 (versioned templates), CONST-6 (Parameter Registry) |

## 1. Purpose

This spec turns published connectome datasets into versioned, checksummed **BrainTemplates** that the engine can load, one per sex. It also sets up two foundations every other spec relies on: the **config system** and the **Parameter Registry**.

## 2. Scope

**In scope**
- Downloading datasets and checking their licenses (v1: FlyWire FAFB v783 for females, MaleCNS v1.0 brain portion for males; v2 datasets such as BANC and the full MaleCNS CNS are catalogued only).
- BrainTemplate contents: neuron table, CSR edges, signs, spiking/graded flag, neuropil membership, modulatory/peptidergic neuron lists.
- The I/O map build and its validation. The *content* of the map is owned by 004 (senses), 005 (motor) and 006 (interoceptive routes).
- Cross-dataset cell-type matching and weight normalization between sexes.
- The cell-type-level graph used by the HYBRID and COARSE fidelities (014).
- Storage, manifests, checksums, deterministic builds, a memory cap for the 8 GB laptop.
- Config files and schemas; the Parameter Registry.

**Out of scope:** running the brain (002), what the senses and motor primitives mean (004/005), fitting rate-unit parameters (014), the larval connectome (v2).

## 3. Definitions

| Term | Meaning |
|---|---|
| BrainTemplate | The immutable, versioned package for one sex: neuron table + edges + I/O map + metadata. Example id: `female-fafb783-t1`. |
| I/O map | Versioned files that link sense channels ↔ sensory neuron groups, motor primitives ↔ DN/MN groups, and interoceptive routes ↔ target neurons. Every entry has a citation. |
| Type graph | A cell-type-level condensation of a template (~8–11k nodes, split by side) used by HYBRID and COARSE. |
| Registry | `config/params/registry.yaml`, the single source of every model parameter. |

## 4. Requirements

### 4.1 Acquisition and licensing

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| CONN-R-001 | M | THE PIPELINE SHALL fetch each source dataset from its official distribution and record in the manifest: source URL/API, dataset version, retrieval time and SHA-256 checksums of the raw files. | T-CONN-I-001 |
| CONN-R-002 | M | THE PIPELINE SHALL keep `data/LICENSES.md` with each dataset's license name, URL, required attribution text and usage restrictions (e.g. non-commercial). | T-CONN-U-005 |
| CONN-R-003 | M | IF a dataset has no license entry THEN THE PIPELINE SHALL refuse to build a template from it. | T-CONN-U-005 |
| CONN-R-004 | M | THE PIPELINE SHALL keep raw downloads under `data/raw/` (gitignored) and never modify them in place. | review |
| CONN-R-005 | M | WHERE a dataset needs authenticated access (neuPrint, CAVE/Codex) THE PIPELINE SHALL read credentials from environment variables and SHALL NOT write them to logs, manifests or the repository. | T-CONN-U-009 |

### 4.2 BrainTemplate contents

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| CONN-R-010 | M | THE PIPELINE SHALL produce a neuron table with at least: dense `neuron_id` (0..N−1), `source_id`, `cell_type`, `class`/`super_class`, `side` (L/R/center), `primary_neuropil`, `nt_pred` and its confidence, `sign`, `model` (spiking or graded), and the flags `is_sensory`, `is_descending`, `is_ascending`, `is_motor`, `is_modulatory`, `is_neurosecretory`. | T-CONN-U-001 |
| CONN-R-011 | M | THE PIPELINE SHALL store edges in CSR form sorted by presynaptic neuron, plus a transposed index, with `syn_count` and `weight = syn_count × sign(pre)`. Connections below the registry threshold `conn.min_synapses` are excluded, and the threshold is written to the manifest. | T-CONN-U-001, T-CONN-U-003 |
| CONN-R-012 | M | THE PIPELINE SHALL assign each neuron's fast sign from its predicted transmitter: ACh → +1, GABA → −1, glutamate → −1 by default. Per-cell-type exceptions and the treatment of DA, 5-HT, OA, tyramine and histamine come from the registry, each with a citation or an `ASSUMPTION` flag. | T-CONN-U-002 |
| CONN-R-013 | M | THE PIPELINE SHALL mark a neuron `graded` if its cell type is modelled as non-spiking in flyvis (Lappalainen et al. 2024) or is listed as non-spiking in the registry; every other neuron is `spiking`. | T-CONN-U-002 |
| CONN-R-014 | M | THE PIPELINE SHALL record, for each neuron, the fraction of its input and output synapses in every neuropil of the standard set (~80 neuropils). | T-CONN-U-001 |
| CONN-R-015 | M | THE PIPELINE SHALL produce lists, with a source for each entry, of neurons that release DA, 5-HT and OA and of peptidergic neurons for the peptides named in 002 (NPF, sNPF, Tk, DH44, insulin-like peptides, Crz, and others as registered). | T-CONN-U-006 |
| CONN-R-016 | M | For the male template, THE PIPELINE SHALL take the "brain portion" of MaleCNS using a documented rule (e.g. soma or majority of synapses in brain neuropils) and SHALL keep all descending and ascending neurons as the brain↔body interface. | T-CONN-V-002 |
| CONN-R-017 | M | THE PIPELINE SHALL keep sensory-neuron fragments and ascending-neuron fragments that enter the brain, labelled as such, so 004 can decide how to drive them. | T-CONN-U-001 |

### 4.3 I/O map

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| CONN-R-020 | M | THE PIPELINE SHALL build a versioned I/O map per template from source files in `config/iomap/`. Each entry has a citation. The map covers: sense channels → sensory neuron groups (004); motor primitives → DN/MN groups (005); interoceptive routes → target neurons (004/006). | T-CONN-U-004 |
| CONN-R-021 | M | IF an I/O map entry references a cell type or neuron missing from the template THEN THE PIPELINE SHALL fail the build and list every missing reference. | T-CONN-U-004 |
| CONN-R-022 | M | THE PIPELINE SHALL report I/O coverage: the share of sensory neurons and DNs that are mapped vs unmapped. Unmapped DNs are still simulated and logged. | T-CONN-U-004 |

### 4.4 Cross-dataset matching and normalization

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| CONN-R-030 | M | THE PIPELINE SHALL build a MaleCNS↔FlyWire cell-type correspondence table from the published matching. Sex-specific types are flagged as present in one sex only. | T-CONN-V-003 |
| CONN-R-031 | M | THE PIPELINE SHALL compute weight-normalization factors between the two templates so that the 002 validation assays give comparable responses in both sexes. The factors are stored in the manifest and the registry; the method is chosen in design. | T-BRAIN-V-003 |
| CONN-R-032 | S | THE PIPELINE SHALL report matched types whose synapse totals differ by more than a registry factor between datasets, for review. | T-CONN-V-003 |

### 4.5 Type graph (for HYBRID and COARSE)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| CONN-R-040 | M | THE PIPELINE SHALL produce, per template, a type graph: nodes = cell types split by side, edges = aggregated weights, plus a neuron → node membership map. Neurons in the "neuron-level sets" defined by 014 (mushroom body, central complex, sensory, DN/MN) are flagged. | T-CONN-U-008 |
| CONN-R-041 | M | Aggregation SHALL conserve total signed synaptic weight between node pairs. | T-CONN-U-008 |

### 4.6 Storage, versioning and determinism

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| CONN-R-050 | M | THE PIPELINE SHALL write tensors as safetensors and tables as Parquet, plus a `manifest.json` containing: template id, pipeline version (git hash), inputs and their checksums, parameters used, output checksums, and counts. | T-CONN-I-001 |
| CONN-R-051 | M | WHEN THE ENGINE loads a template it SHALL verify the output checksums, and SHALL refuse to load it on any mismatch. | T-CONN-I-001 |
| CONN-R-052 | M | THE PIPELINE SHALL be deterministic: the same inputs and pipeline version give byte-identical outputs. | T-CONN-I-002 |
| CONN-R-053 | M | THE PIPELINE SHALL stay under 6 GB of peak RAM (the laptop has 8 GB) by using streaming processing (Polars lazy / DuckDB). | T-CONN-P-001 |
| CONN-R-054 | M | Published templates SHALL be immutable. Any change produces a new template version, and checkpoints record the template version they use. | T-CONN-I-001 |
| CONN-R-055 | S | THE PIPELINE SHALL write templates to a configurable path, by default on the WSL2 ext4 filesystem (§13). | review |

### 4.7 Count validation

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| CONN-R-060 | M | THE PIPELINE SHALL compare neuron and synapse counts with published figures: FAFB v783 has 139,255 neurons and ~54.5M synapses at the published threshold. For MaleCNS v1.0 it records the brain-portion counts next to the full-CNS figure (166.7k neurons). IF a count is outside tolerance THEN the build fails. | T-CONN-V-001, T-CONN-V-002 |

### 4.8 Configuration

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| CONN-R-070 | M | THE SYSTEM SHALL read `config/colony.yaml`, `genesis.yaml`, `watcher.yaml` and the files under `config/iomap/` and `config/params/` through pydantic schemas. Unknown keys and out-of-range values are rejected with the file and line. | T-CONN-U-007 |
| CONN-R-071 | M | THE SYSTEM SHALL store a resolved config snapshot and its hash with every run and checkpoint. | T-WATCH-I-004 |
| CONN-R-072 | M | Config files SHALL be read only at start or restore. Runtime changes go only through the Control API (009). | review |

### 4.9 Parameter Registry

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| CONN-R-080 | M | Each registry entry SHALL have: `id` (dotted, e.g. `brain.lif.v_thresh`), `value`, `units`, `valid_range`, `scope` (global, sex, cell_type:X or class:Y), and exactly one of `source` (authors, year, DOI/URL, figure or table) or `assumption` (rationale, owner). Optional fields: `owner_spec`, `calibrated` (run id, date, objective) and `notes`. | T-CONN-U-006 |
| CONN-R-081 | M | THE ENGINE SHALL take every numeric model parameter from the registry or from template data. A lint check SHALL flag numeric literals in model packages (`brain`, `body`, `world`, `senses`, `motor`, `physiology`, `genetics`) unless they are whitelisted with a reason. | T-CONN-I-003 |
| CONN-R-082 | M | IF a referenced parameter is missing or outside its `valid_range` THEN THE ENGINE SHALL refuse to start and name the parameter. | T-CONN-U-006 |
| CONN-R-083 | M | THE SYSTEM SHALL generate a registry report: the count and share of `ASSUMPTION` entries per owner spec (CONST-6.3). | T-CONN-U-006 |
| CONN-R-084 | M | The registry SHALL be versioned by content hash, and the hash is recorded in every run manifest and checkpoint. | T-CONN-I-001 |
| CONN-R-085 | M | A calibration run SHALL change only parameters with a global scope (CONST-1.3), and SHALL record its run id and objective on every entry it changes. | T-CONN-U-006 |

## 5. Acceptance criteria

| ID | Criterion | Requirements |
|---|---|---|
| CONN-AC-01 | The FAFB v783 female template builds. Its neuron count equals 139,255 exactly, and its synapse count matches the published figure at the same threshold within ±0.5%. | R-010..017, R-060 |
| CONN-AC-02 | The MaleCNS brain-portion male template builds. Its counts are recorded, and every male-specific type in the matching table (e.g. P1) is present. | R-016, R-030, R-060 |
| CONN-AC-03 | Changing one byte of a template makes the engine refuse to load it. | R-050, R-051 |
| CONN-AC-04 | Two builds from the same inputs are byte-identical. | R-052 |
| CONN-AC-05 | The full build runs on the dev laptop with peak RSS ≤ 6 GB. | R-053 |
| CONN-AC-06 | An I/O map with a bad reference fails the build with a clear report; a valid map prints a coverage report. | R-020..022 |
| CONN-AC-07 | `data/LICENSES.md` covers every dataset, and a build without a license entry fails. | R-002, R-003 |
| CONN-AC-08 | The registry lint passes on the codebase, and the engine refuses to start when a parameter is missing. | R-080..085 |

## 6. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-CONN-U-001 | unit | Neuron table schema; CSR ↔ edge-list round trip; neuropil fractions sum to 1 per neuron. |
| T-CONN-U-002 | unit | Transmitter → sign mapping including registry exceptions; spiking/graded flag rules. |
| T-CONN-U-003 | unit | Synapse threshold applied and recorded. |
| T-CONN-U-004 | unit | I/O map validation, failure report, coverage report. |
| T-CONN-U-005 | unit | License gate. |
| T-CONN-U-006 | unit | Registry schema, missing and out-of-range refusal, assumption report, calibration scope rule. |
| T-CONN-U-007 | unit | Config schemas reject unknown keys and bad values. |
| T-CONN-U-008 | unit | Type-graph aggregation conserves weight; membership map is complete. |
| T-CONN-U-009 | unit | Credentials never appear in logs or manifests. |
| T-CONN-V-001 | validation | FAFB v783 counts. |
| T-CONN-V-002 | validation | MaleCNS counts and brain-portion rule. |
| T-CONN-V-003 | validation | Cross-dataset matching coverage and discrepancy report. |
| T-CONN-I-001 | invariant | Manifest checksums; tamper detection; version pinning. |
| T-CONN-I-002 | invariant | Byte-identical rebuild. |
| T-CONN-I-003 | invariant | No-magic-number lint over model packages. |
| T-CONN-P-001 | perf | Peak RAM of a full build on 8 GB. |

## 7. Assumptions and open questions

| ID | Question | Proposal |
|---|---|---|
| CONN-OQ-01 | **Licenses.** FlyWire data is thought to be under a non-commercial license, and the MaleCNS terms are unverified. Is this a non-commercial project? The answer affects sharing outputs such as videos and logs. | Verify both in Phase 0 and record them in `LICENSES.md` before any build. |
| CONN-OQ-02 | Synapse threshold for FAFB and for MaleCNS. | Use the Shiu et al. 2024 reference configuration for FAFB and the same value for MaleCNS unless the matching report suggests otherwise. |
| CONN-OQ-03 | Fast sign for dopaminergic, serotonergic, octopaminergic and peptidergic neurons. | Follow the reference model where it defines one; otherwise `ASSUMPTION` with sign 0 (modulatory only) and review after Phase 1. |
| CONN-OQ-04 | Glutamate can be excitatory at some synapses. | Default −1, with a per-type exception list in the registry. |
| CONN-OQ-05 | Weight-normalization method between datasets. | Decide in design: a global scale factor vs per-matched-type scaling, judged against the 002 assays. |
| CONN-OQ-06 | Sensory and ascending fragments from the VNC in brain-only templates. | Keep and label them (R-017); 004 decides how to drive them (see SENSE-OQ-01). |
| CONN-OQ-07 | `git init` happens in Phase 0 (plan §14). | Confirm at the start of Phase 0. |
