"""SensoryLayout: which template neurons each sense channel drives (004 §2, SENSE-R-002).

Built once per template from the I/O map and `config/senses/channels.yaml`. Poisson-driven
neurons are laid out channel by channel in one index space (`sensory_ids`), so a senses step writes
one dense rate tensor [B, n_sensory]. Photoreceptors are a second index space (`photo_ids`) with
their spectral class and eye side.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from flycolony.config import project_root
from flycolony.connectome.template import BrainTemplate

SIDES = ("L", "R")


@dataclass
class Channel:
    """One channel's slice of the sensory index space."""

    name: str
    sense: str  # taste | smell | mechano | thermo
    group: str
    start: int
    stop: int
    side: np.ndarray  # 0 = L, 1 = R, per neuron in the slice
    cell_type: list[str]
    spec: dict = field(default_factory=dict)

    @property
    def size(self) -> int:
        return self.stop - self.start


@dataclass
class SensoryLayout:
    template_id: str
    sensory_ids: np.ndarray
    channels: dict[str, Channel]
    photo_ids: np.ndarray
    photo_class: np.ndarray  # index into PHOTO_CLASSES
    photo_side: np.ndarray  # 0 = L, 1 = R
    photo_classes: list[str]
    unmapped_groups: list[str]

    @property
    def n_sensory(self) -> int:
        return int(self.sensory_ids.size)

    @property
    def n_photo(self) -> int:
        return int(self.photo_ids.size)


def load_channels(path: Path | None = None) -> dict:
    path = path or project_root() / "config" / "senses" / "channels.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def build_layout(template: BrainTemplate, channels: dict | None = None) -> SensoryLayout:
    channels = channels or load_channels()
    io = json.loads((template.path / "iomap.json").read_text(encoding="utf-8"))["entries"]
    groups = {e["name"]: np.asarray(e["neuron_ids"], dtype=np.int64) for e in io}
    neurons = template.neurons.select("neuron_id", "side", "cell_type").sort("neuron_id")
    side_of = np.array([1 if s == "R" else 0 for s in neurons["side"].fill_null("L")])
    type_of = neurons["cell_type"].fill_null("").to_list()

    specs: list[tuple[str, str, dict]] = []  # (sense, group, spec)
    for sense in ("taste", "mechano", "thermo"):
        for c in channels.get(sense, []):
            specs.append((sense, c["group"], c))
    sm = channels["smell"]
    for name in sorted(g for g in groups if g.startswith(sm["prefix"])):
        glom = name[len(sm["prefix"]) :]
        specs.append(
            (
                "smell",
                name,
                {
                    "channel": f"orn.{glom}",
                    "glomerulus": glom,
                    "palp": glom in sm["palp_glomeruli"],
                    "params": sm["params"],
                },
            )
        )

    ids, chans, used = [], {}, set()
    unmapped = []
    pos = 0
    for sense, group, spec in specs:
        if group not in groups:
            unmapped.append(group)
            continue
        g = np.array([i for i in groups[group] if i not in used], dtype=np.int64)
        used.update(g.tolist())
        name = spec["channel"]
        chans[name] = Channel(
            name=name,
            sense=sense,
            group=group,
            start=pos,
            stop=pos + g.size,
            side=side_of[g],
            cell_type=[type_of[i] for i in g],
            spec=spec,
        )
        ids.append(g)
        pos += g.size

    # Photoreceptors: dorsal-rim first so DRA R7/R8 are classed as dorsal rim, not R7/R8.
    vis = channels["vision"]["photoreceptors"]
    order = sorted(vis, key=lambda v: v["class"] != "dorsal_rim")
    classes = [v["class"] for v in vis]
    p_ids, p_cls = [], []
    seen: set[int] = set()
    for v in order:
        if v["group"] not in groups:
            unmapped.append(v["group"])
            continue
        g = [i for i in groups[v["group"]] if i not in seen]
        seen.update(g)
        p_ids += g
        p_cls += [classes.index(v["class"])] * len(g)
    photo = np.asarray(p_ids, dtype=np.int64)
    if set(photo.tolist()) & used:
        raise ValueError("a neuron is both a photoreceptor and a Poisson-driven sensory neuron")
    return SensoryLayout(
        template_id=template.template_id,
        sensory_ids=np.concatenate(ids) if ids else np.zeros(0, dtype=np.int64),
        channels=chans,
        photo_ids=photo,
        photo_class=np.asarray(p_cls, dtype=np.int64),
        photo_side=side_of[photo] if photo.size else np.zeros(0, dtype=np.int64),
        photo_classes=classes,
        unmapped_groups=unmapped,
    )


def describe(layout: SensoryLayout) -> pl.DataFrame:
    """One row per channel: sense, group, neurons, left, right (for reports)."""
    rows = [
        (c.name, c.sense, c.group, c.size, int((c.side == 0).sum()), int((c.side == 1).sum()))
        for c in layout.channels.values()
    ]
    return pl.DataFrame(
        rows, schema=["channel", "sense", "group", "n", "left", "right"], orient="row"
    )
