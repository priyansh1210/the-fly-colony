"""I/O map: sense channels, motor primitives and interoceptive routes -> neurons (spec 001 §4.3).

The map's content is owned by specs 004 (senses), 005 (motor) and 006 (interoceptive routes).
This module defines its file format, resolves it against a template, and reports coverage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from flycolony.config.loader import load_yaml, validate


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Selector(_Strict):
    """Exactly one way to pick neurons. Lists match any of their values."""

    cell_type: list[str] | None = None
    cell_class: list[str] | None = None
    source_id: list[int] | None = None
    side: list[Literal["L", "R", "C", "NA"]] | None = None  # optional extra filter

    @model_validator(mode="after")
    def _one_kind(self) -> Selector:
        kinds = [k for k in ("cell_type", "cell_class", "source_id") if getattr(self, k)]
        if len(kinds) != 1:
            raise ValueError("select needs exactly one of cell_type, cell_class or source_id")
        return self


class IoEntry(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
    kind: Literal["sense", "motor", "interoceptive"]
    select: Selector
    citation: str = Field(min_length=3)
    notes: str | None = None


class IoMap(_Strict):
    version: str
    entries: list[IoEntry] = Field(default_factory=list)


class IoMapError(ValueError):
    """The I/O map references cell types or neurons missing from the template (CONN-R-021)."""


def load_iomap(directory: Path) -> IoMap:
    """Merge every YAML file in config/iomap/<sex>/ (each with `version` and `entries`)."""
    entries: list[IoEntry] = []
    versions = []
    for path in sorted(Path(directory).glob("*.yaml")):
        data, lines = load_yaml(path)
        part = validate(IoMap, data, lines, path)
        versions.append(f"{path.stem}@{part.version}")
        entries.extend(part.entries)
    names = [e.name for e in entries]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise IoMapError(f"duplicate I/O map names: {dupes}")
    return IoMap(version="+".join(versions) or "empty", entries=entries)


def resolve_iomap(iomap: IoMap, neurons: pl.DataFrame) -> dict:
    """Resolve every entry to neuron ids. Missing references fail with a full list."""
    missing: list[str] = []
    resolved = []
    for e in iomap.entries:
        sel = e.select
        if sel.cell_type:
            col, wanted = "cell_type", sel.cell_type
        elif sel.cell_class:
            col, wanted = "cell_class", sel.cell_class
        else:
            col, wanted = "source_id", sel.source_id
        present = set(neurons.filter(pl.col(col).is_in(wanted))[col].unique().to_list())
        for value in wanted:
            if value not in present:
                missing.append(f"{e.name}: {col}={value!r} not in template")
        picked = neurons.filter(pl.col(col).is_in(wanted))
        if sel.side:
            picked = picked.filter(pl.col("side").is_in(sel.side))
        if picked.height == 0 and not any(m.startswith(f"{e.name}:") for m in missing):
            missing.append(f"{e.name}: selector matched no neurons (side filter {sel.side})")
        resolved.append(
            {
                "name": e.name,
                "kind": e.kind,
                "citation": e.citation,
                "neuron_ids": sorted(picked["neuron_id"].to_list()),
            }
        )
    if missing:
        raise IoMapError("I/O map has missing references:\n  " + "\n  ".join(missing))
    return {"version": iomap.version, "entries": resolved, "coverage": coverage(resolved, neurons)}


def coverage(resolved: list[dict], neurons: pl.DataFrame) -> dict:
    """Mapped vs unmapped shares for sensory neurons and DNs (CONN-R-022)."""
    sense_ids = {
        i for r in resolved if r["kind"] in ("sense", "interoceptive") for i in r["neuron_ids"]
    }
    motor_ids = {i for r in resolved if r["kind"] == "motor" for i in r["neuron_ids"]}
    sensory = set(neurons.filter(pl.col("is_sensory"))["neuron_id"].to_list())
    dns = set(neurons.filter(pl.col("is_descending"))["neuron_id"].to_list())

    def share(mapped: set[int], total: set[int]) -> dict:
        n = len(total & mapped)
        return {
            "total": len(total),
            "mapped": n,
            "unmapped": len(total) - n,
            "share_mapped": round(n / len(total), 4) if total else 0.0,
        }

    return {"sensory": share(sense_ids, sensory), "descending": share(motor_ids, dns)}
