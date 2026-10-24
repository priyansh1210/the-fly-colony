"""Generate config/senses/door_tuning.yaml from DoOR 2.0 (SENSE-R-021, -022).

For each receptor column of the DoOR consensus response matrix that maps to one glomerulus, take
the normalised response (0..1) to each world odorant (config/params/world.yaml world.odor.species).
Ecologically special receptors whose responses are missing or not in DoOR come from their own
citations (SENSE-R-022). Missing odorant × glomerulus pairs are not listed: the transduction treats
them as 0, an ASSUMPTION recorded in the file header.

The output is derived from DoOR.data (CC BY-SA 4.0) and carries that license (data/LICENSES.md).

    python tools/gen_door_tuning.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "door_v2"
OUT = ROOT / "config" / "senses" / "door_tuning.yaml"

# World odorant -> DoOR InChIKey.
ODOR_KEYS = {
    "ethanol": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
    "acetic_acid": "QTBSBXVTEAMEQO-UHFFFAOYSA-N",
    "ethyl_acetate": "XEKOWRVHYACXOJ-UHFFFAOYSA-N",
    "co2": "CURLTUGMZLYLDI-UHFFFAOYSA-N",
    "geosmin": "JLPUXFOGCDVKGO-GRYCIOLGSA-N",
    "cva": "QSZKEDWVAOAFQY-HJWRWDBZSA-N",
    "acetoin": "ROWKJAVDOGWPAT-UHFFFAOYSA-N",
    "phenylethanol": "WRMNZCZEMHIOCP-UHFFFAOYSA-N",
    "isoamyl_acetate": "MLFHJEHSLIIPHL-UHFFFAOYSA-N",
    "methyl_salicylate": "OSWPMRLSEDHDFF-UHFFFAOYSA-N",
    "benzaldehyde": "HUMNYLRZRPPJDN-UHFFFAOYSA-N",
    "ammonia": "QGZKDVFQNNGYKY-UHFFFAOYSA-N",
}

# Special receptors (SENSE-R-022): glomerulus, odorant, response, citation. These override DoOR.
SPECIAL = [
    (
        "da1",
        "cva",
        1.0,
        "Or67d: Kurtovic A. et al. (2007) Nature 446:542; Ha T.S., Smith D.P. (2006) J Neurosci 26:8727",
    ),
    ("dl3", "cva", 0.5, "Or65a: van der Goes van Naters W., Carlson J.R. (2007) Curr Biol 17:606"),
    ("da2", "geosmin", 1.0, "Or56a: Stensmyr M.C. et al. (2012) Cell 151:1345"),
    (
        "v",
        "co2",
        1.0,
        "Gr21a/Gr63a: Jones W.D. et al. (2007) Nature 445:86; Suh G.S. et al. (2004) Nature 431:854",
    ),
    ("vm1", "ammonia", 1.0, "Ir92a: Min S. et al. (2013) PNAS 110:E1321"),
    ("dc4", "acetic_acid", 1.0, "Ir64a: Ai M. et al. (2010) Nature 468:691"),
    ("dp1m", "acetic_acid", 0.5, "Ir64a: Ai M. et al. (2010) Nature 468:691"),
]


def read_r_csv(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    """R write.csv2 output: the header has no row-name column."""
    with path.open(encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter=";"))
    head = rows[0]
    return head, {r[0]: dict(zip(head, r[1:], strict=True)) for r in rows[1:]}


def _add(matrix, col: str, glom: str, species, tuning: dict, spontaneous: dict) -> None:
    sfr = matrix["SFR"].get(col, "NA")
    if sfr not in ("NA", ""):
        spontaneous[glom] = round(float(sfr), 4)
    for odor in species:
        row = matrix.get(ODOR_KEYS[odor])
        v = row.get(col, "NA") if row else "NA"
        if v in ("NA", ""):
            continue
        entry = tuning.setdefault(glom, {})
        prev = entry.get(odor)
        val = round(max(0.0, float(v)), 4)
        if prev is None or val > prev["response"]:  # several receptors per glomerulus: max
            entry[odor] = {"response": val, "source": f"DoOR 2.0 consensus, receptor {col}"}


def main() -> int:
    _, matrix = read_r_csv(RAW / "door_response_matrix.csv")
    _, mappings = read_r_csv(RAW / "door_mappings.csv")
    glom_of: dict[str, list[str]] = {}
    for m in mappings.values():
        g = m["glomerulus"].strip().lower()
        if not g or g == "?" or "+" in g:
            continue
        # "DL2d/v" names two glomeruli innervated by the same receptor neurons.
        base, _, alt = g.partition("/")
        names = [base] + ([base.rstrip("dvlmap") + alt] if alt else [])
        for key in ("receptor", "code.OSN", "OSN"):
            k = m.get(key, "").strip()
            if k and k != "?":
                glom_of.setdefault(k, names)
    world = yaml.safe_load((ROOT / "config" / "params" / "world.yaml").read_text(encoding="utf-8"))
    species = next(e["value"] for e in world["entries"] if e["id"] == "world.odor.species")
    if sorted(species) != sorted(ODOR_KEYS):
        print(f"world odorants {species} != tuning table {sorted(ODOR_KEYS)}", file=sys.stderr)
        return 1
    tuning: dict[str, dict[str, dict]] = {}
    spontaneous: dict[str, float] = {}
    for col, gloms in sorted(glom_of.items()):
        if col not in matrix.get("SFR", {}):
            continue
        for glom in gloms:
            _add(matrix, col, glom, species, tuning, spontaneous)
    for glom, odor, val, cite in SPECIAL:
        tuning.setdefault(glom, {})[odor] = {"response": val, "source": cite}
    doc = {
        "version": 1,
        "license": "CC BY-SA 4.0 (derived from DoOR.data, Münch & Galizia 2016, doi:10.1038/srep21841)",
        "generated_by": "tools/gen_door_tuning.py",
        "dataset": "door_v2 (config/datasets.yaml)",
        "assumption": "Odorant x glomerulus pairs not listed respond 0 (ASSUMPTION; DoOR has no data).",
        "spontaneous": dict(sorted(spontaneous.items())),
        "glomeruli": {g: dict(sorted(v.items())) for g, v in sorted(tuning.items())},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# GENERATED by tools/gen_door_tuning.py. Do not edit.\n")
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=100)
    print(f"wrote {OUT}: {len(tuning)} glomeruli")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
