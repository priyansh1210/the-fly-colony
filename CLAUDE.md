# The Fly Colony: notes for Claude Code

A colony of virtual fruit flies whose behaviour comes only from simulated connectome brains
(FlyWire FAFB v783 female, MaleCNS male). The specs in `specs/` (constitution `000-constitution.md`
plus 14 feature specs) and the plan in `plans/` are the source of truth.

**Read [`docs/agent-memory/README.md`](docs/agent-memory/README.md) first.** It holds the owner's
decisions, the current state of the work (`phase2-status.md`), and how to resume it.

## Working agreements

- Work on a feature branch; never commit to `main`. Push to github.com/priyansh1210/the-fly-colony
  and send the compare link. The owner opens and merges PRs, so don't run `gh pr create`.
- Every biological parameter lives in the Parameter Registry (`config/params/*.yaml`) with a source
  (verify DOIs) or a documented ASSUMPTION. Literals in code need a `# registry-ok:` reason.
- No gate-specific tuning. Calibrations use rest-only rules stated before the run. Criteria are not
  changed after seeing results without the owner's explicit approval, recorded as an amendment in
  the report (CONST-7.3).
- Finish feasible tasks fully. Name only real blockers.
- Report every result as it comes, failures included.
- Update `docs/agent-memory/` in the same commit when state or decisions change.

## Environment (native Windows)

- Python 3.12 venv in `.venv` (uv). Run with `.venv/Scripts/python.exe`; the system python lacks
  torch. CLI: `python -m flycolony.console.cli` (`colony`).
- Set `PYTHONIOENCODING=utf-8` (cp1252 console). Text outputs must be written with `newline="\n"`.
- Never hard-code a GPU: the colony must run on any GPU or on CPU (spec 014 §5).
- Long GPU jobs: start them detached (PowerShell `Start-Process`, logs in `.colony/`).
- Tests: `.venv/Scripts/python.exe -m pytest tests`. The emergence and validation tests read
  stored reports and fail when `model_hash` changes until the gates are re-run.
- Lint: `.venv/Scripts/ruff.exe check . && .venv/Scripts/ruff.exe format --check .`; import
  contracts in `tools/lint.py`.
- `data/` (raw datasets and built templates) is not committed; see README.md to fetch and build it.
