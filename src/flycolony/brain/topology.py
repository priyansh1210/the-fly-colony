"""Shared connectivity: one copy per template and device, used by every fly of that sex (BRAIN-R-002).

Edges stay in the template's CSR order (pre-major). Weights are stored in mV per spike
(signed synapse count x w_per_synapse), fp32 by default. fp16 is allowed only when the timestep
gate passed with fp16 weights (BRAIN-R-052); the engine checks that, not this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl
import torch

from flycolony.connectome.template import BrainTemplate

WEIGHT_DTYPES = {"fp32": torch.float32, "fp16": torch.float16}


@dataclass
class Topology:
    template_id: str
    n: int
    device: torch.device
    indptr: torch.Tensor  # int64 [n+1]
    indices: torch.Tensor  # int64 [E] post neuron of each edge
    weight: torch.Tensor  # fp32/fp16 [E], mV per presynaptic spike
    spiking: torch.Tensor  # bool [n]
    sensory: torch.Tensor  # bool [n]
    neurons: pl.DataFrame = field(repr=False)
    graded_edges: torch.Tensor | None = None  # int64 [Eg] CSR edge ids whose pre is graded
    graded_pre: torch.Tensor | None = None  # int64 [Eg] pre neuron of those edges
    graded_tau: np.ndarray | None = field(default=None, repr=False)  # float64 [n] ms, NaN = default

    @property
    def n_edges(self) -> int:
        return int(self.indices.numel())

    def nbytes(self) -> int:
        ts = [self.indptr, self.indices, self.weight, self.spiking, self.sensory]
        ts += [t for t in (self.graded_edges, self.graded_pre) if t is not None]
        return sum(t.numel() * t.element_size() for t in ts)


def build_topology(
    template: BrainTemplate,
    device: torch.device,
    *,
    w_per_synapse: float,
    graded: bool,
    weight_dtype: str = "fp32",
    weight_scale: float | np.ndarray = 1.0,
    extra_graded: tuple[str, ...] = (),
    graded_tau_ms: dict[str, float] | None = None,
) -> Topology:
    """Move a template's connectivity to `device`.

    `graded=False` simulates every neuron as LIF (the Shiu et al. reference variant).
    `graded_tau_ms` gives membrane time constants per graded cell type (flyvis); other graded
    units use the registry default.
    `extra_graded` lists central-brain types simulated as graded units (BRAIN-OQ-02).
    `weight_scale` is the cross-dataset normalization (CONN-R-031): 1 for FAFB; for MaleCNS a
    scalar or one factor per postsynaptic neuron (see build.weight_scale).
    """
    if weight_dtype not in WEIGHT_DTYPES:
        raise ValueError(f"weight dtype {weight_dtype!r}; use one of {sorted(WEIGHT_DTYPES)}")
    e = template.edges
    neurons = template.neurons
    n = neurons.height
    scale = np.asarray(weight_scale, dtype=np.float64)
    if scale.ndim:
        scale = scale[np.asarray(e["indices"])]  # per postsynaptic neuron
    weight = (np.asarray(e["weight"], dtype=np.float64) * (w_per_synapse * scale)).astype(
        np.float32
    )
    if graded:
        is_graded = (neurons["model"] == "graded").to_numpy()
        is_graded |= neurons["cell_type"].is_in(list(extra_graded)).fill_null(False).to_numpy()
    else:
        is_graded = np.zeros(n, dtype=bool)
    indptr = torch.from_numpy(np.asarray(e["indptr"], dtype=np.int64))
    topo = Topology(
        template_id=template.template_id,
        n=n,
        device=device,
        indptr=indptr.to(device),
        indices=torch.from_numpy(np.asarray(e["indices"]).astype(np.int64)).to(device),
        weight=torch.from_numpy(weight).to(device=device, dtype=WEIGHT_DTYPES[weight_dtype]),
        spiking=torch.from_numpy(~is_graded).to(device),
        sensory=torch.from_numpy(neurons["is_sensory"].to_numpy().astype(bool)).to(device),
        neurons=neurons,
    )
    if is_graded.any() and graded_tau_ms:
        tau = neurons["cell_type"].replace_strict(
            graded_tau_ms, default=None, return_dtype=pl.Float64
        )
        topo.graded_tau = np.where(is_graded, tau.fill_null(np.nan).to_numpy(), np.nan)
    if is_graded.any():
        deg = np.diff(np.asarray(e["indptr"], dtype=np.int64))
        pre_of_edge = np.repeat(np.arange(n, dtype=np.int64), deg)
        g_edges = np.flatnonzero(is_graded[pre_of_edge])
        topo.graded_edges = torch.from_numpy(g_edges).to(device)
        topo.graded_pre = torch.from_numpy(pre_of_edge[g_edges]).to(device)
    return topo


def expand_rows(indptr: torch.Tensor, rows: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Edge ids of the given CSR rows, and for each edge the position of its row in `rows`.

    Cost is proportional to the number of returned edges (event-driven propagation, BRAIN-R-051).
    """
    start = indptr[rows]
    deg = indptr[rows + 1] - start
    total = int(deg.sum())
    which = torch.repeat_interleave(
        torch.arange(rows.numel(), device=rows.device), deg, output_size=total
    )
    first = torch.cumsum(deg, 0) - deg
    edge = start[which] + torch.arange(total, device=rows.device) - first[which]
    return edge, which
