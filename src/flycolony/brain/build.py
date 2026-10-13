"""Assemble a brain engine for a template from config + registry (BRAIN-R-001, -002)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl
import torch
import yaml

from flycolony.brain.engine import BrainBatch, PlasticSet
from flycolony.brain.gate import DtChoice, resolve_dt
from flycolony.brain.modulation import Modulation, load_receptors, load_routes
from flycolony.brain.params import NeuronParams
from flycolony.brain.schedule import Schedule
from flycolony.brain.select import Select, resolve_select
from flycolony.brain.topology import Topology, build_topology
from flycolony.config import project_root
from flycolony.config.schemas import ColonyConfig
from flycolony.connectome.template import BrainTemplate
from flycolony.registry import Registry

_TOPOLOGY_CACHE: dict[tuple, Topology] = {}


@dataclass
class BrainSetup:
    template: BrainTemplate
    topo: Topology
    params: NeuronParams
    choice: DtChoice
    schedule: Schedule
    plastic_sets: list[PlasticSet] = field(default_factory=list)
    output_groups: dict[str, np.ndarray] = field(default_factory=dict)
    modulated: bool = True

    @property
    def dt(self) -> float:
        return self.choice.dt

    def new_batch(self) -> BrainBatch:
        batch = BrainBatch(
            self.topo,
            self.params,
            self.dt,
            plastic_sets=self.plastic_sets,
            output_groups=self.output_groups,
        )
        if self.modulated:
            Modulation(self.template, load_receptors(), load_routes()).attach(batch)
        return batch


def flyvis_time_constants() -> dict[str, float]:
    """Graded-unit membrane time constants per cell type (BRAIN-R-014; generated from flyvis)."""
    path = project_root() / "config" / "brain" / "flyvis_time_constants.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {k: float(v["tau_ms"]) for k, v in raw["cell_types"].items()}


def weight_scale(template: BrainTemplate, reg: Registry) -> float | np.ndarray:
    """Cross-dataset weight normalization (CONN-R-031), applied to MaleCNS weights only.

    `conn.norm.male_mode` = "global": one factor, conn.norm.male_scale. "per_type": each male
    neuron's input weights are scaled by its type's female/male mean input-synapse ratio from the
    match table (clipped to conn.norm.male_type_clip x the global factor); unmatched types use the
    global factor. Returns a scalar or one factor per (postsynaptic) neuron.
    """
    if template.manifest.get("sex") != "male":
        return 1.0
    g = float(reg.get("conn.norm.male_scale"))
    mode = reg.get("conn.norm.male_mode")
    if mode == "global":
        return g
    if mode != "per_type":
        raise ValueError(f"conn.norm.male_mode {mode!r}; use 'global' or 'per_type'")
    matches = sorted(template.path.parent.glob(f"match__*__{template.template_id}"))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"per_type normalization needs exactly one match table for {template.template_id}; "
            f"found {[m.name for m in matches]} (run `colony template match`)"
        )
    clip = float(reg.get("conn.norm.male_type_clip"))
    ratio = (
        pl.read_parquet(matches[0] / "type_stats.parquet")
        .filter(pl.col("matched") & pl.col("in_ratio").is_finite() & (pl.col("in_ratio") > 0))
        .group_by("male_type")
        .agg(pl.col("in_ratio").median().clip(g / clip, g * clip).alias("s"))
    )
    per = template.neurons.select("cell_type").join(
        ratio, left_on="cell_type", right_on="male_type", how="left", maintain_order="left"
    )
    return per["s"].fill_null(g).to_numpy().astype(np.float64)


def topology(
    template: BrainTemplate,
    device: torch.device,
    reg: Registry,
    *,
    w_syn: float,
    graded: bool,
    weights: str = "fp32",
) -> Topology:
    """One shared copy per (template, device, variant) (BRAIN-R-002)."""
    scale = weight_scale(template, reg)
    extra = tuple(reg.get("brain.graded.extra_cell_types")) if graded else ()
    taus = flyvis_time_constants() if graded else {}
    scale_key = (
        scale if isinstance(scale, float) else (reg.get("conn.norm.male_mode"), scale.tobytes())
    )
    key = (template.template_id, str(device), w_syn, scale_key, graded, extra, weights)
    if key not in _TOPOLOGY_CACHE:
        _TOPOLOGY_CACHE[key] = build_topology(
            template,
            device,
            w_per_synapse=w_syn,
            graded=graded,
            weight_dtype=weights,
            weight_scale=scale,
            extra_graded=extra,
            graded_tau_ms=taus,
        )
    return _TOPOLOGY_CACHE[key]


def plastic_sets(
    template: BrainTemplate, device: torch.device, *, include_disabled: bool = False
) -> list[PlasticSet]:
    raw = yaml.safe_load(
        (project_root() / "config" / "brain" / "plastic_sets.yaml").read_text(encoding="utf-8")
    )
    e = template.edges
    indptr = np.asarray(e["indptr"], dtype=np.int64)
    pre_of_edge = np.repeat(np.arange(template.n_neurons, dtype=np.int64), np.diff(indptr))
    post_of_edge = np.asarray(e["indices"], dtype=np.int64)
    out = []
    for s in raw["sets"]:
        if not s["enabled"] and not include_disabled:
            continue
        pre = np.zeros(template.n_neurons, dtype=bool)
        post = np.zeros(template.n_neurons, dtype=bool)
        pre[resolve_select(Select(**s["pre"]), template, allow_empty=True).neuron_ids] = True
        post[resolve_select(Select(**s["post"]), template, allow_empty=True).neuron_ids] = True
        edges = np.flatnonzero(pre[pre_of_edge] & post[post_of_edge])
        out.append(PlasticSet(s["name"], torch.from_numpy(edges).to(device)))
    return out


def output_groups(
    template: BrainTemplate, split_sides: tuple[str, ...] = ()
) -> dict[str, np.ndarray]:
    """DN/motor groups from the I/O map, plus neurosecretory cells by type (BRAIN-R-017).

    Groups named in `split_sides` are published per side (`<name>.L`, `<name>.R`), as the motor
    layer needs for left/right commands (005). Descending neurons in no group are published as
    `descending.unmapped`: simulated and observed, driving nothing (MOTOR-R-004).
    """
    io = json.loads((template.path / "iomap.json").read_text(encoding="utf-8"))
    side = dict(template.neurons.select("neuron_id", "side").iter_rows())
    groups: dict[str, np.ndarray] = {}
    used: set[int] = set()
    for e in io["entries"]:
        if e["kind"] == "motor" and e["neuron_ids"]:
            ids = np.asarray(e["neuron_ids"], dtype=np.int64)
            if e["name"] in split_sides:
                for sd in ("L", "R"):
                    part = np.asarray(
                        [i for i in ids.tolist() if side.get(i) == sd], dtype=np.int64
                    )
                    if part.size:
                        groups[f"{e['name']}.{sd}"] = part
            else:
                groups[e["name"]] = ids
            used |= set(e["neuron_ids"])
    ns = template.neurons.filter(pl.col("is_neurosecretory")).select("neuron_id", "cell_type")
    for (ctype,), part in ns.group_by("cell_type", maintain_order=True):
        ids = [i for i in part["neuron_id"].to_list() if i not in used]
        if ids:
            groups[f"neurosecretory.{ctype}"] = np.asarray(sorted(ids), dtype=np.int64)
            used |= set(ids)
    dn = template.neurons.filter(pl.col("is_descending"))["neuron_id"].to_list()
    rest = sorted(i for i in dn if i not in used)
    if rest:
        groups["descending.unmapped"] = np.asarray(rest, dtype=np.int64)
    return groups


def setup_brain(
    template: BrainTemplate,
    device: torch.device,
    cfg: ColonyConfig,
    reg: Registry,
    *,
    split_sides: tuple[str, ...] = (),
) -> BrainSetup:
    """Everything needed to build brain batches for a template. `split_sides` names output
    groups published per side (the motor layer's left/right commands)."""
    bc = cfg.brain
    reference = bc.mode == "reference"
    choice = resolve_dt(bc, template.path, reg)
    params = NeuronParams.from_registry(reg, reference=reference)
    graded = bc.graded and not reference
    topo = topology(template, device, reg, w_syn=params.w_syn, graded=graded, weights=bc.weights)
    sched = Schedule.build(
        choice.dt,
        {
            "brain": choice.dt,
            "physics": cfg.schedule.physics_ms,
            "senses": cfg.schedule.senses_ms,
            "vision": cfg.schedule.vision_ms,
            "fields": cfg.schedule.fields_ms,
            "physio": cfg.schedule.physio_ms,
        },
    )
    return BrainSetup(
        template=template,
        topo=topo,
        params=params,
        choice=choice,
        schedule=sched,
        plastic_sets=[] if reference else plastic_sets(template, device),
        output_groups=output_groups(template, split_sides),
        modulated=not reference,
    )


def template_path(cfg: ColonyConfig, sex: str) -> Path:
    return project_root() / cfg.paths.templates / getattr(cfg.templates, sex)
