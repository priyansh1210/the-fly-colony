"""Neuron selections shared by assays, the receptor table and interoceptive routes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from flycolony.config import project_root
from flycolony.connectome.template import BrainTemplate


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Select(_Strict):
    """Exactly one of: a Shiu et al. list, an I/O map channel, cell types, or a cell-type regex."""

    shiu_list: str | None = None
    channel: str | None = None
    cell_types: list[str] | None = None
    cell_type_regex: str | None = None
    side: str | None = None

    @model_validator(mode="after")
    def _one(self) -> Select:
        kinds = (self.shiu_list, self.channel, self.cell_types, self.cell_type_regex)
        if sum(x is not None for x in kinds) != 1:
            raise ValueError(
                "select exactly one of shiu_list, channel, cell_types, cell_type_regex"
            )
        return self

    @property
    def name(self) -> str:
        if self.cell_types is not None:
            return ",".join(self.cell_types)
        return self.shiu_list or self.channel or self.cell_type_regex or ""


def shiu_lists(path: Path | None = None) -> dict[str, list[int]]:
    path = path or project_root() / "config" / "brain" / "shiu2024_neurons.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {k: [int(i) for i in v["ids"]] for k, v in raw["lists"].items()}


def iomap_channels(template: BrainTemplate) -> dict[str, list[int]]:
    io = json.loads((template.path / "iomap.json").read_text(encoding="utf-8"))
    return {e["name"]: e["neuron_ids"] for e in io["entries"]}


@dataclass
class Resolved:
    name: str
    neuron_ids: np.ndarray
    rate_hz: float = 0.0
    missing_source_ids: tuple[int, ...] = ()


def resolve_select(sel: Select, template: BrainTemplate, *, allow_empty: bool = False) -> Resolved:
    n = template.neurons
    missing: tuple[int, ...] = ()
    if sel.shiu_list is not None:
        wanted = shiu_lists()[sel.shiu_list]
        hit = n.filter(pl.col("source_id").is_in(wanted))
        missing = tuple(sorted(set(wanted) - set(hit["source_id"].to_list())))
    elif sel.channel is not None:
        hit = n.filter(pl.col("neuron_id").is_in(iomap_channels(template).get(sel.channel, [])))
    elif sel.cell_types is not None:
        hit = n.filter(pl.col("cell_type").is_in(sel.cell_types))
    else:
        hit = n.filter(pl.col("cell_type").str.contains(sel.cell_type_regex))
    if sel.side is not None:
        hit = hit.filter(pl.col("side") == sel.side)
    ids = np.sort(hit["neuron_id"].to_numpy().astype(np.int64))
    if ids.size == 0 and not allow_empty:
        raise ValueError(f"selection {sel.name!r} matches no neuron in {template.template_id}")
    return Resolved(sel.name, ids, missing_source_ids=missing)
