# The Fly Colony

A colony of virtual fruit flies whose behavior comes only from simulated connectome brains, observed by a hidden Watcher. The specs are the source of truth:

- [`plans/fuzzy-hugging-newt.md`](plans/fuzzy-hugging-newt.md): the master plan
- [`specs/`](specs/README.md): the constitution and 14 feature specs (approved 2026-10-12)

**Status:** Phase 1 (brain engine). Phase 0 is complete ([`001 tasks`](specs/001-connectome-pipeline/tasks.md)); Phase 1 progress is in [`002 tasks`](specs/002-brain-engine/tasks.md).

## Runs on different hardware

The same code runs on any NVIDIA GPU supported by the installed PyTorch build, and on CPU only (spec 014 §5). A weaker machine is allowed fewer flies and lower fidelity, based on measured limits. Check what the colony sees on your machine:

```bash
colony hardware probe
colony hardware benchmark    # measures this device; prints "up to N flies in real time, M max"
```

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev          # creates .venv; installs CUDA 12.8 PyTorch on Windows/Linux
```

On a machine without an NVIDIA GPU, the CUDA wheel still runs on CPU. For a smaller download, you can install the CPU wheel instead: `uv pip install torch --index-url https://download.pytorch.org/whl/cpu`.

## Data and BrainTemplates

Raw datasets and built templates live under `data/` and are not committed. Licenses are in [`data/LICENSES.md`](data/LICENSES.md); FAFB v783 and MaleCNS v1.0 are CC BY 4.0.

```bash
colony data fetch                  # ~3 GB FAFB + ~6.5 GB MaleCNS, checksum-verified, resumable
colony template build female       # female-fafb783-t2: 139,255 neurons, 15.1M edges (~5 s, ~3.5 GB RAM)
colony template build male         # male-malecns1-t2: brain portion of MaleCNS (~5 s, ~5 GB RAM)
colony template match              # cross-sex type matching + normalization factor
colony template verify data/templates/female-fafb783-t2
python tools/gen_iomap.py         # regenerate config/iomap from its cited rules (optional)
colony registry report             # share of ASSUMPTION parameters per spec
```

## Brain engine (spec 002)

Batched LIF + graded simulator in pure PyTorch (CPU or any CUDA GPU), validated against the
Shiu et al. 2024 Brian2 model. Reports are in [`specs/002-brain-engine/reports/`](specs/002-brain-engine/reports/).

```bash
uv sync --extra dev --extra reference                          # adds Brian2 for the reference harness
colony data fetch shiu2024_model flyvis_pretrained
python tools/reference_brian2.py sugar --procs 8               # Brian2 reference (also: sugar_bitter, water, jon_ce)
python tools/gen_flyvis_params.py                              # graded time constants from the flyvis ensemble
colony brain validate        # engine vs Brian2 (BRAIN-R-081)
colony brain gate            # timestep gate for the production model (BRAIN-R-021)
colony brain male            # male-template assays and cross-sex comparability (BRAIN-R-082)
```

## Tests

```bash
uv run pytest            # unit + invariant tests (synthetic data); validation tests run when data/ is built
uv run python tools/lint.py   # no magic numbers, no hard-coded devices, import contracts
uv run ruff check src tests tools
```

## Layout

```
specs/          constitution + feature specs (spec.md, design.md, tasks.md)
config/         colony/genesis/watcher/hardware YAML, datasets catalog, Parameter Registry, I/O map
src/flycolony/  config, registry, hardware, connectome, brain, console (later: body, world, ...)
tests/          unit, validation, emergence, invariants, perf
tools/          lint.py (static checks), gen_iomap.py, gen_flyvis_params.py, reference_brian2.py
```
