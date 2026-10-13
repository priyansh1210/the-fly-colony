"""Arena geometry: analytic convex arenas, their faces and surface properties (WORLD-R-010..012).

An arena is a cylinder (the Colony Dome) or an axis-aligned box (chambers, gate arenas), with the
floor at z = 0. Each face has an inward normal, a material and a containment test, so bodies can
walk across edges (floor → wall → ceiling) and rays can be cast analytically, with no mesh.

Units: millimetres. All functions are batched over points and work on any device.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import torch

FLOOR, CEILING = 0, 1  # face ids shared by every arena; walls follow
_DIM = 3  # registry-ok: 3D vectors
_FACE_AXIS = -2  # registry-ok: the face axis of a [..., F, 3] stack


@dataclass(frozen=True)
class Material:
    walkable: bool = True
    graspable: bool = True
    substrate: str = "plain"
    texture: str = "plain"


@dataclass(frozen=True)
class Arena:
    """kind: "cylinder" (radius, height) or "box" (size_x, size_y, height)."""

    kind: str
    height: float
    radius: float = 0.0
    size_x: float = 0.0
    size_y: float = 0.0
    materials: dict[str, Material] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in ("cylinder", "box"):
            raise ValueError(f"arena kind {self.kind!r}; use 'cylinder' or 'box'")
        if self.height <= 0 or (self.kind == "cylinder" and self.radius <= 0):
            raise ValueError("arena dimensions must be positive")
        if self.kind == "box" and (self.size_x <= 0 or self.size_y <= 0):
            raise ValueError("arena dimensions must be positive")

    # --- faces -------------------------------------------------------------------------------

    @property
    def face_names(self) -> list[str]:
        walls = (
            ["wall"] if self.kind == "cylinder" else ["wall_x0", "wall_x1", "wall_y0", "wall_y1"]
        )
        return ["floor", "ceiling", *walls]

    @property
    def n_faces(self) -> int:
        return len(self.face_names)

    def material(self, face: int) -> Material:
        name = self.face_names[face]
        base = "wall" if name.startswith("wall") else name
        return self.materials.get(name, self.materials.get(base, Material()))

    @property
    def bounds(self) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
        """Axis-aligned bounding box ((x0, x1), (y0, y1), (z0, z1))."""
        if self.kind == "cylinder":
            r = self.radius
            return (-r, r), (-r, r), (0.0, self.height)
        return (0.0, self.size_x), (0.0, self.size_y), (0.0, self.height)

    @property
    def center_xy(self) -> tuple[float, float]:
        if self.kind == "cylinder":
            return 0.0, 0.0
        return self.size_x / 2, self.size_y / 2

    def violation(self, p: torch.Tensor) -> torch.Tensor:
        """How far each point is outside each face's half-space: [..., n_faces] (≤ 0 = inside)."""
        x, y, z = p.unbind(-1)
        cols = [-z, z - self.height]
        if self.kind == "cylinder":
            cols.append(torch.sqrt(x * x + y * y) - self.radius)
        else:
            cols += [-x, x - self.size_x, -y, y - self.size_y]
        return torch.stack(cols, -1)

    def normal(self, face: torch.Tensor, p: torch.Tensor) -> torch.Tensor:
        """Inward unit normal of `face` at points `p` (batched; face is an int tensor)."""
        x, y, _ = p.unbind(-1)
        zero, one = torch.zeros_like(x), torch.ones_like(x)
        cand = [torch.stack([zero, zero, one], -1), torch.stack([zero, zero, -one], -1)]
        if self.kind == "cylinder":
            r = torch.sqrt(x * x + y * y).clamp_min(torch.finfo(p.dtype).tiny)
            cand.append(torch.stack([-x / r, -y / r, zero], -1))
        else:
            cand += [
                torch.stack([one, zero, zero], -1),
                torch.stack([-one, zero, zero], -1),
                torch.stack([zero, one, zero], -1),
                torch.stack([zero, -one, zero], -1),
            ]
        stacked = torch.stack(
            cand, _FACE_AXIS
        )  # [..., F, 3]  # registry-ok: box face ids in face_names order
        idx = (
            face.long().unsqueeze(-1).unsqueeze(-1).expand(*face.shape, 1, _DIM)
        )  # registry-ok: box face ids in face_names order
        return stacked.gather(-2, idx).squeeze(-2)  # registry-ok: box face ids in face_names order

    def project(self, face: torch.Tensor, p: torch.Tensor) -> torch.Tensor:
        """Put points exactly on their face (removes drift from finite steps)."""
        x, y, z = p.unbind(-1)
        f = face.long()
        z = torch.where(f == FLOOR, torch.zeros_like(z), z)
        z = torch.where(f == CEILING, torch.full_like(z, self.height), z)
        if self.kind == "cylinder":
            r = torch.sqrt(x * x + y * y).clamp_min(torch.finfo(p.dtype).tiny)
            on_wall = f == 2  # registry-ok: the cylinder's single wall face id
            s = torch.where(on_wall, self.radius / r, torch.ones_like(r))
            x, y = x * s, y * s
        else:
            for fid, axis, val in (
                (2, 0, 0.0),  # registry-ok: box face ids in face_names order
                (3, 0, self.size_x),  # registry-ok: box face ids in face_names order
                (4, 1, 0.0),  # registry-ok: box face ids in face_names order
                (5, 1, self.size_y),  # registry-ok: box face ids in face_names order
            ):
                if axis == 0:
                    x = torch.where(f == fid, torch.full_like(x, val), x)
                else:
                    y = torch.where(f == fid, torch.full_like(y, val), y)
        return torch.stack([x, y, z], -1)

    def spec(self) -> dict:
        return {
            "kind": self.kind,
            "height": self.height,
            "radius": self.radius,
            "size_x": self.size_x,
            "size_y": self.size_y,
            "materials": {k: vars(v) for k, v in sorted(self.materials.items())},
        }

    def spec_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.spec(), sort_keys=True).encode()).hexdigest()[:16]


def rotate_frame(v: torch.Tensor, n_from: torch.Tensor, n_to: torch.Tensor) -> torch.Tensor:
    """Rotate vectors `v` by the rotation that takes unit normal `n_from` to `n_to` (Rodrigues).

    Used when a walking body crosses an edge: its heading turns with the surface.
    """
    axis = torch.cross(n_from, n_to, dim=-1)
    s = axis.norm(dim=-1, keepdim=True)
    c = (n_from * n_to).sum(-1, keepdim=True)
    k = axis / s.clamp_min(torch.finfo(v.dtype).tiny)
    kv = torch.cross(k, v, dim=-1)
    kdv = (k * v).sum(-1, keepdim=True)
    out = v * c + kv * s + k * kdv * (1 - c)
    return torch.where(s > torch.finfo(v.dtype).eps, out, v)
