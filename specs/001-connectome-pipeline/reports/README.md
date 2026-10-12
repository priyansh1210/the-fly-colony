# 001 build reports

Manifests and build reports of the Phase-0 artifacts, built on the dev PC (Windows 11, RTX 4000 SFF Ada, 64 GB). The artifacts live under `data/templates/` (not committed) and can be rebuilt with `colony data fetch` + `colony template build female|male` + `colony template match`. Rebuilds are byte-identical (CONN-AC-04).

## Current: t2 (commit `fc3858a7ea42`)

t2 = t1 plus cited peptidergic neurons (D8), the full I/O map (D7) and a `cell_sub_class` column. Edges are identical to t1, so the matching is unchanged.

| Artifact | Neurons | Edges | Synapses | Peptidergic neurons | Sensory / MN / DN mapped | Peak RAM |
|---|---|---|---|---|---|---|
| `female-fafb783-t2` | 139,255 | 15,091,983 | 54,492,922 | 7,651 (31 peptides) | 91% / 96% / 2% | 3.442 GiB |
| `male-malecns1-t2` | 144,428 | 21,872,410 | 101,094,177 | 8,979 (31 peptides, inferred) | 88% / 99% / 2% | 4.887 GiB |
| `match__female-fafb783-t2__male-malecns1-t2` | — | — | — | — | — | — |

The matching maps 7,362 of 8,638 male types, with scale 0.552 and 883 discrepancies.

## Superseded: t1 (commit `6bc8c0868fa1`)

The `*-t1.*` files record the first Phase-0 templates (no peptides, seed I/O map). They are kept because templates are immutable and versions are never reused (CONN-R-054).
