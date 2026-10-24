# Phase 2 status (embodied fly): branch `phase2/body-senses-motor`

Last updated 2026-10-24. The newest state is at the top; history follows.

## Current state

The branch is pushed; the latest work commit is d96bc4f. It is not PR-ready, because the
emergence gates fail.

**Second full gate run** (female `female-fafb783-t2`, n = 50 per arm, ~9.5 h; reports in
`specs/005-motor/reports/`):

| Gate | Result |
|---|---|
| AC-07 no self-motion | PASS 50/50 |
| AC-01 feeding | FAIL 0/50 vs 0/50 |
| AC-02 bitter | FAIL 0/50 vs 0/50 (no feeding to suppress) |
| AC-04 plume | FAIL 0/50 vs 0/50 |
| AC-05 sleep | FAIL 0 vs 0 sleep minutes |
| AC-03 looming | BLOCKED: needs the FlyWire Codex "Visual Neuron Columns" file in `data/raw/flywire_columns/` (user download, login required), then 004 S8 |

The male template passes its timestep gate (dt 0.5 ms, r = 0.996) and its validation assays.
`specs/005-motor/tasks.md` M10 is not ticked.

**Feeding diagnosis** (`diagnostics/feed_diag.py`, 16 flies, gate conditions):
- The proboscis group rate averages 24 Hz on sucrose vs 11.5 Hz on water, so sugar does drive it.
- In both arms, CB0216 bursts reach ~100 Hz peaks.
- The M8 rule (q0.99 of the instantaneous resting rate) therefore set the threshold to 92.5 Hz.
- Maximum proboscis extension is ≤ 0.11, against the 0.5 needed (`gate.feed.min_extension`).

**Plume and sleep:** not diagnosed on this model. On the first run the causes were that flies
barely walked and that steering twitches broke every immobility bout (a bout needs 12.5 s).

**Open decision (the user's to make):**
- (a) Amend the M8 threshold rule so short bursts don't set it, for example q0.99 of a rate averaged over a longer window. This is a post-hoc rule change, so it needs explicit approval and an amendment record (CONST-7.3).
- (b) Keep the rules and keep fixing the model: the CB0216 bursts, and the antennal-lobe LN loop at ~115 Hz.
- Proposed next step: diagnose plume and sleep (~1 GPU-h), then bring one combined proposal.
- The HTML report artifact still shows the first run; see "Report" below.

## Model changes made in Phase 2

All are production-variant only. The reference (Shiu et al. 2024) variant is unchanged.

1. **LB3b taste mapping** (97ed66d): LB3b is the `sugar_low_salt` channel.
2. **Electrical eLN→PN** (ed22bb1): `brain.electrical.excitatory_pairs: ["ALLN>ALPN"]`.
   - Chemical edges from excitatory AL local neurons onto PNs get weight 0, because that coupling is electrical (Yaksi & Wilson 2010, doi 10.1016/j.neuron.2010.08.041).
   - Without this the resting brain ignited irreversibly into a ~20 Hz state starting in the AL.
   - Report: `specs/002-brain-engine/reports/female-fafb783-t2.ignition-diagnostic.json`.
3. **Background noise** `brain.noise.w` = 1.4 mV (`tools/calibrate_noise.py`).
   - Rule: the largest kick with central-brain rest mean in [1, 4] Hz and no runaway. Result: 3.6–3.7 Hz.
   - The user approved dropping the Kenyon-cell criterion (amendment in the report).
4. **Per-connection synapse cap** (9dc49fb): `brain.syn.max_synapses` = 250 (`tools/calibrate_cap.py`).
   - Rule, rest only: the largest scanned cap with no neuron outside the AL self-sustained once background input and AL output are off.
   - Uncapped, 33 neurons latch through reciprocal pairs (CB0216 L↔R 451/455 synapses, MN9, DNge022, ...). The cap removes all of them.
   - The user chose this over depression on 2026-10-23.
   - Validation only, not used to choose the cap: MN9 rest 17 Hz, sugar 60, sugar+bitter 7; DM1 odour PN 86 Hz.
5. **Short-term depression** is implemented in the engine (`brain.syn.depression.*`; Nagel, Hong & Wilson 2015 doi 10.1038/nn.3895, f = 0.78, τ = 893 ms) but **disabled** (keep = 1.0).
   - Applied to every neuron, it turns sustained responses into ~50 ms transients and fails the sugar→MN9 validation.
6. **Motor thresholds** (M8, 8a29d10): walk_forward 41, walk_backward 9.5, steer 60, landing 18.5, proboscis 92.5, ingestion 41.5, groom 25 Hz; escape is a trigger.

**Known limitation:** the AL LN network is self-sustained at ~115 Hz at every cap.
- It comes from excitatory LN→LN and LN→ORN chemical loops.
- Dropping eLN→eLN fixes it, but that step has no citation.
- Re-signing by FlyWire `known_nt`, then type consensus, did not help (12,065 sign changes).

## Rules that bind this work

- No gate-specific tuning. Calibrations use rest-only, pre-stated rules.
- Criteria never change after seeing results without the user's explicit approval, and every amendment is written into the report (CONST-7.3).
- Every parameter needs a citation or a documented ASSUMPTION in `config/params/*.yaml`. Verify DOIs on Crossref; one was wrong once.
- Report results as they come, failures included.

## How to run things

- Use `.venv/Scripts/python.exe` (the system python has no torch). Set `PYTHONIOENCODING=utf-8`, plus `PYTHONUNBUFFERED=1` for live logs.
- Long GPU jobs: launch detached with PowerShell `Start-Process ... -RedirectStandardOutput .colony\x.log` (`.colony/` is gitignored). Bash background tasks are capped at 1 h.
- Costs on an RTX 4000 SFF Ada:
  - full gate run `colony gates run`: ~9.5 h
  - timestep gate `colony brain gate --sex female|male`: ~20 min
  - M8 `tools/calibrate_motor.py --warmup 3`: ~25 min
  - cap scan: ~45 min
  - noise scan: ~40 min
- Any `brain.*` registry change alters `model_hash`. Then re-run the timestep gates (both sexes), `colony brain male`, M8 and the gates; the report-reading tests fail until you do.
- The `diagnostics/` scripts here are the one-off investigations behind each finding. Run them from the repo root with the venv python. Their JSON outputs sit next to them.

## Report

The private HTML report artifact is https://claude.ai/artifact/W48TGAEppJzs8yS2o8B3Nu (first gate run).
- Generator: `report/build_report.py` with `report/report_template.html`, run as `python build_report.py <repo> <out.html>`.
- To update it, republish to the same URL; only the owner's Claude session can do that.

## History

- M1–M6: world, bodies, senses, routes, motor readout, minimal physiology, ClosedLoop.
- Loop speed-up (ca5dbb3), bit-identical: 32 flies at ~0.31 fly-s/s, launch-bound on WDDM. Fused kernels / CUDA graphs belong to Phase 9 (`tools/profile_loop.py`).
- M7 (b47140c): open-loop DN harness; 8/8 groups at 8× threshold (MDN needs ≥ 4×, GF 8×).
- M9 (7f29720): `engine/gates.py`, `engine/stats.py`, `config/motor/gates.yaml`, `colony gates run`.
- First gate run, 2026-10-21 (394a3c2), on the model before these fixes:
  - AC-07 PASS.
  - AC-01 FAIL 4/50 vs 1/50.
  - AC-02 FAIL 2/50 vs 2/50.
  - AC-04 FAIL 0/50 vs 0/50.
  - AC-05 FAIL.
- Root-cause chain since then:
  1. Noise held the brain in an ignited state.
  2. Ignition traced to the AL eLN→PN edges (fix 2).
  3. Noise recalibrated (fix 3).
  4. M8 showed MN9 latched at ~100 Hz through CB0216 L↔R.
  5. Global depression failed validation (fix 5).
  6. Synapse cap applied (fix 4).
  7. Second gate run.
