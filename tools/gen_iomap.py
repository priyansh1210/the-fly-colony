"""Generate config/iomap/<sex>/*.yaml from curated, cited rules + the dataset annotations.

The I/O map content is owned by specs 004 (senses), 005 (motor) and 006 (interoceptive routes).
This tool writes the first full version from neuron identities the datasets already annotate,
so every entry is traceable: the rule below names the publication, and the selector is checked
against the real template at build time (CONN-R-021).

Usage (after `colony template build female|male` once):
    python tools/gen_iomap.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.feather as pf
import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
TEMPLATES = ROOT / "data" / "templates"
OUT = ROOT / "config" / "iomap"
VERSION = "1.0"
# Any built template of each sex works (only cell identities are read); default: colony.yaml.
sys.path.insert(0, str(ROOT / "src"))
from flycolony.config import load_all  # noqa: E402

_TEMPLATES_CFG = load_all()["colony.yaml"].templates
FEMALE_ID = sys.argv[1] if len(sys.argv) > 1 else _TEMPLATES_CFG.female
MALE_ID = sys.argv[2] if len(sys.argv) > 2 else _TEMPLATES_CFG.male
MALE_ID = sys.argv[2] if len(sys.argv) > 2 else "male-malecns1-t1"

SCHLEGEL_2024 = "Schlegel P. et al. (2024) Nature 634:139-152, doi:10.1038/s41586-024-07686-5"
MALECNS = "MaleCNS v1.0 annotations (male-cns.janelia.org)"
CITE = {
    "photo": f"Photoreceptor types: {SCHLEGEL_2024}; {MALECNS}",
    "dra": "Dorsal-rim polarization photoreceptors. Labhart T., Meyer E.P. (1999) Microsc Res Tech 47:368-379",
    "orn": "ORN types by glomerulus. Schlegel P. et al. (2021) eLife 10:e66018, doi:10.7554/eLife.66018",
    "gust": "Labellar GRN types by taste modality. Engert S. et al. (2022) eLife 11:e78110, doi:10.7554/eLife.78110",
    "jo": "Johnston's organ subgroups. Kamikouchi A. et al. (2009) Nature 458:165-171, doi:10.1038/nature07810",
    "bristle": "Head bristle mechanosensory neurons. Eichler K. et al. (2024) eLife, somatotopic grooming pathways",
    "thermo": "Thermo/hygrosensory receptor neurons. Marin E.C. et al. (2020) Curr Biol 30:3167-3182, doi:10.1016/j.cub.2020.06.028",
    "clock": "Clock neurons. Reinhard N. et al. (2024) Synaptic and peptidergic connectome of the Drosophila circadian clock, Nat Commun",
    "gf": "Giant Fiber. von Reyn C.R. et al. (2014) Nat Neurosci 17:962-970, doi:10.1038/nn.3741",
    "mdn": "Moonwalker descending neurons. Bidaye S.S. et al. (2014) Science 344:97-101, doi:10.1126/science.1249964",
    "steer": "Rayshubskiy A. et al. (2020) Neural circuit mechanisms for steering control in walking Drosophila, bioRxiv doi:10.1101/2020.04.04.024703",
    "song": "Song command neuron (male). von Philipsborn A.C. et al. (2011) Neuron 69:509-522, doi:10.1016/j.neuron.2011.01.011",
    "landing": "Landing DNs. Ache J.M. et al. (2019) State-dependent decoupling of sensory and motor circuits underlies behavioral flexibility in Drosophila, Nat Neurosci 22:1132-1139",
    "bdn2": "BDN2 (synonym in MaleCNS v1.0 annotations: 'Sapkal 2024: BDN2'); Sapkal N. et al. (2024)",
    "adn": "Antennal grooming DNs aDN1/aDN2 (synonyms in MaleCNS v1.0). Hampel S. et al. (2015) eLife 4:e08758, doi:10.7554/eLife.08758",
    "ovidn": "Oviposition DNs. Wang F. et al. (2020) Nature 579:101-105, doi:10.1038/s41586-020-2055-9",
    "mn9": "MN9, proboscis extension. Gordon M.D., Scott K. (2009) Neuron 61:373-384, doi:10.1016/j.neuron.2008.12.033; feeding readout in Shiu P.K. et al. (2024) Nature 634:210-219",
    "mn_sub": f"Motor neuron sub-classes by nerve: {SCHLEGEL_2024}",
}


def _strings(table: pa.Table) -> pa.Table:
    return pa.table(
        {
            n: (c.cast(pa.string()) if pa.types.is_dictionary(c.type) else c)
            for n, c in zip(table.column_names, table.columns, strict=True)
        }
    )


def load_female() -> pl.DataFrame:
    tpl = pl.read_parquet(
        TEMPLATES / FEMALE_ID / "neurons.parquet",
        columns=["source_id", "cell_type", "super_class", "cell_class"],
    )
    ann = pl.read_csv(
        RAW / "fafb783_annotations" / "Supplemental_file1_neuron_annotations.tsv",
        separator="\t",
        infer_schema=False,
    ).select(pl.col("root_id").cast(pl.Int64).alias("source_id"), "cell_sub_class")
    return tpl.join(ann, on="source_id", how="left")


def load_male() -> pl.DataFrame:
    tpl = pl.read_parquet(
        TEMPLATES / MALE_ID / "neurons.parquet",
        columns=["source_id", "cell_type", "super_class", "cell_class", "flywire_type"],
    )
    ann = pl.from_arrow(
        _strings(
            pf.read_table(
                RAW / "malecns_v1" / "body-annotations-male-cns-v1.0-minconf-0.5.feather",
                columns=["bodyId", "subclass"],
            )
        )
    )
    ann = ann.rename({"bodyId": "source_id", "subclass": "cell_sub_class"})
    return tpl.join(ann, on="source_id", how="left")


def types_present(n: pl.DataFrame, wanted: list[str]) -> list[str]:
    have = set(n["cell_type"].drop_nulls().to_list())
    return [t for t in wanted if t in have]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def female_type_subclass(f: pl.DataFrame, cls: str) -> dict[str, str]:
    """Female cell type -> its most common sub_class, for one cell_class."""
    rows = (
        f.filter(pl.col("cell_class") == cls)
        .drop_nulls(["cell_type", "cell_sub_class"])
        .group_by("cell_type", "cell_sub_class")
        .len()
        .sort(["cell_type", "len", "cell_sub_class"], descending=[False, True, False])
        .group_by("cell_type", maintain_order=True)
        .first()
    )
    return dict(rows.select("cell_type", "cell_sub_class").iter_rows())


def build(sex: str, n: pl.DataFrame, f: pl.DataFrame) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"senses": [], "motor": [], "interoceptive": []}

    def add(file: str, name: str, kind: str, select: dict, cite: str, notes: str | None = None):
        entry = {"name": name, "kind": kind, "select": select, "citation": CITE[cite]}
        if notes:
            entry["notes"] = notes
        out[file].append(entry)

    def by_types(file, name, kind, types, cite, notes=None):
        present = types_present(n, types)
        if present:
            add(file, name, kind, {"cell_type": present}, cite, notes)

    female = sex == "female"
    # --- vision ---------------------------------------------------------------------------
    if female:
        excl = ["DRA", "ocellar"]
        add(
            "senses",
            "vision.photoreceptor.r1_6",
            "sense",
            {"cell_type": ["R1-6"], "exclude_cell_sub_class": excl},
            "photo",
        )
        add(
            "senses",
            "vision.photoreceptor.r7",
            "sense",
            {"cell_type": ["R7"], "exclude_cell_sub_class": excl},
            "photo",
        )
        add(
            "senses",
            "vision.photoreceptor.r8",
            "sense",
            {"cell_type": ["R8"], "exclude_cell_sub_class": excl},
            "photo",
        )
        add("senses", "vision.dorsal_rim", "sense", {"cell_sub_class": ["DRA"]}, "dra")
    else:
        by_types("senses", "vision.photoreceptor.r1_6", "sense", ["R1-R6"], "photo")
        by_types(
            "senses", "vision.photoreceptor.r7", "sense", ["R7p", "R7y", "R7_unclear"], "photo"
        )
        by_types(
            "senses", "vision.photoreceptor.r8", "sense", ["R8p", "R8y", "R8_unclear"], "photo"
        )
        by_types("senses", "vision.dorsal_rim", "sense", ["R7d", "R8d"], "dra")
    # --- smell: one channel per ORN type (glomerulus) ---------------------------------------
    for t in sorted(
        n.filter(pl.col("cell_type").str.starts_with("ORN_").fill_null(False))["cell_type"]
        .unique()
        .to_list()
    ):
        add("senses", f"olfaction.orn.{slug(t[4:])}", "sense", {"cell_type": [t]}, "orn")
    # --- taste: labellar GRN types grouped by the modality FlyWire annotates ------------------
    modality = female_type_subclass(f, "gustatory")
    wanted = {
        "sugar",
        "sugar/low_salt",
        "water",
        "high_salt/heavy_metal",
        "bitter",
        "glutamate",
        "putative_aversive",
        "putative_attractive",
    }
    groups: dict[str, list[str]] = {}
    for t, m in modality.items():
        if m in wanted:
            groups.setdefault(m, []).append(t)
    for m, types in sorted(groups.items()):
        by_types(
            "senses",
            f"taste.labellar.{slug(m)}",
            "sense",
            sorted(types),
            "gust",
            None if female else "Modality from the FlyWire type of the same name",
        )
    # --- mechanosensation -----------------------------------------------------------------
    for sub, name in (
        ("auditory", "mechano.jo.auditory"),
        ("wind_gravity", "mechano.jo.wind_gravity"),
    ):
        if n.filter(pl.col("cell_sub_class") == sub).height:
            add("senses", name, "sense", {"cell_sub_class": [sub]}, "jo")
    bm = sorted(
        n.filter(pl.col("cell_type").str.starts_with("BM_").fill_null(False))["cell_type"]
        .unique()
        .to_list()
    )
    if bm:
        add("senses", "touch.head_bristle", "sense", {"cell_type": bm}, "bristle")
    # --- temperature and humidity -----------------------------------------------------------
    for cls, prefix in (("thermosensory", "thermo"), ("hygrosensory", "hygro")):
        sub = female_type_subclass(f, cls)
        grouped: dict[str, list[str]] = {}
        for t, s in sub.items():
            grouped.setdefault(s, []).append(t)
        for s, types in sorted(grouped.items()):
            by_types("senses", f"{prefix}.{slug(s)}", "sense", sorted(types), "thermo")
    # --- interoceptive: circadian clock neurons (route: clock-neuron excitability, 006) ----
    clock = {
        "clock.s_lnv": r"^s-LNv",
        "clock.l_lnv": r"^l-LNv$",
        "clock.lnd": r"^LNd",
        "clock.dn1a": r"^DN1a$",
        "clock.dn1p": r"^DN1p",
        "clock.lpn": r"^LPN",
    }
    for name, pat in clock.items():
        types = sorted(
            n.filter(pl.col("cell_type").str.contains(pat).fill_null(False))["cell_type"]
            .unique()
            .to_list()
        )
        if types:
            add("interoceptive", name, "interoceptive", {"cell_type": types}, "clock")
    # --- motor: descending neurons --------------------------------------------------------
    by_types("motor", "escape.takeoff", "motor", ["DNp01"], "gf")
    by_types("motor", "walk.backward", "motor", ["MDN"], "mdn")
    by_types("motor", "walk.steer", "motor", ["DNa01", "DNa02"], "steer")
    by_types(
        "motor",
        "walk.forward",
        "motor",
        ["DNg100"],
        "bdn2",
        "Function from the BDN2 literature name; to be confirmed in the 005 design",
    )
    by_types("motor", "flight.landing", "motor", ["DNp07", "DNp10"], "landing")
    by_types("motor", "groom.antenna", "motor", ["DNg62", "DNge078"], "adn")
    by_types("motor", "wing.song", "motor", ["pIP10"], "song")
    by_types("motor", "oviposition", "motor", ["oviDNa_a", "oviDNa_b", "oviDNb"], "ovidn")
    # --- motor: brain motor neurons, grouped by FlyWire sub-class (male via type match) ----
    mn9 = "CB0701" if female else "MN9"
    by_types(
        "motor",
        "feeding.proboscis_extension",
        "motor",
        [mn9],
        "mn9",
        "FlyWire files this neuron under ingestion_motor_neuron; the literature name MN9 is used",
    )
    fsub = female_type_subclass(f, "brain_motor_neuron") | female_type_subclass(
        f, "neck_motor_neuron"
    )
    mn_groups = {
        "proboscis_motor_neuron": "mouth.proboscis_muscles",
        "ingestion_motor_neuron": "feeding.ingestion",
        "crop_motor_neuron": "feeding.crop",
        "salivary_motor_neuron": "feeding.salivary",
        "haustellum_motor_neuron": "mouth.haustellum",
        "neck_motor_neuron": "head.neck",
        "antennal_motor_neuron": "antenna.motor",
        "eye_motor_neuron": "eye.motor",
    }
    motor_types = n.filter(pl.col("super_class") == "motor")
    picked: dict[str, list[str]] = {}
    for row in (
        motor_types.select("cell_type", *([] if female else ["flywire_type"])).unique().iter_rows()
    ):
        t = row[0]
        if t is None or t == mn9:
            continue
        keys = [t] if female else re.split(r"[,/]", row[1] or "")
        subs = {fsub.get(k.strip()) for k in keys} - {None}
        if len(subs) == 1:
            picked.setdefault(subs.pop(), []).append(t)
    for sub, name in mn_groups.items():
        if picked.get(sub):
            add(
                "motor",
                name,
                "motor",
                {"cell_type": sorted(picked[sub])},
                "mn_sub",
                None if female else "Male types assigned via their flywireType",
            )
    return out


def write(sex: str, files: dict[str, list[dict]]) -> None:
    d = OUT / sex
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.yaml"):
        old.unlink()
    for file, entries in files.items():
        header = (
            f"# GENERATED by tools/gen_iomap.py from the {sex} template and dataset annotations.\n"
            "# Edit the rules in the tool, not this file. Owners: 004 senses, 005 motor, "
            "006 interoceptive.\n"
        )
        body = yaml.safe_dump(
            {"version": VERSION, "entries": entries}, sort_keys=False, allow_unicode=True, width=100
        )
        (d / f"{file}.yaml").write_text(header + body, encoding="utf-8", newline="\n")
        print(f"{sex}/{file}.yaml: {len(entries)} entries")


def main() -> int:
    f = load_female()
    write("female", build("female", f, f))
    write("male", build("male", load_male(), f))
    return 0


if __name__ == "__main__":
    sys.exit(main())
