# Fly colony project setup

_Fly Colony decisions as of 2026-10-12: specs approved with all proposals accepted, multi-GPU portability required, native Windows, non-commercial, all work in C:\Users\FITT\the-fly-colony_

- 2026-10-12: the user approved all specs and told me to accept the recommendation for every open question. For any new open question, default to the recommended answer and list it so they can object.
- Multi-GPU portability is "very important" to the user. The colony must run on different GPUs and on CPU, with per-device fly limits: a hard limit from VRAM and a soft limit from speed. This is captured in spec 014 §5 (HW prefix). Never hard-code a GPU.
- All work stays inside C:\Users\FITT\the-fly-colony. The plan's WSL ext4 and D:\ paths don't apply.
- Runtime is native Windows, Python 3.12 + CUDA PyTorch, venv in this folder. The pure-PyTorch path comes first.
- The project is non-commercial. Still verify each dataset's license in Phase 0.
- Dev PC: RTX 4000 SFF Ada 20 GB (~280 GB/s), 64 GB RAM, Core Ultra 9 285.

**Why:** These are the user's answers and requests in the first session.
**How to apply:**
- As of 2026-10-12, Phase 0 is complete. PR #3 was merged. Branch `phase0/peptides-iomap` (D7 full I/O map, D8 cited peptides, templates bumped to t2) is pushed and awaiting merge.
- 2026-10-13: Phase 1 (spec 002 brain engine) was merged as PR #5 (main 822d83f). Only E3 (a second GPU tier) is open, because no second GPU is available. The production model runs at RTF ~0.1 on the RTX 4000, so fused kernels (Phase 9) matter.
- Datasets are in data/raw and templates in data/templates (both gitignored).
- The user was unhappy that items were left "not done" after the merge. Finish deliverables fully instead of deferring them to later specs when the data allows it. See [finish-deliverables](finish-deliverables.md). Related: [git-pr-workflow](git-pr-workflow.md)
