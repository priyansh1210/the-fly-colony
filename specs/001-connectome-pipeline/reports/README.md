# 001 build reports

Manifests and build reports of the Phase-0 artifacts, built on the dev PC (Windows 11, RTX 4000 SFF Ada, 64 GB) from commit `6bc8c0868fa1`. The artifacts are under `data/templates/` (not committed) and are reproducible with `colony data fetch` + `colony template build female|male` + `colony template match`. Rebuilds are byte-identical (CONN-AC-04).

| Artifact | Neurons | Edges | Synapses | Peak RAM | Notes |
|---|---|---|---|---|---|
| `female-fafb783-t1` | 139,255 | 15,091,983 | 54,492,922 | 3.5 GiB | Identical to the Shiu et al. 2024 inputs, edge by edge |
| `male-malecns1-t1` | 144,428 | 21,872,410 | 101,094,177 | 4.8 GiB | Brain portion of 165,122 traced bodies |
| `match__female-fafb783-t1__male-malecns1-t1` | — | — | — | — | 7,362/8,638 male types matched; scale 0.552; 883 discrepancies |
