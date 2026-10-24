"""ColonyBody v1: batched fly bodies in a world group (BODY-R-001..004, -006..008).

- Grounded bodies walk kinematically on any walkable face; crossing an edge rotates the body frame
  onto the next face (floor → wall → ceiling).
- Airborne bodies are point masses under gravity and linear drag relative to the local wind. The
  escape jump is ballistic (fixed impulse and duration, MOTOR-R-002); with no flight thrust mapped
  yet (005 §2) airborne flies glide and land on the first graspable face they touch.
- A body moves only because of motor commands or external forces (BODY-R-008): with zero commands a
  grounded body stays exactly where it is.

Units: mm, s, radians. State is float64 so long runs keep sub-micrometre precision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

from flycolony.registry import Registry
from flycolony.world.geometry import Arena, rotate_frame

GROUNDED, AIRBORNE, COUPLED = 0, 1, 2
DIM = 3  # registry-ok: 3D vectors
EPS = 1e-9  # registry-ok: mm, numerical floor for degenerate directions
TINY = 1e-12  # registry-ok: division guard


@dataclass
class BodyParams:
    body_length: float
    stand_height: float
    head_offset: float
    head_height: float
    antenna_forward: float
    antenna_lateral: float
    antenna_height: float
    eye_lateral: float
    proboscis_length: float
    proboscis_angle: float
    labellum_rest_drop: float
    proboscis_tau_s: float
    tarsus_lateral: float
    max_speed: float
    max_back_speed: float
    max_yaw: float
    jump_speed: float
    jump_angle: float
    jump_duration_s: float
    gravity: float
    drag_per_s: float
    impact_threshold: float
    impact_threshold_landing: float
    radius: float

    @classmethod
    def from_registry(cls, reg: Registry) -> BodyParams:
        g = lambda k: float(reg.get(k))  # noqa: E731
        return cls(
            body_length=g("body.size.length_mm"),
            stand_height=g("body.size.stand_height_mm"),
            head_offset=g("body.size.head_offset_mm"),
            head_height=g("body.size.head_height_mm"),
            antenna_forward=g("body.sites.antenna_forward_mm"),
            antenna_lateral=g("body.sites.antenna_lateral_mm"),
            antenna_height=g("body.sites.antenna_height_mm"),
            eye_lateral=g("body.sites.eye_lateral_mm"),
            proboscis_length=g("body.proboscis.length_mm"),
            proboscis_angle=g("body.proboscis.angle_rad"),
            labellum_rest_drop=g("body.proboscis.rest_drop_mm"),
            proboscis_tau_s=g("body.proboscis.tau_s"),
            tarsus_lateral=g("body.sites.tarsus_lateral_mm"),
            max_speed=g("body.walk.max_speed_mm_s"),
            max_back_speed=g("body.walk.max_back_speed_mm_s"),
            max_yaw=g("body.walk.max_yaw_rad_s"),
            jump_speed=g("body.jump.speed_mm_s"),
            jump_angle=g("body.jump.angle_rad"),
            jump_duration_s=g("body.jump.duration_s"),
            gravity=g("body.flight.gravity_mm_s2"),
            drag_per_s=g("body.flight.drag_per_s"),
            impact_threshold=g("body.injury.impact_mm_s"),
            impact_threshold_landing=g("body.injury.impact_landing_mm_s"),
            radius=g("body.size.length_mm") / 2,
        )


@dataclass
class Commands:
    """Motor commands for one physics step (from 005). All zeros = no motor output."""

    speed: torch.Tensor  # mm/s, signed (forward > 0)
    yaw: torch.Tensor  # rad/s, left turn > 0
    jump: torch.Tensor  # bool: ballistic escape jump trigger
    landing: torch.Tensor  # bool: landing extension
    proboscis: torch.Tensor  # extension target in [0, 1]

    @classmethod
    def zeros(cls, n: int, device: torch.device) -> Commands:
        f = torch.zeros(n, dtype=torch.float64, device=device)
        b = torch.zeros(n, dtype=torch.bool, device=device)
        return cls(f, f.clone(), b, b.clone(), f.clone())


class BodyBatch:
    """N bodies, each in one world of a world group sharing `arena`."""

    STATE = (
        "pos",
        "fwd",
        "up",
        "vel",
        "mode",
        "face",
        "proboscis",
        "jump_left",
        "injury",
        "yaw_rate",
        "world",
        "speed",
    )

    def __init__(self, arena: Arena, params: BodyParams, device: torch.device):
        self.arena, self.p, self.device = arena, params, device
        f64 = torch.float64
        z3 = torch.zeros(0, 3, dtype=f64, device=device)  # registry-ok: 3D vectors
        z = torch.zeros(0, dtype=f64, device=device)
        self.ids: list[str] = []
        self.pos, self.fwd, self.up, self.vel = z3, z3.clone(), z3.clone(), z3.clone()
        self.mode = torch.zeros(0, dtype=torch.long, device=device)
        self.face = torch.zeros(0, dtype=torch.long, device=device)
        self.world = torch.zeros(0, dtype=torch.long, device=device)
        self.proboscis, self.jump_left, self.injury = z.clone(), z.clone(), z.clone()
        self.yaw_rate, self.speed = z.clone(), z.clone()
        self.last_impact = z.clone()
        self._sites: tuple[tuple[torch.Tensor, ...], dict[str, torch.Tensor]] | None = None
        self._graspable: torch.Tensor | None = None

    @property
    def n(self) -> int:
        return len(self.ids)

    def add(
        self, fly_id: str, world: int, xy: tuple[float, float], heading_rad: float, face: int = 0
    ) -> None:
        """Place a grounded fly on a face (default the floor) at in-plane position xy."""
        if fly_id in self.ids:
            raise ValueError(f"fly {fly_id!r} already has a body")
        f64, dev = torch.float64, self.device
        if face != 0:
            raise NotImplementedError("Phase 2 places new bodies on the floor")
        pos = torch.tensor([[xy[0], xy[1], 0.0]], dtype=f64, device=dev)
        up = torch.tensor([[0.0, 0.0, 1.0]], dtype=f64, device=dev)
        fwd = torch.tensor(
            [
                [
                    torch.cos(torch.tensor(heading_rad)).item(),
                    torch.sin(torch.tensor(heading_rad)).item(),
                    0.0,
                ]
            ],
            dtype=f64,
            device=dev,
        )
        if (self.arena.violation(pos) > 0).any():
            raise ValueError(f"{fly_id}: start position {xy} is outside the arena")
        cat = lambda a, b: torch.cat([a, b])  # noqa: E731
        self.ids.append(fly_id)
        self.pos, self.fwd, self.up = cat(self.pos, pos), cat(self.fwd, fwd), cat(self.up, up)
        self.vel = cat(
            self.vel, torch.zeros(1, DIM, dtype=f64, device=dev)
        )  # registry-ok: 3D vectors
        one = lambda v, dt=f64: torch.tensor([v], dtype=dt, device=dev)  # noqa: E731
        self.mode = cat(self.mode, one(GROUNDED, torch.long))
        self.face = cat(self.face, one(face, torch.long))
        self.world = cat(self.world, one(world, torch.long))
        for k in ("proboscis", "jump_left", "injury", "yaw_rate", "speed", "last_impact"):
            setattr(self, k, cat(getattr(self, k), one(0.0)))

    def index(self, fly_id: str) -> int:
        return self.ids.index(fly_id)

    @property
    def left(self) -> torch.Tensor:
        return torch.cross(self.up, self.fwd, dim=-1)

    # --- physics step -------------------------------------------------------------------------------

    def step(self, cmd: Commands, dt: float, wind: torch.Tensor | None = None) -> None:
        """One physics step of dt seconds. `wind` is the air velocity at each body [N, 3]."""
        p = self.p
        grounded = self.mode == GROUNDED
        airborne = self.mode == AIRBORNE
        # Proboscis follows its command with a first-order lag.
        a = 1 - math.exp(-dt / p.proboscis_tau_s)
        self.proboscis = self.proboscis + (cmd.proboscis.clamp(0, 1) - self.proboscis) * a
        # Ballistic jump trigger (grounded only).
        jump = cmd.jump & grounded & (self.jump_left <= 0)
        walking = grounded & ~jump
        moving = walking & ((cmd.speed != 0) | (cmd.yaw != 0))
        # One host read for all the branch flags of this step.
        any_jump, any_air, any_move = torch.stack(
            [jump.any(), (airborne | jump).any(), moving.any()]
        ).tolist()
        if any_jump:
            dirn = self.fwd * math.cos(p.jump_angle) + self.up * math.sin(p.jump_angle)
            self.vel = torch.where(jump.unsqueeze(-1), dirn * p.jump_speed, self.vel)
            self.jump_left = torch.where(
                jump, torch.full_like(self.jump_left, p.jump_duration_s), self.jump_left
            )
            self.mode = torch.where(jump, torch.full_like(self.mode, AIRBORNE), self.mode)
            # Lift off the surface so the first airborne step does not register a landing.
            self.pos = torch.where(
                jump.unsqueeze(-1), self.pos + self.up * p.stand_height, self.pos
            )
            airborne = self.mode == AIRBORNE
        self._walk(cmd, dt, walking, moving, any_move)
        if any_air:
            self._fly(cmd, dt, airborne, wind)
        self._collide()

    def _walk(
        self, cmd: Commands, dt: float, grounded: torch.Tensor, moving: torch.Tensor, any_move: bool
    ) -> None:
        p = self.p
        speed = cmd.speed.clamp(-p.max_back_speed, p.max_speed) * grounded
        yaw = cmd.yaw.clamp(-p.max_yaw, p.max_yaw) * grounded
        self.speed, self.yaw_rate = speed, yaw
        if not any_move:
            return
        # Turn about the surface normal, then step forward in the tangent plane.
        ang = (yaw * dt).unsqueeze(-1)
        fwd = self.fwd * torch.cos(ang) + torch.cross(self.up, self.fwd, dim=-1) * torch.sin(ang)
        pos = self.pos + fwd * (speed * dt).unsqueeze(-1)
        up = self.up
        # Edge crossing: the most violated other face becomes the new surface.
        viol = self.arena.violation(pos)
        viol = viol.scatter(-1, self.face.unsqueeze(-1), float("-inf"))
        worst, new_face = viol.max(-1)
        cross = moving & (worst > 0)
        n_new = self.arena.normal(new_face, pos)
        fwd = torch.where(cross.unsqueeze(-1), rotate_frame(fwd, up, n_new), fwd)
        up = torch.where(cross.unsqueeze(-1), n_new, up)
        face = torch.where(cross, new_face, self.face)
        pos = self.arena.project(face, pos)
        up = torch.where(moving.unsqueeze(-1), self.arena.normal(face, pos), up)
        # Keep the frame orthonormal.
        fwd = fwd - up * (fwd * up).sum(-1, keepdim=True)
        fwd = fwd / fwd.norm(dim=-1, keepdim=True)
        m = moving.unsqueeze(-1)
        self.pos = torch.where(m, pos, self.pos)
        self.fwd = torch.where(m, fwd, self.fwd)
        self.up = torch.where(m, up, self.up)
        self.face = torch.where(moving, face, self.face)

    def _fly(self, cmd: Commands, dt: float, airborne: torch.Tensor, wind) -> None:
        p = self.p
        g = torch.tensor([0.0, 0.0, -p.gravity], dtype=torch.float64, device=self.device)
        air = wind if wind is not None else torch.zeros_like(self.vel)
        in_jump = self.jump_left > 0
        # During the jump the legs push: velocity is held; afterwards gravity and drag act.
        acc = g - p.drag_per_s * (self.vel - air)
        vel = torch.where((airborne & ~in_jump).unsqueeze(-1), self.vel + acc * dt, self.vel)
        pos = torch.where(airborne.unsqueeze(-1), self.pos + vel * dt, self.pos)
        self.jump_left = (self.jump_left - dt * airborne).clamp_min(0)
        # Landing on the first face crossed; impact above threshold gives injury points.
        viol = self.arena.violation(pos)
        worst, face = viol.max(-1)
        land = airborne & (worst > 0) & (self.jump_left <= 0)
        if bool(land.any()):
            n = self.arena.normal(face, pos)
            impact = (-(vel * n).sum(-1)).clamp_min(0)
            thr = torch.where(
                cmd.landing,
                torch.full_like(impact, p.impact_threshold_landing),
                torch.full_like(impact, p.impact_threshold),
            )
            self.injury = self.injury + torch.where(
                land, (impact - thr).clamp_min(0) / thr, torch.zeros_like(impact)
            )
            self.last_impact = torch.where(land, impact, self.last_impact)
            if self._graspable is None:
                self._graspable = torch.tensor(
                    [self.arena.material(i).graspable for i in range(self.arena.n_faces)],
                    device=self.device,
                )
            land = land & self._graspable[face]
            heading = vel - n * (vel * n).sum(-1, keepdim=True)
            hn = heading.norm(dim=-1, keepdim=True)
            old_t = self.fwd - n * (self.fwd * n).sum(-1, keepdim=True)
            heading = torch.where(
                hn > EPS, heading / hn.clamp_min(TINY), old_t
            )  # registry-ok: numerical floor for a zero heading
            heading = heading / heading.norm(dim=-1, keepdim=True).clamp_min(
                TINY
            )  # registry-ok: numerical floor
            m = land.unsqueeze(-1)
            pos = torch.where(m, self.arena.project(face, pos), pos)
            self.fwd = torch.where(m, heading, self.fwd)
            self.up = torch.where(m, n, self.up)
            vel = torch.where(m, torch.zeros_like(vel), vel)
            self.face = torch.where(land, face, self.face)
            self.mode = torch.where(land, torch.full_like(self.mode, GROUNDED), self.mode)
        # Non-graspable faces: stay inside (inelastic).
        out = (self.mode == AIRBORNE) & (self.arena.violation(pos).max(-1).values > 0)
        if bool(out.any()):
            f = self.arena.violation(pos).max(-1).indices
            n = self.arena.normal(f, pos)
            pos = torch.where(out.unsqueeze(-1), self.arena.project(f, pos), pos)
            vel = torch.where(out.unsqueeze(-1), vel - n * (vel * n).sum(-1, keepdim=True), vel)
        self.pos, self.vel = pos, vel

    def _collide(self) -> None:
        """Grounded fly-fly overlap on the same world: symmetric push apart (deterministic)."""
        if self.n < 2:
            return
        same = (
            (self.world[:, None] == self.world[None, :])
            & (self.mode[:, None] == GROUNDED)
            & (self.mode[None, :] == GROUNDED)
        )
        d = self.pos[:, None, :] - self.pos[None, :, :]
        dist = d.norm(dim=-1)
        overlap = (2 * self.p.radius - dist).clamp_min(0) * same
        overlap.fill_diagonal_(0)
        push = (d / dist.clamp_min(EPS).unsqueeze(-1) * (overlap / 2).unsqueeze(-1)).sum(
            1
        )  # registry-ok: numerical floor for coincident flies
        hit = (overlap > 0).any(1, keepdim=True)
        self.pos = torch.where(hit, self.arena.project(self.face, self.pos + push), self.pos)

    # --- contact sites (BODY-R-004) -------------------------------------------------------------------

    def sites(self) -> dict[str, torch.Tensor]:
        """World positions of the contact and sensor sites [N, 3] each.

        Cached until the body state they depend on is replaced (state tensors are never written in
        place), so the senses, physics and contacts of one step share one computation.
        """
        key = (self.pos, self.fwd, self.up, self.proboscis)
        if self._sites is not None and all(
            a is b for a, b in zip(self._sites[0], key, strict=True)
        ):
            return self._sites[1]
        p = self.p
        lft, up, fwd = self.left, self.up, self.fwd
        center = self.pos + up * p.stand_height
        head = center + fwd * p.head_offset + up * (p.head_height - p.stand_height)
        ext = self.proboscis.unsqueeze(-1)
        drop = p.labellum_rest_drop + ext * p.proboscis_length * math.sin(p.proboscis_angle)
        reach = ext * p.proboscis_length * math.cos(p.proboscis_angle)
        labellum = head - up * drop + fwd * reach
        ant = head + fwd * p.antenna_forward + up * p.antenna_height
        sites = {
            "center": center,
            "head": head,
            "labellum": labellum,
            "antenna_l": ant + lft * p.antenna_lateral,
            "antenna_r": ant - lft * p.antenna_lateral,
            "eye_l": head + lft * p.eye_lateral,
            "eye_r": head - lft * p.eye_lateral,
            "tarsi_l": self.pos + lft * p.tarsus_lateral,
            "tarsi_r": self.pos - lft * p.tarsus_lateral,
        }
        self._sites = (key, sites)
        return sites

    # --- checkpoint --------------------------------------------------------------------------------------

    def state_dict(self) -> dict:
        return {
            "ids": list(self.ids),
            **{k: getattr(self, k).cpu() for k in (*self.STATE, "last_impact")},
        }

    def load_state_dict(self, s: dict) -> None:
        self.ids = list(s["ids"])
        for k in (*self.STATE, "last_impact"):
            setattr(self, k, s[k].to(self.device))
