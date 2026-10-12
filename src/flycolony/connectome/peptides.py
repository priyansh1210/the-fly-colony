"""Peptidergic neurons with a citation per neuron (spec 001 CONN-R-015, design §5.1 step 8)."""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
from pydantic import BaseModel, ConfigDict

from flycolony.config.loader import load_config
from flycolony.config.schemas import project_root

SCHLEGEL_2024 = (
    "Schlegel P. et al. (2024) Nature 634:139-152, doi:10.1038/s41586-024-07686-5 "
    "(FlyWire annotation: cell type named by peptide)"
)
KNOWN_NT_FALLBACK = "FlyWire annotations, known_nt (Schlegel et al. 2024)"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Peptide(_Strict):
    aliases: list[str]
    name: str


class PeptideVocab(_Strict):
    peptides: dict[str, Peptide]
    not_peptides: list[str]
    endocrine_types: dict[str, str]
    not_in_brain: dict[str, str]

    def alias_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for canonical, p in self.peptides.items():
            for alias in p.aliases:
                if alias in out:
                    raise ValueError(f"alias {alias!r} used by {out[alias]} and {canonical}")
                out[alias] = canonical
        return out


class UnknownTokenError(ValueError):
    """known_nt has a token the vocabulary does not classify (add it to peptides.yaml)."""


def load_vocab(path: Path | None = None) -> PeptideVocab:
    return load_config(PeptideVocab, path or project_root() / "config" / "params" / "peptides.yaml")


_SPLIT = re.compile(r"[;,]")


def _tokens(known_nt: str) -> list[str]:
    return [t.strip() for t in _SPLIT.split(known_nt) if t.strip()]


def fafb_peptides(annotations: pl.DataFrame, vocab: PeptideVocab) -> pl.DataFrame:
    """Per-neuron peptide rows from FlyWire annotations.

    `annotations` needs: source_id, cell_type, known_nt, known_nt_source.
    Returns source_id, substance, source_ref.
    """
    aliases = vocab.alias_map()
    ignore = set(vocab.not_peptides)
    rows: dict[tuple[int, str, str], None] = {}
    unknown: set[str] = set()
    for sid, known, source in annotations.select(
        "source_id", "known_nt", "known_nt_source"
    ).iter_rows():
        if not known:
            continue
        for tok in _tokens(known):
            if tok.endswith("-negative") or tok in ignore:
                continue
            if tok not in aliases:
                unknown.add(tok)
                continue
            rows[(sid, aliases[tok], source or KNOWN_NT_FALLBACK)] = None
    if unknown:
        raise UnknownTokenError(f"unclassified known_nt tokens: {sorted(unknown)}")
    for sid, cell_type in annotations.select("source_id", "cell_type").iter_rows():
        if cell_type in vocab.endocrine_types:
            rows[(sid, vocab.endocrine_types[cell_type], SCHLEGEL_2024)] = None
    return pl.DataFrame(
        list(rows),
        schema={"source_id": pl.Int64, "substance": pl.String, "source_ref": pl.String},
        orient="row",
    ).sort("substance", "source_id", "source_ref")


def by_type(female_rows: pl.DataFrame, annotations: pl.DataFrame) -> pl.DataFrame:
    """Female peptide assignments aggregated to cell type: cell_type, substance, source_ref."""
    return (
        female_rows.join(annotations.select("source_id", "cell_type"), on="source_id")
        .drop_nulls("cell_type")
        .group_by("cell_type", "substance")
        .agg(pl.col("source_ref").unique().sort().str.join(" | "))
        .sort("cell_type", "substance")
    )


def male_peptides(male_neurons: pl.DataFrame, female_by_type: pl.DataFrame) -> pl.DataFrame:
    """Male rows inherited through the MaleCNS->FlyWire type match (marked as inferred).

    `male_neurons` needs source_id and flywire_type ("A", "A,B" or "A/B" for multiple matches).
    """
    exploded = (
        male_neurons.select(
            "source_id",
            pl.col("flywire_type")
            .str.replace_all("/", ",", literal=True)
            .str.split(",")
            .alias("ft"),
        )
        .explode("ft")
        .with_columns(pl.col("ft").str.strip_chars())
        .drop_nulls("ft")
    )
    return (
        exploded.join(female_by_type, left_on="ft", right_on="cell_type", how="inner")
        .select(
            "source_id",
            "substance",
            (
                pl.col("source_ref")
                + pl.lit(" [inferred for MaleCNS via flywireType match to ")
                + pl.col("ft")
                + pl.lit("]")
            ).alias("source_ref"),
        )
        .unique()
        .sort("substance", "source_id", "source_ref")
    )
