"""Motor readout: DN/MN group rates → motor primitive commands (spec 005, MOTOR-R-001..010).

The brain chooses; this layer only executes. Each primitive's command is a saturating function of
its groups' filtered firing rates, `max · s((rate − θ) / r_half)` with s(x) = x / (1 + x) for x > 0,
delayed by a registry latency. Nothing latches except the ballistic escape jump, which one Giant
Fiber spike triggers (MOTOR-R-002). Concurrent primitives superpose; the only gating is the
biomechanical constraint table (MOTOR-R-003), applied by the body and by physiology.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import yaml

from flycolony.body.body import Commands
from flycolony.config import project_root
from flycolony.registry import Registry

COMMANDS = ("speed", "yaw", "jump", "landing", "proboscis", "pump", "groom")


def load_primitives(path: Path | None = None) -> dict:
    path = path or project_root() / "config" / "motor" / "primitives.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def split_groups(table: dict) -> tuple[str, ...]:
    """I/O-map groups the brain must publish per side (for LR primitives)."""
    return tuple(g for p in table["primitives"] if p.get("side") == "LR" for g in p["groups"])


@dataclass
class Prim:
    name: str
    command: str
    sign: float
    cols: list[int]  # brain group columns (L then R for LR primitives)
    lr: bool
    threshold: float
    half: float
    max: float
    latency: int  # physics steps
    cost: float
    trigger_spikes: int = 0


@dataclass
class MotorOutput:
    commands: Commands
    pump: torch.Tensor  # pump rate (Hz)
    groom: torch.Tensor  # antennal grooming drive in [0, 1]
    effort: torch.Tensor  # summed effort per fly (MOTOR-R-007)
    activation: dict[str, torch.Tensor]  # per-primitive command (observation, MOTOR-R-010)


class MotorBatch:
    def __init__(
        self,
        group_names: list[str],
        group_members: dict[str, np.ndarray],
        reg: Registry,
        physics_dt_ms: float,
        device: torch.device,
        table: dict | None = None,
    ):
        self.table = table or load_primitives()
        self.device = device
        g = reg.get
        self.prims: list[Prim] = []
        trig: list[int] = []
        for p in self.table["primitives"]:
            lr = p.get("side") == "LR"
            names = [f"{x}.{sd}" for x in p["groups"] for sd in ("L", "R")] if lr else p["groups"]
            missing = [n for n in names if n not in group_names]
            if missing:
                raise KeyError(f"primitive {p['name']}: brain publishes no group {missing}")
            k = p["params"]
            self.prims.append(
                Prim(
                    name=p["name"],
                    command=p["command"],
                    sign=float(p.get("sign", 1)),
                    cols=[group_names.index(n) for n in names],
                    lr=lr,
                    threshold=float(g(f"{k}.threshold_hz")),
                    half=float(g(f"{k}.half_hz")),
                    max=float(g(f"{k}.max")),
                    latency=max(0, round(float(g(f"{k}.latency_ms")) / physics_dt_ms)),
                    cost=float(g(f"{k}.effort_cost")),
                    trigger_spikes=int(p.get("trigger_spikes", 0)),
                )
            )
            if p.get("trigger_spikes"):
                for n in names:
                    trig += group_members[n].tolist()
        self.trigger_ids = torch.tensor(sorted(set(trig)), dtype=torch.int64, device=device)
        # Vectorised form of the table: group → primitive input weights (left/one side summed,
        # right side for LR primitives), per-primitive constants and the command superposition.
        f64, n_p = torch.float64, len(self.prims)
        w_in = np.zeros((len(group_names), n_p))
        w_right = np.zeros_like(w_in)
        n_cols = np.ones(n_p)
        sign = np.zeros((n_p, len(COMMANDS)))
        for i, p in enumerate(self.prims):
            if p.lr:
                w_in[p.cols[0], i] = w_right[p.cols[1], i] = 1.0
            else:
                w_in[p.cols, i] = 1.0
                n_cols[i] = len(p.cols)
            sign[i, COMMANDS.index(p.command)] = p.sign
        t = lambda v, dt=f64: torch.tensor(v, dtype=dt, device=device)  # noqa: E731
        self._w_in, self._w_right, self._n_cols = t(w_in), t(w_right), t(n_cols)
        self._sign = t(sign)
        col = lambda k: t([getattr(p, k) for p in self.prims])  # noqa: E731
        self._thr, self._half, self._max, self._cost = (
            col(k) for k in ("threshold", "half", "max", "cost")
        )
        self._lr = col("lr")
        self._trig_n = t([p.trigger_spikes for p in self.prims], torch.int64)
        self._trig = self._trig_n > 0
        self._lat = t([p.latency for p in self.prims], torch.int64)
        self._prim_ix = torch.arange(n_p, device=device)
        self.ingest_min_extension = float(g("motor.ingest.min_extension"))
        self.groom_walk_factor = float(g("motor.groom.walk_factor"))
        self.n = 0
        self._alloc(0)

    def _alloc(self, n: int) -> None:
        depth = max([p.latency for p in self.prims] + [0]) + 1
        self.history = torch.zeros(
            depth, n, len(self.prims), dtype=torch.float64, device=self.device
        )
        self.spikes = torch.zeros(n, dtype=torch.int64, device=self.device)
        self.head = 0

    def resize(self, n: int) -> None:
        if n != self.n:
            self._alloc(n)
            self.n = n

    # --- brain tap: trigger-group spikes (escape) ------------------------------------------------

    def tap(self, batch, _t: int, spikes: torch.Tensor) -> None:
        """Count trigger-group spikes per fly (registered on BrainBatch.taps; read-only)."""
        if not self.trigger_ids.numel() or not spikes.numel():
            return
        hit = torch.isin(spikes % batch.n, self.trigger_ids)
        if bool(hit.any()):
            self.spikes += torch.bincount(spikes[hit] // batch.n, minlength=self.n)[: self.n]

    # --- one physics step --------------------------------------------------------------------------

    def read(self, rates: torch.Tensor) -> MotorOutput:
        """Commands from the brain's filtered group rates [N, G] (Hz)."""
        n = rates.shape[0]
        self.resize(n)
        r = rates.double()
        left = self._sat((r @ self._w_in) / self._n_cols)  # one-sided: mean over its groups
        right = self._sat(r @ self._w_right) * self._lr
        now = self._max * (left - right)
        now = torch.where(self._trig, (self.spikes.unsqueeze(1) >= self._trig_n).double(), now)
        self.spikes.zero_()
        # Latency line: write now, read each primitive's delayed value.
        depth = self.history.shape[0]
        self.history[self.head] = now
        out = self.history[(self.head - self._lat) % depth, :, self._prim_ix].T  # [N, P]
        self.head = (self.head + 1) % depth
        return self._combine(out)

    def _sat(self, rate: torch.Tensor) -> torch.Tensor:
        x = ((rate - self._thr) / self._half).clamp_min(0)
        return x / (1 + x)

    def _combine(self, out: torch.Tensor) -> MotorOutput:
        acc = dict(
            zip(COMMANDS, ((out @ self._sign).T), strict=True)
        )  # superposition (MOTOR-R-003)
        effort = out.abs() @ self._cost
        act = dict(zip((p.name for p in self.prims), out.T, strict=True))
        groom = acc["groom"].clamp(0, 1)
        speed = acc["speed"] * (1 - groom * (1 - self.groom_walk_factor))  # forelegs busy
        cmd = Commands(
            speed=speed,
            yaw=acc["yaw"],
            jump=acc["jump"] > 0,
            landing=acc["landing"] > 0,
            proboscis=acc["proboscis"].clamp(0, 1),
        )
        return MotorOutput(cmd, acc["pump"].clamp_min(0), groom, effort, act)
