"""T-CONN-U-006 (peptidergic lists, CONN-R-015) and the extended I/O map selector (CONN-R-020)."""

from __future__ import annotations

import polars as pl
import pytest

from flycolony.connectome.iomap import IoMap, resolve_iomap
from flycolony.connectome.peptides import (
    UnknownTokenError,
    by_type,
    fafb_peptides,
    load_vocab,
    male_peptides,
)


@pytest.fixture(scope="module")
def vocab():
    return load_vocab()


def ann(rows):
    return pl.DataFrame(
        rows,
        schema={
            "source_id": pl.Int64,
            "cell_type": pl.String,
            "known_nt": pl.String,
            "known_nt_source": pl.String,
        },
        orient="row",
    )


def test_vocab_aliases_are_unique(vocab):
    aliases = vocab.alias_map()
    assert aliases["dNPF"] == aliases["NPF"] == "NPF"
    assert aliases["tachykinin"] == "Tk"
    assert {"NPF", "sNPF", "Tk", "DH44", "ILP", "Crz"} <= set(vocab.peptides)  # named in 002
    assert set(vocab.not_in_brain) == {"AKH", "SP"}


def test_fafb_rows_carry_their_citation(vocab):
    rows = fafb_peptides(
        ann(
            [
                (1, "X", "acetylcholine; sNPF; acetylcholine, sNPF", "Johard 2008 (immuno)"),
                (2, "Y", "gaba-negative, tachykinin", None),
                (3, "IPC", None, None),
                (4, "Z", "glutamate", "src"),
            ]
        ),
        vocab,
    )
    got = {(r[0], r[1]) for r in rows.select("source_id", "substance").iter_rows()}
    assert got == {(1, "sNPF"), (2, "Tk"), (3, "ILP")}
    refs = dict(rows.select("source_id", "source_ref").iter_rows())
    assert refs[1] == "Johard 2008 (immuno)"
    assert "known_nt" in refs[2]  # fallback names the annotation column
    assert "Schlegel" in refs[3]  # endocrine type named by its peptide


def test_unknown_token_fails_loudly(vocab):
    with pytest.raises(UnknownTokenError, match="mysteryamide"):
        fafb_peptides(ann([(1, "X", "mysteryamide", "src")]), vocab)


def test_male_inherits_via_type_match_and_is_marked(vocab):
    a = ann([(1, "LNd_a", "sNPF", "Ref A"), (2, "PDFn", "pdf", "Ref B")])
    female = fafb_peptides(a, vocab)
    male = pl.DataFrame({"source_id": [10, 11, 12], "flywire_type": ["LNd_a", "PDFn/LNd_a", None]})
    rows = male_peptides(male, by_type(female, a))
    got = sorted(rows.select("source_id", "substance").iter_rows())
    assert got == [(10, "sNPF"), (11, "PDF"), (11, "sNPF")]
    assert rows["source_ref"].str.contains("inferred for MaleCNS").all()


def test_sub_class_selector_and_exclusion(synth, registry, tmp_path):
    neurons = pl.DataFrame(
        {
            "neuron_id": [0, 1, 2, 3],
            "cell_type": ["R7", "R7", "R8", "R8"],
            "cell_sub_class": [None, "DRA", None, "DRA"],
            "side": ["L", "L", "R", "R"],
            "is_sensory": [True] * 4,
            "is_descending": [False] * 4,
            "is_motor": [False] * 4,
        }
    )
    m = IoMap.model_validate(
        {
            "version": "t",
            "entries": [
                {
                    "name": "vision.r7",
                    "kind": "sense",
                    "citation": "test",
                    "select": {"cell_type": ["R7"], "exclude_cell_sub_class": ["DRA"]},
                },
                {
                    "name": "vision.dra",
                    "kind": "sense",
                    "citation": "test",
                    "select": {"cell_sub_class": ["DRA"]},
                },
            ],
        }
    )
    r = {e["name"]: e["neuron_ids"] for e in resolve_iomap(m, neurons)["entries"]}
    assert r == {"vision.r7": [0], "vision.dra": [1, 3]}


def test_overlaps_are_counted():
    neurons = pl.DataFrame(
        {
            "neuron_id": [0, 1],
            "cell_type": ["A", "A"],
            "cell_sub_class": [None, None],
            "side": ["L", "R"],
            "is_sensory": [True, True],
            "is_descending": [False, False],
            "is_motor": [False, False],
        }
    )
    m = IoMap.model_validate(
        {
            "version": "t",
            "entries": [
                {
                    "name": "a.one",
                    "kind": "sense",
                    "citation": "test",
                    "select": {"cell_type": ["A"]},
                },
                {
                    "name": "a.two",
                    "kind": "sense",
                    "citation": "test",
                    "select": {"cell_type": ["A"]},
                },
            ],
        }
    )
    assert resolve_iomap(m, neurons)["coverage"]["overlaps"]["sense"] == 2
