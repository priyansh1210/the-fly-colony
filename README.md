# The Fly Colony

A colony of virtual fruit flies whose behavior comes only from simulated connectome brains, observed by a hidden Watcher. The specs are the source of truth:

- [`plans/fuzzy-hugging-newt.md`](plans/fuzzy-hugging-newt.md): the master plan
- [`specs/`](specs/README.md): the constitution and 14 feature specs (approved 2026-10-12)

**Status:** Phase 0 (foundations and data). See [`specs/001-connectome-pipeline/tasks.md`](specs/001-connectome-pipeline/tasks.md).

## Runs on different hardware

The same code runs on any NVIDIA GPU supported by the installed PyTorch build, and on CPU only (spec 014 §5). A weaker machine is allowed fewer flies and lower fidelity, based on measured limits. Check what the colony sees on your machine:

```bash
colony hardware probe
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
colony template build female       # female-fafb783-t1: 139,255 neurons, 15.1M edges (~5 s, ~3.5 GB RAM)
colony template build male         # male-malecns1-t1: brain portion of MaleCNS (~5 s, ~5 GB RAM)
colony template match              # cross-sex type matching + normalization factor
colony template verify data/templates/female-fafb783-t1
colony registry report             # share of ASSUMPTION parameters per spec
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
src/flycolony/  config, registry, hardware, connectome, console (later: brain, body, world, ...)
tests/          unit, validation, emergence, invariants, perf
tools/lint.py   static checks used by the test suite
```
