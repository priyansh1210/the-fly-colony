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
        now = torch.zeros(n, len(self.prims), dtype=torch.float64, device=self.device)
        for i, p in enumerate(self.prims):
            if p.trigger_spikes:
                now[:, i] = (self.spikes >= p.trigger_spikes).double()
                continue
            if p.lr:
                left = self._sat(r[:, p.cols[0]], p)
                right = self._sat(r[:, p.cols[1]], p)
                now[:, i] = p.max * (left - right)
            else:
                now[:, i] = p.max * self._sat(r[:, p.cols].mean(1), p)
        self.spikes.zero_()
        # Latency line: write now, read each primitive's delayed value.
        depth = self.history.shape[0]
        self.history[self.head] = now
        out = torch.stack(
            [self.history[(self.head - p.latency) % depth, :, i] for i, p in enumerate(self.prims)],
            1,
        )
        self.head = (self.head + 1) % depth
        return self._combine(out)

    @staticmethod
    def _sat(rate: torch.Tensor, p: Prim) -> torch.Tensor:
        x = ((rate - p.threshold) / p.half).clamp_min(0)
        return x / (1 + x)

    def _combine(self, out: torch.Tensor) -> MotorOutput:
        n = out.shape[0]
        z = torch.zeros(n, dtype=torch.float64, device=self.device)
        acc = {c: z.clone() for c in COMMANDS}
        act: dict[str, torch.Tensor] = {}
        effort = z.clone()
        for i, p in enumerate(self.prims):
            v = out[:, i] * p.sign
            act[p.name] = out[:, i]
            acc[p.command] = acc[p.command] + v  # superposition (MOTOR-R-003)
            effort = effort + out[:, i].abs() * p.cost
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
