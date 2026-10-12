# 001 — Connectome Pipeline & Foundations: Design

| Field | Value |
|---|---|
| Status | Draft (written after spec approval, 2026-10-12) |
| Implements | [spec.md](spec.md) (CONN-R-001..085), plus the Phase-0 part of 014 §5 (HW-R-001, -002, -005, -010) |
| Tasks | [tasks.md](tasks.md) |

This document describes **how** spec 001 is built. Where it makes a choice the spec left open (`TBD` / "decide in design"), the choice is marked **Decision**.

---

## 1. Data sources and licenses (CONN-R-001..005, CONN-OQ-01)

Licenses were checked on 2026-10-12. Every dataset is registered in `config/datasets.yaml`. That file is the machine-readable source; `data/LICENSES.md` is generated from it and committed.

| Dataset id | Role | Source | Version / pin | License | Status |
|---|---|---|---|---|---|
| `fafb783_connectome` | Female connectivity, neuropil counts, proofread ids | Zenodo record 10676866 | 783.0 | CC BY 4.0 | verified (Zenodo license field) |
| `fafb783_annotations` | Female cell types, classes, side, transmitter | GitHub `flyconnectome/flywire_annotations` | tag v3.2.0 (`a83b277`) | None in the repo; published as supplementary data of Schlegel et al. 2024 (*Nature* 634, open access, CC BY 4.0) | **assumed**: confirm with authors before any public redistribution |
| `shiu2024_model` | Reference model inputs (validation in 002) | GitHub `philshiu/Drosophila_brain_model` | commit `91bdd1e` | MIT (code); the data is derived from FlyWire 783 (CC BY 4.0) | verified (LICENSE file) |
| `malecns_v1` | Male neurons, NT predictions and per-ROI counts (`Neuprint_Neurons.feather`, `roiInfo`), ROI hierarchy (`Neuprint_Meta.csv`), traced-only connection weights | Janelia `male-cns.janelia.org` public GCS bucket (flat-connectome + neuprint-inputs) | v1.0 | CC BY 4.0 | verified (download page) |

**Note on CONN-OQ-01.** The project is non-commercial, but the expected non-commercial restriction does not apply: the v1 datasets are CC BY 4.0. Only attribution is required, and the attribution text is in `LICENSES.md`.

- `datasets.yaml` holds each file's URL, expected size, and checksum (Zenodo publishes MD5; SHA-256 is pinned after the first verified fetch).
- The fetcher (`colony data fetch <id>`) downloads into `data/raw/<id>/`, then writes `data/raw/<id>/_source.json` with the URL, version, retrieval time and SHA-256 of each file. Raw files are never modified (CONN-R-004).
- **Decision:** the 9.5 GB per-synapse table (`flywire_synapses_783.feather`) is **not** fetched in v1. Per-pair counts and per-neuron neuropil counts are enough for every Phase-0 requirement. Fetching it is an opt-in flag.
- **License gate (CONN-R-003):** the template builder refuses a dataset whose `license` block is missing or whose status is not `verified` or `assumed`. `assumed` entries are listed in red in the build report.
- **Credentials (CONN-R-005):** the bulk sources need none. neuPrint/Codex tokens, if ever used, come only from `NEUPRINT_APPLICATION_CREDENTIALS` / `CODEX_API_TOKEN`. A `redact()` helper scrubs them from every log line and manifest field.

## 2. Package layout

```
src/flycolony/
  config/       pydantic schemas + YAML loader with line numbers (CONN-R-070..072)
  registry/     Parameter Registry: schema, loader, lookup, report, calibration rule (CONN-R-080..085)
  hardware/     device layer, hardware probe, tiers (014 HW-R-001/002/005/010)
  connectome/   datasets & licenses, fetch, BrainTemplate build/load/verify, I/O map, type graph
  console/      `colony` CLI (Typer)
  brain/ body/ world/ senses/ motor/ physiology/ genetics/ comms/ engine/ watcher/ tasks/   (later phases)
tools/lint.py   no-magic-number and device lints (CONN-R-081, HW-R-002)
```

`import-linter` contracts (in `pyproject.toml`) forbid engine packages from importing the Watcher, console and tasks, and forbid production code from importing `tests` (CONST-1.4).

## 3. Configuration (CONN-R-070..072)

- Files: `config/colony.yaml`, `genesis.yaml`, `watcher.yaml`, `hardware.yaml`, `datasets.yaml`, `config/iomap/<sex>/*.yaml`, and `config/params/registry.yaml` (plus `config/params/*.yaml` fragments).
- Every schema is a pydantic v2 model with `extra="forbid"`.
- **Line numbers:** the loader composes YAML with `yaml.compose()`, builds a map from each value's path to its line, and turns each `ValidationError` location into `file:line: message`.
- A config **snapshot** is the canonical JSON of all resolved configs (sorted keys, no whitespace). Its SHA-256 is the config hash (CONN-R-071, used by 009).
- Configs are read once at start or restore. There is no hot reload; runtime changes go through the Control API (009).

## 4. Parameter Registry (CONN-R-080..085)

- `config/params/registry.yaml` holds a list of entries:
  ```yaml
  - id: brain.lif.v_thresh
    value: -45.0
    units: mV
    valid_range: [-70.0, -20.0]
    scope: global            # global | sex:<f|m> | cell_type:<X> | class:<Y>
    source: {authors: "Kakaria & de Bivort", year: 2017, doi: "10.3389/fnbeh.2017.00008", where: "Shiu et al. 2024 model.py default_params"}
    owner_spec: "002"
  ```
- Each entry has exactly one of `source` or `assumption: {rationale, owner}` (validated). Values may be numbers, lists of numbers, or strings for categorical parameters (e.g. sign rules); `valid_range` applies to numbers only.
- `Registry.require(ids)` is called at engine start with every id the model references. Any missing or out-of-range id raises `RegistryError`, naming each one (CONN-R-082).
- **Content hash:** SHA-256 of the canonical JSON of the sorted entries (CONN-R-084).
- **Report:** `colony registry report` prints the count and share of `ASSUMPTION` entries per `owner_spec` (CONN-R-083).
- **Calibration (CONN-R-085):** `apply_calibration(registry, changes, run_id, objective)`. Every changed entry gets `calibrated: {run_id, date, objective}`. The scope grammar has no per-fly or per-situation form, so calibration is global by construction (CONST-1.3). The function also refuses unknown ids and out-of-range values.
- **Lint (CONN-R-081):** `tools/lint.py` scans model packages with `ast`. It flags any numeric literal other than `0`, `1`, `-1`, `0.5` and `2`. Literals inside type hints and subscripts (indexing, slicing, shapes) are ignored. A line can opt out with `# registry-ok: <reason>`. The lint runs in the test suite (T-CONN-I-003).

## 5. BrainTemplate build

### 5.1 Pipeline (Polars lazy, streaming; CONN-R-053)

1. **Neuron set.**
   - Female: `proofread_root_ids_783.npy`.
   - Male: annotation rows with `status == "Traced"` (or the documented equivalent), minus non-neuronal bodies.
   - Dense `neuron_id` = rank of `source_id` in ascending order, so ids are deterministic.
2. **Annotations.** Join on `source_id`:
   - `cell_type`, `super_class`, `cell_class`, `side`, `nt_pred` and `nt_conf`.
   - Female: `top_nt` / `top_nt_conf` from annotations. Where they are missing, use the argmax of the synapse-weighted average transmitter probabilities over the neuron's outgoing connections.
   - Male: the body-neurotransmitters table.
   - `side` is normalized to `L`/`R`/`C`.
3. **Flags (CONN-R-010).** Each flag comes from `super_class`, using a rule table in `config/params/connectome.yaml`:
   - `is_sensory` ← sensory
   - `is_descending` ← descending
   - `is_ascending` ← ascending
   - `is_motor` ← motor
   - `is_neurosecretory` ← endocrine
   - `is_modulatory` ← `nt_pred` ∈ {dopamine, serotonin, octopamine} or listed in `modulatory.yaml`
4. **Sign (CONN-R-012, CONN-OQ-03/04).** Read `conn.sign.<nt>` from the registry.
   - **Transmitter rule:** ACh +1, GABA −1, Glu −1, DA/5-HT/OA +1. This follows the reference model's convention (Shiu et al. 2024: GABA and glutamate inhibitory, everything else excitatory).
   - **Decision (FAFB, CONN-OQ-03), measured 2026-10-12:** no way of deriving a per-neuron transmitter from the release reproduces the reference model's per-neuron signs.
     - Agreement: synapse-weighted mean 95.7%, annotation `top_nt` 95.6%, per-connection vote 95.9%, unweighted mean 95.2%.
     - So for the female template, the sign is taken **directly from the reference model** (`Connectivity_783.parquet`, `Excitatory`, per presynaptic neuron; `conn.fafb.sign_source = reference`). This is the literal reading of "follow the reference model where it defines one", and it makes the Phase-1 comparison like-for-like.
     - The 1,250 neurons the reference does not cover use the transmitter rule.
   - **Precedence:** registry exception > reference > transmitter rule. The winning rule is stored per neuron in `sign_source`.
   - **Male:** the transmitter rule on the per-body `predictedNt` (`conn.male.nt_source`).
   - **Determinism:** the synapse-weighted transmitter means are summed as fixed-point integers, so parallel summation order cannot change the result (CONN-R-052).
   - Per-type exceptions go in `conn.sign_exceptions` (registry).
5. **Model flag (CONN-R-013).** A neuron is `graded` if its cell type is in `conn.graded_cell_types`, the flyvis (Lappalainen et al. 2024) cell-type list mapped to FlyWire names, or in the registry's extra list. Every other neuron is `spiking`.
6. **Edges (CONN-R-011).**
   - Aggregate connections over neuropils to (pre, post) pairs, summing `syn_count`.
   - Drop pairs with `syn_count < conn.min_synapses`.
   - **Decision (CONN-OQ-02):** `conn.min_synapses = 1`, the Shiu et al. 2024 reference configuration. Checked against the data on 2026-10-12: its `Connectivity_783.parquet` keeps every proofread pair (minimum 1 synapse), giving 15,091,983 pairs and 54,492,922 synapses. That is the published ~54.5M figure. Codex's "≥ 5 synapses" is only a display threshold.
   - `weight = syn_count × sign(pre)`.
   - Sort by (pre, post) to give CSR `indptr` (int64, N+1), `indices` (int32), `syn_count` (int32) and `weight` (float32).
   - Transposed index: `t_indptr`, `t_indices` (pre ids sorted by post), and `t_perm` (int64, the CSR edge index of each transposed edge).
7. **Neuropil fractions (CONN-R-014).** From per-neuron per-neuropil pre and post counts, compute `pre_frac` and `post_frac` per (neuron, neuropil). This is a long-format Parquet table; fractions sum to 1 for each neuron that has synapses. `primary_neuropil` is the argmax of pre + post.
8. **Modulatory and peptidergic lists (CONN-R-015).**
   - `config/params/modulatory.yaml` maps peptide → cell types, each with a source.
   - Aminergic neurons come from the transmitter predictions.
   - The build resolves each list to neuron ids, stored in `modulatory.parquet` (`neuron_id`, `substance`, `source_ref`).
9. **Male brain portion (CONN-R-016).**
   - **Neuron set:** bodies with `status == Traced` (165,122).
   - **Decision:** keep a neuron if more than half of its synapses lie in the brain ROI groups `CentralBrain`, `Optic(L)` and `Optic(R)` (`conn.male.brain_rois`) rather than `VNC` and `CV` (`conn.male.vnc_rois`). These are the top-level children of `CNS` in the release's ROI hierarchy.
   - **Units:** synapses are counted as neuPrint `downstream` + `upstream` synapse pairs. neuPrint `pre` counts T-bars, while FlyWire counts pairs, so pairs make the two sexes comparable.
   - Always keep descending and ascending neurons (super_class), and sensory neurons with any brain synapses.
   - **Neuropil fractions** use the release's `primaryRois` (144 non-overlapping ROIs).
   - **Vocabulary:** MaleCNS superclasses are mapped onto the FlyWire `super_class` vocabulary (table `SUPERCLASS` in `connectome/male.py`).
   - The rule and its counts go into the manifest.
10. **Fragments (CONN-R-017).** In the female data, sensory and ascending fragments are proofread ids and are kept with their flags. In the male data, they are kept by step 9.

### 5.2 Cross-dataset matching and normalization (CONN-R-030..032)

- **Correspondence:** the female annotations carry `hemibrain_type`, and MaleCNS annotations carry FlyWire/hemibrain type matches (`flywireType` / `type` columns).
  - Build `type_match.parquet` (`male_type`, `female_type`, `match_source`, `sex_specific`).
  - Types present in one sex only are flagged.
- **Decision (CONN-OQ-05):** start with a **global scale factor** per template, `s = median over matched types of (female in-degree weight / male in-degree weight)`.
  - It is stored in the manifest and in the registry as `conn.norm.male_scale`.
  - Per-type scaling is held back until the 002 assays show it is needed.
- The **discrepancy report** lists matched types whose total synapses differ by more than `conn.match.discrepancy_factor` (CONN-R-032).

### 5.3 Type graph (CONN-R-040, -041)

- **Node key:** `(cell_type, side)`. Untyped neurons become singleton nodes keyed by `untyped:<source_id>`.
- **Edges:** sum of signed `weight` over all neuron pairs between two nodes, plus summed `syn_count`. Conservation holds by construction, and a test checks it.
- **Membership:** `type_membership.parquet` (`neuron_id` → `node_id`).
- **Neuron-level set flags (owned by 014):** `in_mb`, `in_cx`, `is_io` (sensory/DN/MN). The rule uses `primary_neuropil` ∈ `conn.neuron_level.mb_neuropils` / `cx_neuropils` and the flags; it is versioned in the registry.

### 5.4 I/O map (CONN-R-020..022)

- `config/iomap/<sex>/{senses,motor,interoceptive}.yaml`. Each entry is:
  ```yaml
  - channel: taste.sugar.labellar      # or primitive: walk.backward
    select: {cell_type: [...]} | {cell_class: ...} | {source_id: [...]}
    citation: "..."
  ```
- The build resolves every selector against the template. Any unresolved reference fails the build, and every missing one is listed (CONN-R-021).
- The coverage report gives the shares of sensory neurons and DNs that are mapped vs unmapped (CONN-R-022).
- Content is owned by 004/005/006. Phase 0 ships only a small, cited seed so the mechanism is tested on real data.

### 5.5 Storage, manifest and verification (CONN-R-050..055)

```
data/templates/<template_id>/
  neurons.parquet           one row per neuron (schema in §5.1)
  neuropil_fractions.parquet
  edges.safetensors         indptr, indices, syn_count, weight, t_indptr, t_indices, t_perm
  modulatory.parquet
  type_nodes.parquet  type_edges.parquet  type_membership.parquet
  iomap.json                resolved I/O map (+ coverage)
  manifest.json
```

- **Template ids:** `female-fafb783-t1` and `male-malecns1-t1`. The suffix `tN` increases on any change, and published templates are never overwritten (CONN-R-054). The builder refuses to write into an existing id.
- **Manifest:**
  - template id
  - pipeline version (`git describe --always --dirty`)
  - inputs: each dataset id, version and per-file SHA-256
  - parameters used (registry ids → values) and registry hash
  - counts
  - outputs: per-file SHA-256 and size
  - Keys are sorted. **No timestamps**, so rebuilds are byte-identical (CONN-R-052). Retrieval times live in `data/raw/<id>/_source.json`.
- **Determinism:** Parquet is written with pyarrow, fixed compression (zstd level 3), fixed row-group size, no statistics timestamps, and sorted rows. Safetensors are written with sorted keys and fixed metadata.
- **Load (CONN-R-051):** `load_template(path)` re-hashes every output file against the manifest. Any mismatch raises `TemplateIntegrityError` and nothing is loaded.
- **Location (CONN-R-055):** `colony.yaml: paths.templates`, default `data/templates` inside the project folder. That replaces the plan's WSL ext4 default, per the owner's choice of native Windows with all work in this folder.
- **Memory (CONN-R-053):** each step is a Polars lazy query with `collect(engine="streaming")`. The builder records peak RSS with `psutil` (sampled in a thread), writes it to the build report, and fails above `conn.build.max_rss_gb` (default 6).

### 5.6 Count validation (CONN-R-060)

- Registry entries `conn.expected.fafb783.neurons = 139255` (Dorkenwald et al. 2024) and `conn.expected.fafb783.synapses` (published figure at the release threshold), with tolerance `conn.expected.tolerance = 0.005`.
- The female build fails outside tolerance. For the male template, the full-CNS figure and the brain-portion counts are recorded side by side.

## 6. Hardware layer (014 HW-R-001/002/005/010, Phase-0 part)

- `flycolony.hardware.probe()` returns a `HardwareInfo` (pydantic) with:
  - OS and Python, torch, CUDA and driver versions
  - each CUDA device's name, total and free VRAM, and compute capability
  - system RAM, CPU cores
  - free disk at the configured paths
- `select_device(spec="auto")` is the **only** place that names a device. It returns `torch.device` for `auto` (CUDA:0 if usable, else CPU), `cuda[:N]` or `cpu`.
- `classify_tier(info)` returns `cpu`, `low`, `mid`, `high` or `ultra` by VRAM, with thresholds from `config/hardware.yaml`.
- The capacity benchmark and limits (HW-R-011..016) come in Phase 1 and Phase 5.
- **Lint (HW-R-002):** `tools/lint.py` also flags `"cuda"` / `"cpu"` string literals and `torch.device(` calls outside `flycolony/hardware/`.

## 7. CLI

| Command | Does |
|---|---|
| `colony data list` | Datasets, licenses, fetch status |
| `colony data fetch <id>… [--with-synapses]` | Download + verify + `_source.json` |
| `colony data licenses` | Regenerate `data/LICENSES.md` |
| `colony template build <sex> [--id]` | Build one BrainTemplate (+ report) |
| `colony template verify <path>` | Checksum verification |
| `colony registry report` | ASSUMPTION share per spec |
| `colony hardware probe` | Print `HardwareInfo` and tier |

## 8. Testing

Tests follow spec §6. Unit tests use **synthetic** mini-connectomes (a few dozen neurons built in-memory), so they run in CI without downloads. Validation tests (`T-CONN-V-*`) are marked `data` and skip when `data/raw` is absent. The determinism test builds a synthetic template twice and compares bytes. A real-data rebuild check is run manually and recorded in the build report.

## 9. Deviations and notes

- The plan's WSL2/ext4 template location is replaced by `data/templates` in the project (owner decision 2026-10-12). PERF-R-009/010 already allow configurable paths.
- `fafb783_annotations` has no explicit repository license (§1). The build accepts it as `assumed` and says so in every build report.
- **FAFB neuropil counts:** the per-neuron count tables cover every segment (43M post rows), not just proofread neurons. The adapter filters to proofread ids while scanning; without this, peak RAM was 6.9 GiB.
- **Windows Application Control** on the dev PC blocks some native extension modules: import-linter's `grimp` and `pyarrow.dataset`. Import contracts are checked by a pure-Python checker (`tools/lint.py`), and the MaleCNS reader uses the core Arrow IPC reader. This keeps the pipeline working on locked-down machines (spec 014 HW-R-001).
- **Pipeline version:** `git describe --dirty` ignores untracked files, so the version is the commit hash plus `-dirty` if anything under `src/`, `config/`, `tools/` or `pyproject.toml` is uncommitted.
