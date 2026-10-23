"""Brain parameters from the registry and their discretisation for a timestep (BRAIN-R-010..013, -020).

All biological values come from `config/params/brain.yaml`. This module only turns them into the
per-step constants the engine uses, the same way Brian2 does for the reference model:

- exact ("linear") integration of the LIF membrane and the exponential synapse;
- refractory periods as whole steps: ``int(t_ref / dt + 1e-3)`` (Brian2 ``timestep()``);
- delays rounded to the nearest step (Brian2 ``SpikeQueue``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from flycolony.registry import Registry

# Brian2 treats a time as step k when it is within 1e-3 steps of k*dt (brian2.core.functions.timestep).
_BRIAN2_STEP_TOLERANCE = 1e-3  # registry-ok: numerical tolerance of the reference simulator

REGISTRY_IDS = (
    "brain.lif.v_rest",
    "brain.lif.v_reset",
    "brain.lif.v_thresh",
    "brain.lif.tau_m",
    "brain.lif.t_ref",
    "brain.syn.tau",
    "brain.syn.delay",
    "brain.syn.w_per_synapse",
    "brain.syn.depression.keep",
    "brain.syn.depression.tau_rec",
    "brain.input.w_poisson",
    "brain.input.driven_t_ref",
    "brain.noise.rate",
    "brain.noise.w",
    "brain.dt.reference",
    "brain.num.fixed_point_bits",
    "brain.num.event_block_steps",
    "brain.out.rate_tau",
    "brain.graded.tau",
    "brain.graded.v_thresh",
    "brain.graded.gain",
    "brain.graded.max_rate",
    "brain.graded.extra_cell_types",
    "brain.graded.update_interval",
    "brain.trace.amine.tau_rise",
    "brain.trace.amine.tau_decay",
    "brain.trace.peptide.tau_rise",
    "brain.trace.peptide.tau_decay",
    "brain.trace.unit_rate",
    "brain.trace.update_interval",
    "brain.trace.max_gain_change",
    "brain.safety.max_population_rate",
    "brain.safety.window",
)

MS_PER_S = 1000.0  # registry-ok: unit conversion


@dataclass(frozen=True)
class NeuronParams:
    """Registry values in their native units (mV, ms, Hz)."""

    v_rest: float
    v_reset: float
    v_thresh: float
    tau_m: float
    t_ref: float
    tau_syn: float
    delay: float
    w_syn: float
    w_poisson: float
    driven_t_ref: float
    noise_rate: float
    noise_w: float
    dt_reference: float
    fixed_point_bits: int
    event_block_steps: int
    out_rate_tau: float
    graded_tau: float
    graded_v_thresh: float
    graded_gain: float
    graded_max_rate: float
    graded_extra_types: tuple[str, ...]
    graded_update_interval: float
    amine_tau_rise: float
    amine_tau_decay: float
    peptide_tau_rise: float
    peptide_tau_decay: float
    trace_unit_rate: float
    trace_update_interval: float
    max_gain_change: float
    max_population_rate: float
    safety_window: float
    depression_keep: float
    depression_tau_rec: float

    @classmethod
    def from_registry(cls, reg: Registry, *, reference: bool = False) -> NeuronParams:
        """Read every brain parameter. `reference=True` switches off background noise, as in the
        Shiu et al. model, where only stimulated neurons receive input, and short-term synaptic
        depression, which that model does not have."""
        reg.require(list(REGISTRY_IDS))
        g = reg.get
        return cls(
            v_rest=float(g("brain.lif.v_rest")),
            v_reset=float(g("brain.lif.v_reset")),
            v_thresh=float(g("brain.lif.v_thresh")),
            tau_m=float(g("brain.lif.tau_m")),
            t_ref=float(g("brain.lif.t_ref")),
            tau_syn=float(g("brain.syn.tau")),
            delay=float(g("brain.syn.delay")),
            w_syn=float(g("brain.syn.w_per_synapse")),
            w_poisson=float(g("brain.input.w_poisson")),
            driven_t_ref=float(g("brain.input.driven_t_ref")),
            noise_rate=0.0 if reference else float(g("brain.noise.rate")),
            noise_w=float(g("brain.noise.w")),
            dt_reference=float(g("brain.dt.reference")),
            fixed_point_bits=int(g("brain.num.fixed_point_bits")),
            event_block_steps=int(g("brain.num.event_block_steps")),
            out_rate_tau=float(g("brain.out.rate_tau")),
            graded_tau=float(g("brain.graded.tau")),
            graded_v_thresh=float(g("brain.graded.v_thresh")),
            graded_gain=float(g("brain.graded.gain")),
            graded_max_rate=float(g("brain.graded.max_rate")),
            graded_extra_types=tuple(g("brain.graded.extra_cell_types")),
            graded_update_interval=float(g("brain.graded.update_interval")),
            amine_tau_rise=float(g("brain.trace.amine.tau_rise")),
            amine_tau_decay=float(g("brain.trace.amine.tau_decay")),
            peptide_tau_rise=float(g("brain.trace.peptide.tau_rise")),
            peptide_tau_decay=float(g("brain.trace.peptide.tau_decay")),
            trace_unit_rate=float(g("brain.trace.unit_rate")),
            trace_update_interval=float(g("brain.trace.update_interval")),
            max_gain_change=float(g("brain.trace.max_gain_change")),
            max_population_rate=float(g("brain.safety.max_population_rate")),
            safety_window=float(g("brain.safety.window")),
            depression_keep=1.0 if reference else float(g("brain.syn.depression.keep")),
            depression_tau_rec=float(g("brain.syn.depression.tau_rec")),
        )


def refractory_steps(t_ref: float, dt: float) -> int:
    """Whole steps a neuron stays refractory (Brian2 `timestep(refractory, dt)`)."""
    return int(t_ref / dt + _BRIAN2_STEP_TOLERANCE)


def delay_steps(delay: float, dt: float) -> int:
    """Transmission delay in steps, rounded half up like Brian2's spike queue."""
    return math.floor(delay / dt + 0.5)


def membrane_propagator(tau_m: float, tau_syn: float, dt: float) -> tuple[float, float, float]:
    """Exact one-step solution of dv/dt = (v_rest - v + g)/tau_m, dg/dt = -g/tau_syn.

    With x = v - v_rest: x' = x*e_m + g*c and g' = g*e_s. Returns (e_m, c, e_s), computed in
    float64 like Brian2's 'linear' integrator.
    """
    e_m = math.exp(-dt / tau_m)
    e_s = math.exp(-dt / tau_syn)
    if math.isclose(tau_m, tau_syn):
        c = dt / tau_m * e_m
    else:
        c = tau_syn / (tau_syn - tau_m) * (e_s - e_m)
    return e_m, c, e_s


@dataclass(frozen=True)
class StepConstants:
    """Per-step constants for one dt (all derived; nothing here is a free parameter)."""

    dt: float
    ref_steps: int
    driven_ref_steps: int
    delay_steps: int
    e_m: float
    c_m: float
    e_s: float
    p_noise: float
    rate_decay: float
    safety_steps: int
    graded_every: int
    e_graded: float
    c_graded: float

    @classmethod
    def build(cls, p: NeuronParams, dt: float) -> StepConstants:
        if dt <= 0:
            raise ValueError(f"dt must be positive, got {dt}")
        e_m, c_m, e_s = membrane_propagator(p.tau_m, p.tau_syn, dt)
        p_noise = p.noise_rate * dt / MS_PER_S
        if p_noise >= 1:
            raise ValueError(
                f"background rate {p.noise_rate} Hz is too high for dt={dt} ms (p={p_noise:.3f} per step)"
            )
        e_g, c_g, _ = membrane_propagator(p.graded_tau, p.tau_syn, dt)
        return cls(
            graded_every=max(1, round(p.graded_update_interval / dt)),
            e_graded=e_g,
            c_graded=c_g,
            dt=dt,
            ref_steps=refractory_steps(p.t_ref, dt),
            driven_ref_steps=refractory_steps(p.driven_t_ref, dt),
            delay_steps=delay_steps(p.delay, dt),
            e_m=e_m,
            c_m=c_m,
            e_s=e_s,
            p_noise=p_noise,
            rate_decay=math.exp(-dt / p.out_rate_tau),
            safety_steps=max(1, round(p.safety_window / dt)),
        )
