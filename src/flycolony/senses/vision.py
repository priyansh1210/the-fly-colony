"""Compound-eye vision: lattice, analytic ray casting, photoreceptor responses (SENSE-R-010..015).

- Each eye is a hexagonal lattice (flyvis extent → 721 columns) with inter-ommatidial angle Δφ,
  mapped to viewing directions by an azimuthal-equidistant projection around the eye's centre
  direction. Each ommatidium averages 7 rays over a Gaussian acceptance function (half-width Δρ).
- Rays are cast analytically from the eye positions: the arena (opaque textured floor; walls and
  ceiling opaque or transparent to the sky by material), food and water discs, other flies
  (spheres), looming spheres, and the sky (003 §4.3). No mesh, batched over flies.
- Radiance has three spectral channels (UV, blue, green). Photoreceptor classes weight them; the
  dorsal rim adds a polarization response from the sky e-vector.
- Transduction is log-compressive with adaptation: a steady component that grows with log
  intensity (so night reaches the brain) and a transient contrast component.
- Mapping to the template's photoreceptor neurons: in *full* mode every neuron has its column (from
  the FlyWire column map); in *luminance* mode (no column map) every photoreceptor of an eye and
  class gets that eye's mean response. The mode is reported with every gate (004 §7.4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import torch

from flycolony.body.body import BodyBatch
from flycolony.engine.clock import Clock
from flycolony.registry import Registry
from flycolony.senses.layout import SensoryLayout
from flycolony.world.geometry import CEILING, FLOOR
from flycolony.world.world import WorldGroup

N_CH = 3  # registry-ok: UV, blue, green
HEX_DIRS = 6  # registry-ok: neighbours on a hexagonal lattice
NO_HIT = float("inf")
DIM = 3  # registry-ok: 3D vectors
_RAY_AXIS = 3  # registry-ok: ray axis of [N, eye, omm, ray, ch]
_QUAD_4 = 4  # registry-ok: quadratic-formula constant
_TINY = 1e-30  # registry-ok: division guard
_BOX_WALLS = (2, 3, 4, 5)  # registry-ok: box wall face ids
_SPHERE_AXIS = -2  # registry-ok: sphere axis of [..., S, 3]
SQRT3_2 = math.sqrt(3) / 2  # registry-ok: hexagonal geometry


def hex_lattice(extent: int) -> np.ndarray:
    """(u, v) of a hexagonal lattice of radius `extent` (flyvis ordering by u then v)."""
    return np.array(
        [
            (u, v)
            for u in range(-extent, extent + 1)
            for v in range(-extent, extent + 1)
            if abs(u + v) <= extent
        ],
        dtype=np.int64,
    )


@dataclass
class VisionParams:
    extent: int
    dphi: float  # rad
    drho: float  # rad
    eye_azimuth: float  # rad, left eye centre (right = −)
    eye_elevation: float
    class_weights: np.ndarray  # [classes, 3]
    floor_albedo: float
    floor_contrast: float
    floor_period: float
    fly_albedo: float
    patch_albedo: float
    wall_transparent: bool
    abs_gain: float
    ref_lux: float
    contrast_gain: float
    adapt_tau_s: float
    max_mv: float
    min_mv: float
    pol_gain: float

    @classmethod
    def from_registry(cls, reg: Registry, classes: list[str]) -> VisionParams:
        g = lambda k: float(reg.get(f"senses.vision.{k}"))  # noqa: E731
        w = np.array([reg.get(f"senses.vision.weights.{c}") for c in classes], dtype=np.float64)
        return cls(
            extent=int(reg.get("senses.vision.lattice_extent")),
            dphi=math.radians(g("dphi_deg")),
            drho=math.radians(g("drho_deg")),
            eye_azimuth=math.radians(g("eye_azimuth_deg")),
            eye_elevation=math.radians(g("eye_elevation_deg")),
            class_weights=w,
            floor_albedo=g("floor_albedo"),
            floor_contrast=g("floor_contrast"),
            floor_period=g("floor_period_mm"),
            fly_albedo=g("fly_albedo"),
            patch_albedo=g("patch_albedo"),
            wall_transparent=bool(reg.get("senses.vision.walls_transparent")),
            abs_gain=g("abs_gain_mv"),
            ref_lux=g("ref_lux"),
            contrast_gain=g("contrast_gain_mv"),
            adapt_tau_s=g("adapt_tau_s"),
            max_mv=g("max_mv"),
            min_mv=g("min_mv"),
            pol_gain=g("pol_gain_mv"),
        )


class Eyes:
    """Viewing directions in the body frame for both eyes: [2, n_omm, n_rays, 3] and ray weights."""

    def __init__(self, p: VisionParams, device: torch.device):
        uv = hex_lattice(p.extent)
        self.uv = uv
        x = p.dphi * (uv[:, 0] + uv[:, 1] / 2)  # in-plane angular coordinates (rad)
        y = p.dphi * (uv[:, 1] * SQRT3_2)
        # 7 rays: centre + hexagon at Δρ/2, Gaussian weights of the acceptance function.
        ang = np.arange(HEX_DIRS) * (2 * math.pi / HEX_DIRS)
        off = np.concatenate([[[0.0, 0.0]], (p.drho / 2) * np.stack([np.cos(ang), np.sin(ang)], 1)])
        sigma = p.drho / (2 * math.sqrt(2 * math.log(2)))  # Δρ is the full width at half maximum
        w = np.exp(-(off**2).sum(1) / (2 * sigma**2))
        self.ray_w = torch.tensor(w / w.sum(), dtype=torch.float64, device=device)
        dirs = []
        for sign in (1.0, -1.0):  # left eye looks to +left, right eye mirrored
            ax = x[:, None] + off[None, :, 0]
            ay = y[:, None] + off[None, :, 1]
            dirs.append(self._project(ax * sign, ay, sign * p.eye_azimuth, p.eye_elevation))
        self.dirs = torch.tensor(np.stack(dirs), dtype=torch.float64, device=device)
        self.n = uv.shape[0]
        # Dorsal rim: the top rows of the lattice (highest elevation), registry-free fraction.
        self.elevation = torch.tensor(
            np.stack([np.arcsin(np.clip(d[:, 0, 2], -1, 1)) for d in dirs]), device=device
        )

    @staticmethod
    def _project(ax, ay, az0, el0) -> np.ndarray:
        """Azimuthal-equidistant projection around (az0, el0): body frame (fwd, left, up)."""
        c = np.array([math.cos(el0) * math.cos(az0), math.cos(el0) * math.sin(az0), math.sin(el0)])
        e1 = np.array([-math.sin(az0), math.cos(az0), 0.0])  # azimuth increases toward +left
        e2 = np.cross(c, e1)  # elevation tangent (up)
        theta = np.sqrt(ax**2 + ay**2)
        psi = np.arctan2(ay, ax)
        d = np.cos(theta)[..., None] * c + np.sin(theta)[..., None] * (
            np.cos(psi)[..., None] * e1 + np.sin(psi)[..., None] * e2
        )
        return d / np.linalg.norm(d, axis=-1, keepdims=True)


class Vision:
    """Renders both eyes of every fly and produces photoreceptor input (mV) for the layout."""

    def __init__(
        self,
        layout: SensoryLayout,
        reg: Registry,
        device: torch.device,
        columns: dict[int, int] | None = None,
    ):
        self.layout, self.device = layout, device
        self.p = VisionParams.from_registry(reg, layout.photo_classes)
        self.eyes = Eyes(self.p, device)
        self.w = torch.tensor(self.p.class_weights, dtype=torch.float64, device=device)
        self.dra = (
            layout.photo_classes.index("dorsal_rim") if "dorsal_rim" in layout.photo_classes else -1
        )
        # Neuron → (eye, class, ommatidium or −1 for the eye mean).
        omm = np.full(layout.n_photo, -1, dtype=np.int64)
        if columns:
            for i, nid in enumerate(layout.photo_ids.tolist()):
                omm[i] = columns.get(nid, -1)
        self.mode = "full" if columns else "luminance"
        self.coverage = float((omm >= 0).mean()) if layout.n_photo else 0.0
        self.n_omm = torch.from_numpy(omm).to(device)
        self.n_eye = torch.from_numpy(layout.photo_side).to(device)
        self.n_cls = torch.from_numpy(layout.photo_class).to(device)
        self.adapt: torch.Tensor | None = None  # [N, 2, n_omm, classes] log-intensity
        self.last_frame: torch.Tensor | None = None

    # --- rendering ---------------------------------------------------------------------------------

    def render(self, world: WorldGroup, body: BodyBatch, clock: Clock) -> torch.Tensor:
        """Radiance per fly, eye, ommatidium and channel: [N, 2, n_omm, 3]."""
        sites = body.sites()
        n = body.n
        frame = torch.stack([body.fwd, body.left, body.up], -1)  # [N, 3, 3] columns
        d = torch.einsum("nij,eorj->neori", frame, self.eyes.dirs)  # [N, 2, O, R, 3]
        origin = torch.stack([sites["eye_l"], sites["eye_r"]], 1)  # [N, 2, 3]
        o = origin[:, :, None, None, :].expand_as(d)
        lux = world.sky.illuminance(clock)
        rad = world.sky.radiance(d, clock)  # sky by default
        t_best = torch.full(d.shape[:-1], NO_HIT, dtype=torch.float64, device=self.device)
        # Arena: the first face the ray leaves through.
        t_face, face = self._arena_exit(world, o, d)
        opaque = torch.ones_like(face, dtype=torch.bool)
        if self.p.wall_transparent:
            opaque = face == FLOOR
        hit_pt = o + d * t_face.unsqueeze(-1)
        alb = self._floor_albedo(hit_pt)
        surf = (
            lux
            * alb.unsqueeze(-1)
            * torch.tensor(world.sky.p.spectrum_sky, dtype=torch.float64, device=self.device)
        )
        rad = torch.where(opaque.unsqueeze(-1), surf, rad)
        t_best = torch.where(opaque, t_face, t_best)
        # Discs (food, water) on the floor at their drop height.
        t_disc = self._discs(world, body, o, d)
        rad, t_best = self._take(rad, t_best, t_disc, lux * self.p.patch_albedo, world)
        # Other flies (spheres; a fly never sees itself).
        t_fly = self._flies(body, o, d)
        rad, t_best = self._take(rad, t_best, t_fly, lux * self.p.fly_albedo, world)
        # Looming spheres (may be outside a transparent arena).
        t_loom = self._looming(world, body, o, d, clock)
        rad, t_best = self._take(rad, t_best, t_loom, lux * world.looming.p.albedo, world)
        del n
        return (rad * self.eyes.ray_w.view(1, 1, 1, -1, 1)).sum(_RAY_AXIS)  # [N, 2, O, 3]

    def _take(self, rad, t_best, t_new, level: float, world):
        closer = t_new < t_best
        col = level * torch.tensor(
            world.sky.p.spectrum_sky, dtype=torch.float64, device=self.device
        )
        return torch.where(closer.unsqueeze(-1), col.expand_as(rad), rad), torch.minimum(
            t_best, t_new
        )

    def _arena_exit(self, world: WorldGroup, o, d):
        a = world.spec.arena
        big = torch.full(d.shape[:-1], NO_HIT, dtype=torch.float64, device=self.device)
        ts, fs = [], []
        dz = d[..., 2]
        t_floor = torch.where(dz < 0, -o[..., 2] / dz, big)
        t_ceil = torch.where(dz > 0, (a.height - o[..., 2]) / dz, big)
        ts += [t_floor, t_ceil]
        fs += [FLOOR, CEILING]
        if a.kind == "cylinder":
            ox, oy, dx, dy = o[..., 0], o[..., 1], d[..., 0], d[..., 1]
            qa = dx * dx + dy * dy
            qb = 2 * (ox * dx + oy * dy)
            qc = ox * ox + oy * oy - a.radius**2
            disc = (qb * qb - _QUAD_4 * qa * qc).clamp_min(0)
            t_wall = torch.where(qa > 0, (-qb + disc.sqrt()) / (2 * qa).clamp_min(_TINY), big)
            ts.append(t_wall)
            fs.append(2)  # registry-ok: the cylinder's wall face id
        else:
            for fid, axis, val in zip(
                _BOX_WALLS, (0, 0, 1, 1), (0.0, a.size_x, 0.0, a.size_y), strict=True
            ):
                comp = d[..., axis]
                ok = (comp < 0) if val == 0.0 else (comp > 0)
                ts.append(torch.where(ok, (val - o[..., axis]) / comp, big))
                fs.append(fid)
        stack = torch.stack(ts, -1)
        t, idx = stack.min(-1)
        face = torch.tensor(fs, device=self.device)[idx]
        return t, face

    def _floor_albedo(self, p: torch.Tensor) -> torch.Tensor:
        k = 2 * math.pi / self.p.floor_period
        chk = torch.sign(torch.sin(k * p[..., 0]) * torch.sin(k * p[..., 1]))
        return self.p.floor_albedo * (1 + self.p.floor_contrast * chk)

    def _discs(self, world: WorldGroup, body: BodyBatch, o, d) -> torch.Tensor:
        pt = world.patches
        w = body.world
        cen, rad, hgt = pt.center[w], pt.radius[w], pt.height[w]  # [N, K, 2], [N, K]
        act = pt.active[w] & (pt.stage[w] != 4)  # registry-ok: stage index of "depleted"
        dz = d[..., 2].unsqueeze(-1)  # [N, E, O, R, 1]
        oz = o[..., 2].unsqueeze(-1)
        h = hgt.view(hgt.shape[0], 1, 1, 1, -1)
        t = torch.where(dz < 0, (h - oz) / dz, NO_HIT)
        hx = o[..., 0].unsqueeze(-1) + d[..., 0].unsqueeze(-1) * t
        hy = o[..., 1].unsqueeze(-1) + d[..., 1].unsqueeze(-1) * t
        cx = cen[..., 0].view(cen.shape[0], 1, 1, 1, -1)
        cy = cen[..., 1].view(cen.shape[0], 1, 1, 1, -1)
        inside = (hx - cx) ** 2 + (hy - cy) ** 2 <= rad.view(rad.shape[0], 1, 1, 1, -1) ** 2
        ok = inside & act.view(act.shape[0], 1, 1, 1, -1) & (t > 0)
        return torch.where(ok, t, torch.full_like(t, NO_HIT)).min(-1).values

    def _spheres(self, o, d, centres, radius, valid) -> torch.Tensor:
        """Nearest positive hit of rays [N, E, O, R] with spheres [N, S] → [N, E, O, R]."""
        oc = o.unsqueeze(_SPHERE_AXIS) - centres.view(centres.shape[0], 1, 1, 1, -1, DIM)
        b = (oc * d.unsqueeze(_SPHERE_AXIS)).sum(-1)
        c = (oc * oc).sum(-1) - radius.view(radius.shape[0], 1, 1, 1, -1) ** 2
        disc = b * b - c
        t = -b - disc.clamp_min(0).sqrt()
        t = torch.where(
            c < 0, torch.zeros_like(t), t
        )  # ray starts inside: everything is the sphere
        ok = (disc >= 0) & (t >= 0) & valid.view(valid.shape[0], 1, 1, 1, -1)
        return torch.where(ok, t, torch.full_like(t, NO_HIT)).min(-1).values

    def _flies(self, body: BodyBatch, o, d) -> torch.Tensor:
        n = body.n
        if n < 2:
            return torch.full(d.shape[:-1], NO_HIT, dtype=torch.float64, device=self.device)
        centre = body.sites()["center"]
        cen = centre.unsqueeze(0).expand(n, n, DIM)
        same = (body.world[:, None] == body.world[None, :]) & ~torch.eye(
            n, dtype=torch.bool, device=self.device
        )
        r = torch.full((n, n), body.p.radius, dtype=torch.float64, device=self.device)
        return self._spheres(o, d, cen, r, same)

    def _looming(self, world, body, o, d, clock) -> torch.Tensor:
        c, r, act = world.looming.spheres(clock.sim_ts)
        w = body.world
        return self._spheres(o, d, c[w].unsqueeze(1), r[w].unsqueeze(1), act[w].unsqueeze(1))

    # --- transduction ---------------------------------------------------------------------------------

    def photoreceptors(
        self, world: WorldGroup, body: BodyBatch, clock: Clock, dt: float
    ) -> torch.Tensor:
        """Photoreceptor input (mV) for every neuron of the layout: [N, n_photo]."""
        rad = self.render(world, body, clock)  # [N, 2, O, 3]
        self.last_frame = rad
        cls = torch.einsum("neoc,kc->neok", rad, self.w)  # [N, 2, O, classes]
        if self.dra >= 0:
            sites = body.sites()
            frame = torch.stack([body.fwd, body.left, body.up], -1)
            d = torch.einsum("nij,eoj->neoi", frame, self.eyes.dirs[:, :, 0])
            e, deg = world.sky.polarization(d, clock)
            # Polarization response: degree × alignment of the e-vector with the DRA analyser
            # axis (the body's left axis here: one analyser per eye, a Phase-2 simplification).
            align = (e * body.left[:, None, None, :]).sum(-1) ** 2
            cls[..., self.dra] = (
                cls[..., self.dra] * (1 + self.p.pol_gain * deg * align) * (d[..., 2] > 0)
            )
            del sites
        log_i = torch.log(cls.clamp_min(1e-9) / self.p.ref_lux)  # registry-ok: log floor
        if self.adapt is None or self.adapt.shape != log_i.shape:
            self.adapt = log_i.clone()
        a = math.exp(-dt / self.p.adapt_tau_s)
        self.adapt = self.adapt * a + log_i * (1 - a)
        # Steady depolarisation grows with log intensity above the night reference (never below
        # rest); the transient contrast term rides on top.
        mv = self.p.abs_gain * log_i.clamp_min(0) + self.p.contrast_gain * (log_i - self.adapt)
        mv = mv.clamp(self.p.min_mv, self.p.max_mv)  # [N, 2, O, K]
        return self._to_neurons(mv)

    def _to_neurons(self, mv: torch.Tensor) -> torch.Tensor:
        mean = mv.mean(2)  # [N, 2, K]
        per_eye = mean[:, self.n_eye, self.n_cls]  # [N, n_photo]
        if self.mode == "luminance":
            return per_eye.float()
        o = self.n_omm.clamp_min(0)
        full = mv[:, self.n_eye, o, self.n_cls]
        return torch.where(self.n_omm >= 0, full, per_eye).float()

    def preview(self, fly: int) -> dict:
        """Read-only fly-eye preview (SENSE-R-015): the last rendered frame of one fly."""
        if self.last_frame is None:
            raise RuntimeError("no frame rendered yet")
        return {"radiance": self.last_frame[fly].detach().cpu().clone(), "lattice_uv": self.eyes.uv}
