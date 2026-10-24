# Agent memory

Project memory for AI coding agents (Claude Code) working on this repository. It holds what the
code and git history don't: the owner's decisions, working agreements, machine quirks, the current
investigation state, and the one-off scripts behind each finding. It is kept in the repo so that
any session on any machine can pick up the work. The root [`CLAUDE.md`](../../CLAUDE.md) points
here and is loaded automatically.

| File | What it holds |
|---|---|
| [phase2-status.md](phase2-status.md) | **Start here.** Current Phase 2 state, model changes and why, open decision, run costs, history |
| [git-pr-workflow.md](git-pr-workflow.md) | Branch → commit → push → compare link; the owner opens and merges PRs |
| [fly-colony-project-setup.md](fly-colony-project-setup.md) | Owner decisions from the first session (specs approved, portability, native Windows) |
| [finish-deliverables.md](finish-deliverables.md) | Finish feasible tasks fully; name real blockers only |
| [dev-pc-quirks.md](dev-pc-quirks.md) | Windows dev-PC gotchas (App Control DLL blocks, cp1252, CRLF, WDDM VRAM) |
| [diagnostics/](diagnostics/) | Investigation scripts (and their JSON outputs) cited in phase2-status.md |
| [report/](report/) | Generator and template for the Phase 2 HTML run report |

Keep this current: when a decision, finding or state changes, update the relevant file here in
the same commit as the work. Dates are absolute.
