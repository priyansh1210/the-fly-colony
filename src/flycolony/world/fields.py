"""Scalar fields on a 3D grid: odorants, temperature, humidity; steady wind (WORLD-R-032, -033, -040).

- One cell-centred grid per world group, covering the arena's bounding box. Cells whose centre is
  outside the arena are solid.
- Transport is finite-volume and conservative: first-order upwind advection through cell faces,
  explicit diffusion, exponential decay, dense sources, and relaxation sources (for temperature and
  humidity set-points). The flux leaving one cell enters its neighbour exactly, so mass changes only
  through decay, sources and outflow vents (WORLD-AC-02).
- Wind is incompressible potential flow, ∇²φ = 0 with the vents' normal velocities as Neumann
  conditions, solved by conjugate gradient whenever vents change (WORLD-R-033).
- Every operation is a dense stencil or reduction: no scatter, no atomics, so steps are bit-identical
  on a given device (WORLD-R-002).

Units: mm, s, concentrations in amount per mm³ (species-specific amount unit), velocities in mm/s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import torch

from flycolony.world.geometry import Arena

_AXES = ("x", "y", "z")
_CELL_TOL = 1e-9  # registry-ok: float tolerance when counting cells
_XYZ = (2, 3, 4)  # registry-ok: spatial axes of the [W, S, x, y, z] grid


class FieldError(ValueError):
    """Inconsistent vents or an unstable field configuration."""


@dataclass(frozen=True)
class Vent:
    """A rectangular patch on a planar face with a normal velocity (mm/s, > 0 = into the arena).

    face: "floor", "ceiling", "wall_x0", "wall_x1", "wall_y0", "wall_y1" (box walls only).
    lo, hi: patch corners in the face's two in-plane coordinates (mm), e.g. (y, z) on wall_x0.
    """

    face: str
    lo: tuple[float, float]
    hi: tuple[float, float]
    speed: float


class Grid:
    """Cell layout, solid mask and open-face masks for one arena at one resolution."""

    def __init__(self, arena: Arena, cell_mm: float, device: torch.device):
        self.arena, self.cell, self.device = arena, float(cell_mm), device
        (x0, x1), (y0, y1), (z0, z1) = arena.bounds
        self.origin = (x0, y0, z0)
        self.shape = tuple(
            max(
                1, math.ceil((hi - lo) / self.cell - _CELL_TOL)
            )  # registry-ok: float tolerance in the cell count
            for lo, hi in ((x0, x1), (y0, y1), (z0, z1))
        )
        c = self.centers()
        self.fluid = (arena.violation(c) <= 0).all(-1)  # [nx, ny, nz]
        f = self.fluid
        # Interior faces are open when both neighbouring cells are fluid.
        self.open = {
            "x": f[1:, :, :] & f[:-1, :, :],
            "y": f[:, 1:, :] & f[:, :-1, :],
            "z": f[:, :, 1:] & f[:, :, :-1],
        }
        self.volume = self.cell**3  # registry-ok: 3D cell layout
        self.area = self.cell**2
        # Constants for point queries (built once: no host→device copies per query).
        self._origin = torch.tensor(self.origin, dtype=torch.float64, device=device)
        self._hi = torch.tensor(self.shape, device=device) - 1

    def centers(self) -> torch.Tensor:
        nx, ny, nz = self.shape
        ax = [
            torch.arange(n, device=self.device, dtype=torch.float64) * self.cell + o + self.cell / 2
            for n, o in zip((nx, ny, nz), self.origin, strict=True)
        ]
        gx, gy, gz = torch.meshgrid(*ax, indexing="ij")
        return torch.stack([gx, gy, gz], -1)

    def cell_of(self, p: torch.Tensor) -> torch.Tensor:
        """Integer cell index (clamped to the grid) of points [..., 3] → [..., 3]."""
        idx = torch.floor((p - self._origin.to(p.dtype)) / self.cell).long()
        return torch.minimum(idx.clamp_min(0), self._hi)

    def boundary_inflow(self, vents: list[Vent]) -> dict[str, torch.Tensor]:
        """Normal velocity on each domain-boundary face (into the domain > 0), per side.

        Returns {"x0": [ny, nz], "x1": [ny, nz], "y0": [nx, nz], "y1": [nx, nz], "z0": [nx, ny],
        "z1": [nx, ny]} for box arenas; cylinders support floor/ceiling vents only.
        """
        nx, ny, nz = self.shape
        out = {
            "x0": torch.zeros(ny, nz, dtype=torch.float64, device=self.device),
            "x1": torch.zeros(ny, nz, dtype=torch.float64, device=self.device),
            "y0": torch.zeros(nx, nz, dtype=torch.float64, device=self.device),
            "y1": torch.zeros(nx, nz, dtype=torch.float64, device=self.device),
            "z0": torch.zeros(nx, ny, dtype=torch.float64, device=self.device),
            "z1": torch.zeros(nx, ny, dtype=torch.float64, device=self.device),
        }
        side = {
            "floor": ("z0", (0, 1)),
            "ceiling": ("z1", (0, 1)),
            "wall_x0": ("x0", (1, 2)),
            "wall_x1": ("x1", (1, 2)),
            "wall_y0": ("y0", (0, 2)),
            "wall_y1": ("y1", (0, 2)),
        }
        c = self.centers()
        for v in vents:
            if v.face not in side or (self.arena.kind == "cylinder" and v.face.startswith("wall")):
                raise FieldError(f"vent face {v.face!r} not supported for a {self.arena.kind}")
            key, (a, b) = side[v.face]
            plane = {
                "x0": c[0],
                "x1": c[-1],
                "y0": c[:, 0],
                "y1": c[:, -1],
                "z0": c[:, :, 0],
                "z1": c[:, :, -1],
            }[key]
            sel = (
                (plane[..., a] >= v.lo[0])
                & (plane[..., a] <= v.hi[0])
                & (plane[..., b] >= v.lo[1])
                & (plane[..., b] <= v.hi[1])
            )
            fl = {
                "x0": self.fluid[0],
                "x1": self.fluid[-1],
                "y0": self.fluid[:, 0],
                "y1": self.fluid[:, -1],
                "z0": self.fluid[:, :, 0],
                "z1": self.fluid[:, :, -1],
            }[key]
            out[key] = torch.where(sel & fl, torch.full_like(out[key], v.speed), out[key])
        return out


# --- wind ------------------------------------------------------------------------------------


@dataclass
class Wind:
    """Face velocities (mm/s) on the grid: u[nx+1, ny, nz], v[nx, ny+1, nz], w[nx, ny, nz+1].

    Positive = toward increasing coordinate. Boundary faces hold the vent velocities.
    """

    u: torch.Tensor
    v: torch.Tensor
    w: torch.Tensor
    residual: float = 0.0
    _max_speed: float | None = field(default=None, init=False, repr=False)

    def max_speed(self) -> float:
        if self._max_speed is None:  # the faces never change after the solve
            self._max_speed = float(max(self.u.abs().max(), self.v.abs().max(), self.w.abs().max()))
        return self._max_speed

    def at(self, grid: Grid, p: torch.Tensor) -> torch.Tensor:
        """Wind vector at points [..., 3]: cell-centre average of the face velocities (piecewise)."""
        i = grid.cell_of(p)
        ix, iy, iz = i.unbind(-1)
        ux = (self.u[ix, iy, iz] + self.u[ix + 1, iy, iz]) / 2
        vy = (self.v[ix, iy, iz] + self.v[ix, iy + 1, iz]) / 2
        wz = (self.w[ix, iy, iz] + self.w[ix, iy, iz + 1]) / 2
        return torch.stack([ux, vy, wz], -1).to(p.dtype)


def solve_wind(grid: Grid, vents: list[Vent], *, tol: float, max_iter: int) -> Wind:
    """Potential flow from vents (conjugate gradient on the Neumann Laplacian)."""
    nx, ny, nz = grid.shape
    dev, f64 = grid.device, torch.float64
    inflow = grid.boundary_inflow(vents)
    a = grid.area
    net = sum(float(t.sum()) for t in inflow.values()) * a  # all entries point into the domain
    if abs(net) > tol * max(1.0, sum(float(t.abs().sum()) for t in inflow.values()) * a):
        raise FieldError(f"vents are not balanced: net inflow {net:.3g} mm³/s (must be 0)")
    fluid = grid.fluid
    ox, oy, oz = (grid.open[k].to(f64) for k in _AXES)

    def lap(phi: torch.Tensor) -> torch.Tensor:
        """−∇²φ·dx² restricted to open faces (symmetric positive semidefinite)."""
        out = torch.zeros_like(phi)
        d = (phi[1:] - phi[:-1]) * ox
        out[:-1] -= d
        out[1:] += d
        d = (phi[:, 1:] - phi[:, :-1]) * oy
        out[:, :-1] -= d
        out[:, 1:] += d
        d = (phi[:, :, 1:] - phi[:, :, :-1]) * oz
        out[:, :, :-1] -= d
        out[:, :, 1:] += d
        return out * fluid

    # Right-hand side: inflow per cell (mm/s × dx), so that  lap(φ) = b  gives ∇φ·n = inflow.
    b = torch.zeros(nx, ny, nz, dtype=f64, device=dev)
    b[0] += inflow["x0"]
    b[-1] += inflow["x1"]
    b[:, 0] += inflow["y0"]
    b[:, -1] += inflow["y1"]
    b[:, :, 0] += inflow["z0"]
    b[:, :, -1] += inflow["z1"]
    b = b * grid.cell * fluid
    n_fluid = fluid.sum()

    def demean(x: torch.Tensor) -> torch.Tensor:
        return (x - (x * fluid).sum() / n_fluid) * fluid

    phi = torch.zeros_like(b)
    r = demean(b - lap(phi))
    p = r.clone()
    rr = (r * r).sum()
    b_norm = float(b.norm()) or 1.0
    it = 0
    for it in range(max_iter):  # noqa: B007
        if float(rr.sqrt()) <= tol * b_norm:
            break
        ap = lap(p)
        alpha = rr / (p * ap).sum()
        phi = phi + alpha * p
        r = demean(r - alpha * ap)
        rr_new = (r * r).sum()
        p = r + (rr_new / rr) * p
        rr = rr_new
    # Sign: lap = −∇²·dx², and the inflow on a low-side face points +axis, so u = −∇φ.
    u = torch.zeros(nx + 1, ny, nz, dtype=f64, device=dev)
    v = torch.zeros(nx, ny + 1, nz, dtype=f64, device=dev)
    w = torch.zeros(nx, ny, nz + 1, dtype=f64, device=dev)
    u[1:-1] = -(phi[1:] - phi[:-1]) / grid.cell * ox
    v[:, 1:-1] = -(phi[:, 1:] - phi[:, :-1]) / grid.cell * oy
    w[:, :, 1:-1] = -(phi[:, :, 1:] - phi[:, :, :-1]) / grid.cell * oz
    u[0], u[-1] = inflow["x0"], -inflow["x1"]
    v[:, 0], v[:, -1] = inflow["y0"], -inflow["y1"]
    w[:, :, 0], w[:, :, -1] = inflow["z0"], -inflow["z1"]
    res = float(r.norm()) / b_norm if float(b.abs().sum()) else 0.0
    return Wind(u, v, w, residual=res)


def zero_wind(grid: Grid) -> Wind:
    nx, ny, nz = grid.shape
    z = lambda *s: torch.zeros(*s, dtype=torch.float64, device=grid.device)  # noqa: E731
    return Wind(z(nx + 1, ny, nz), z(nx, ny + 1, nz), z(nx, ny, nz + 1))


# --- transport --------------------------------------------------------------------------------


@dataclass(frozen=True)
class SpeciesSpec:
    name: str
    diffusion_mm2_s: float
    decay_per_s: float = 0.0
    ambient: float = 0.0  # initial value and the value carried in by inflow vents


class Fields:
    """S transported scalar species over W worlds of one grid: c[W, S, nx, ny, nz] (float64)."""

    def __init__(self, grid: Grid, species: list[SpeciesSpec], n_worlds: int, wind: Wind):
        self.grid, self.species, self.wind = grid, species, wind
        self.names = [s.name for s in species]
        dev, f64 = grid.device, torch.float64
        shape = (n_worlds, len(species), *grid.shape)
        amb = torch.tensor([s.ambient for s in species], dtype=f64, device=dev)
        self.c = amb.view(1, -1, 1, 1, 1).expand(shape).clone() * grid.fluid
        self.ambient = amb
        self.diff = torch.tensor([s.diffusion_mm2_s for s in species], dtype=f64, device=dev)
        self.decay = torch.tensor([s.decay_per_s for s in species], dtype=f64, device=dev)
        self.source = torch.zeros(shape, dtype=f64, device=dev)  # amount per s per cell
        self.relax_target = torch.zeros(shape, dtype=f64, device=dev)
        self.relax_rate = torch.zeros(shape, dtype=f64, device=dev)  # 1/s, 0 = no relaxation
        self._diff_max = float(self.diff.max()) if self.diff.numel() else 0.0
        # The 8 trilinear corners as index offsets [8, 3] and a mask of which are the upper ones.
        corners = [(dx, dy, dz) for dx in (0, 1) for dy in (0, 1) for dz in (0, 1)]
        self._corners = torch.tensor(corners, device=dev)
        self._upper = self._corners.bool()

    def index(self, name: str) -> int:
        return self.names.index(name)

    def substeps(self, dt: float, max_cfl: float, max_diff: float) -> int:
        """Sub-steps needed for stability (CFL ≤ max_cfl, diffusion number ≤ max_diff)."""
        h = self.grid.cell
        cfl = self.wind.max_speed() * dt / h
        dn = self._diff_max * dt / (h * h)
        return max(1, math.ceil(cfl / max_cfl), math.ceil(dn / max_diff))

    def step(self, dt: float, *, max_cfl: float, max_diff: float) -> None:
        n = self.substeps(dt, max_cfl, max_diff)
        h = dt / n
        for _ in range(n):
            self._substep(h)

    def _substep(self, dt: float) -> None:
        g, c = self.grid, self.c
        fl = g.fluid
        h = g.cell
        div = torch.zeros_like(c)  # net outflow per cell (amount/s)
        amb = self.ambient.view(1, -1, 1, 1, 1)
        # Advection: interior faces, upwind.
        for axis, vel, open_ in (
            (0, self.wind.u, g.open["x"]),
            (1, self.wind.v, g.open["y"]),
            (2, self.wind.w, g.open["z"]),
        ):
            inner = vel.narrow(axis, 1, vel.shape[axis] - 2) * open_  # [.., n-1 along axis]
            lo = c.narrow(axis + 2, 0, c.shape[axis + 2] - 1)
            hi = c.narrow(axis + 2, 1, c.shape[axis + 2] - 1)
            flux = torch.where(inner > 0, inner * lo, inner * hi) * g.area  # + = toward hi
            div.narrow(axis + 2, 0, c.shape[axis + 2] - 1).add_(flux)
            div.narrow(axis + 2, 1, c.shape[axis + 2] - 1).sub_(flux)
            # Boundary faces: inflow carries ambient air in; outflow removes the cell's content.
            first, last = vel.narrow(axis, 0, 1), vel.narrow(axis, vel.shape[axis] - 1, 1)
            c_first = c.narrow(axis + 2, 0, 1)
            c_last = c.narrow(axis + 2, c.shape[axis + 2] - 1, 1)
            f_in_first = (
                torch.where(first > 0, first * amb.expand_as(c_first), first * c_first) * g.area
            )
            f_out_last = torch.where(last > 0, last * c_last, last * amb.expand_as(c_last)) * g.area
            div.narrow(axis + 2, 0, 1).sub_(f_in_first * fl.narrow(axis, 0, 1))
            div.narrow(axis + 2, c.shape[axis + 2] - 1, 1).add_(
                f_out_last * fl.narrow(axis, fl.shape[axis] - 1, 1)
            )
        c_new = c - dt * div / g.volume
        # Diffusion through open interior faces.
        k = (self.diff * dt / (h * h)).view(1, -1, 1, 1, 1)
        for axis, open_ in ((0, g.open["x"]), (1, g.open["y"]), (2, g.open["z"])):
            lo = c.narrow(axis + 2, 0, c.shape[axis + 2] - 1)
            hi = c.narrow(axis + 2, 1, c.shape[axis + 2] - 1)
            d = (hi - lo) * open_ * k
            c_new.narrow(axis + 2, 0, c.shape[axis + 2] - 1).add_(d)
            c_new.narrow(axis + 2, 1, c.shape[axis + 2] - 1).sub_(d)
        # Sources, relaxation, decay.
        c_new = c_new + dt * self.source / g.volume
        c_new = c_new + (self.relax_target - c_new) * (1 - torch.exp(-self.relax_rate * dt))
        c_new = c_new * torch.exp(-self.decay * dt).view(1, -1, 1, 1, 1)
        self.c = c_new * fl

    # --- queries --------------------------------------------------------------------------------

    def total(self) -> torch.Tensor:
        """Amount per world and species: [W, S]."""
        return (
            self.c.sum(_XYZ) * self.grid.volume
        )  # registry-ok: spatial axes of the [W, S, x, y, z] grid

    def sample(self, world: torch.Tensor, p: torch.Tensor) -> torch.Tensor:
        """Trilinear concentration at points p [P, 3] in worlds `world` [P] → [P, S]."""
        g = self.grid
        x = (p.double() - g._origin) / g.cell - 0.5  # in cell-centre index units
        i0 = torch.floor(x).long()
        t = (x - i0).unsqueeze(1)  # [P, 1, 3]
        idx = torch.minimum((i0.unsqueeze(1) + self._corners).clamp_min(0), g._hi)  # [P, 8, 3]
        f = torch.where(self._upper, t, 1 - t)  # per-axis weights [P, 8, 3]
        w = f[..., 0] * f[..., 1] * f[..., 2]  # [P, 8]
        vals = self.c[world.unsqueeze(1), :, idx[..., 0], idx[..., 1], idx[..., 2]]  # [P, 8, S]
        return (vals * w.unsqueeze(-1)).sum(1)

    def state_dict(self) -> dict[str, torch.Tensor]:
        return {
            "c": self.c,
            "source": self.source,
            "relax_target": self.relax_target,
            "relax_rate": self.relax_rate,
        }

    def load_state_dict(self, s: dict[str, torch.Tensor]) -> None:
        for k, v in s.items():
            setattr(self, k, v.to(self.grid.device))
