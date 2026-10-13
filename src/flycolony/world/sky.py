"""Sky, light and looming events (WORLD-R-030, -031, -034, -035).

- Illuminance follows the life clock: day and night levels, a photoperiod with lights-on at a
  registry hour, and cosine dawn/dusk ramps.
- The sun moves on a circular path through the light phase. Sky radiance per direction is a
  two-term gradient (elevation and angular distance to the sun), in three spectral channels
  (UV, blue, green), with a single-scattering Rayleigh polarization pattern.
- Looming events are dark spheres approaching a target point on a straight line; their angular
  size is 2·atan(r / d(t)). They start on command or at a natural rate drawn from the counter-based
  RNG, and are harmless unless predation is enabled (WORLD-OQ-06).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

from flycolony.engine.clock import HOURS_PER_DAY, SECONDS_PER_HOUR, Clock
from flycolony.registry import Registry

CHANNELS = ("uv", "blue", "green")
_MIN_PHOTOPERIOD_H = 1e-9  # registry-ok: guard against a zero photoperiod


@dataclass
class SkyParams:
    day_lux: float
    night_lux: float
    lights_on_hour: float
    photoperiod_h: float
    ramp_h: float
    spectrum_sky: tuple[float, float, float]
    spectrum_sun: tuple[float, float, float]
    sun_tilt_deg: float
    sky_zenith_gain: float
    sun_glow_gain: float
    sun_glow_width_deg: float
    max_polarization: float

    @classmethod
    def from_registry(cls, reg: Registry) -> SkyParams:
        g = reg.get
        return cls(
            day_lux=float(g("world.light.day_lux")),
            night_lux=float(g("world.light.night_lux")),
            lights_on_hour=float(g("world.light.lights_on_hour")),
            photoperiod_h=float(g("world.light.photoperiod_h")),
            ramp_h=float(g("world.light.ramp_h")),
            spectrum_sky=tuple(g("world.light.spectrum_sky")),
            spectrum_sun=tuple(g("world.light.spectrum_sun")),
            sun_tilt_deg=float(g("world.sky.sun_tilt_deg")),
            sky_zenith_gain=float(g("world.sky.zenith_gain")),
            sun_glow_gain=float(g("world.sky.sun_glow_gain")),
            sun_glow_width_deg=float(g("world.sky.sun_glow_width_deg")),
            max_polarization=float(g("world.sky.max_polarization")),
        )


class Sky:
    """Light state of one world group (shared by its worlds)."""

    def __init__(self, params: SkyParams):
        self.p = params

    def set_day_length(self, photoperiod_h: float) -> None:
        """Day length via the Control API (WORLD-R-034), applied at a step boundary."""
        if not 0 <= photoperiod_h <= 24:  # registry-ok: hours in a day
            raise ValueError("photoperiod must be within 0..24 h")
        self.p.photoperiod_h = photoperiod_h

    def light_fraction(self, hour: float) -> float:
        """0 at night, 1 in the day, cosine ramps of ramp_h centred on lights-on and lights-off."""
        p = self.p
        t = (hour - p.lights_on_hour) % HOURS_PER_DAY
        half = p.ramp_h / 2
        if p.ramp_h <= 0:
            return 1.0 if t < p.photoperiod_h else 0.0

        def ramp(x: float) -> float:  # 0 → 1 over [−half, +half]
            x = min(max((x + half) / p.ramp_h, 0.0), 1.0)
            return 0.5 - 0.5 * math.cos(math.pi * x)

        up = ramp(t if t < 12.0 else t - 24.0)  # registry-ok: half a day, wrap point
        down = ramp(t - p.photoperiod_h)
        return max(0.0, min(1.0, up - down))

    def illuminance(self, clock: Clock) -> float:
        f = self.light_fraction(clock.fly_hour_of_day)
        return self.p.night_lux + (self.p.day_lux - self.p.night_lux) * f

    def sun_direction(self, clock: Clock) -> tuple[float, float, float]:
        """Unit vector to the sun; the sun rises at lights-on in the east (+x) and sets in the west.

        Below the horizon at night (z < 0); the sky uses max(z, 0).
        """
        p = self.p
        phase = ((clock.fly_hour_of_day - p.lights_on_hour) % HOURS_PER_DAY) / max(
            p.photoperiod_h, _MIN_PHOTOPERIOD_H
        )  # registry-ok: hours in a day; guard against a zero photoperiod
        ang = math.pi * phase  # 0 at sunrise, π at sunset
        tilt = math.radians(p.sun_tilt_deg)
        x, z = math.cos(ang), math.sin(ang)
        return (x, -z * math.sin(tilt), z * math.cos(tilt))

    def radiance(self, dirs: torch.Tensor, clock: Clock) -> torch.Tensor:
        """Sky radiance [..., 3 channels] for unit view directions [..., 3]."""
        p = self.p
        lux = self.illuminance(clock)
        sun = torch.tensor(self.sun_direction(clock), dtype=dirs.dtype, device=dirs.device)
        elev = dirs[..., 2].clamp_min(0)
        cos_g = (dirs * sun).sum(-1).clamp(-1, 1)
        gamma = torch.arccos(cos_g)
        width = math.radians(p.sun_glow_width_deg)
        glow = p.sun_glow_gain * torch.exp(-((gamma / width) ** 2)) * float(sun[2] > 0)
        base = (1 + p.sky_zenith_gain * elev) / (1 + p.sky_zenith_gain)
        sky = torch.tensor(p.spectrum_sky, dtype=dirs.dtype, device=dirs.device)
        sunc = torch.tensor(p.spectrum_sun, dtype=dirs.dtype, device=dirs.device)
        return lux * (base.unsqueeze(-1) * sky + glow.unsqueeze(-1) * sunc)

    def polarization(self, dirs: torch.Tensor, clock: Clock) -> tuple[torch.Tensor, torch.Tensor]:
        """Single-scattering Rayleigh pattern: (e-vector unit [..., 3], degree [...])."""
        sun = torch.tensor(self.sun_direction(clock), dtype=dirs.dtype, device=dirs.device)
        e = torch.cross(dirs, sun.expand_as(dirs), dim=-1)
        n = e.norm(dim=-1, keepdim=True)
        e = e / n.clamp_min(torch.finfo(dirs.dtype).tiny)
        cos_g = (dirs * sun).sum(-1).clamp(-1, 1)
        degree = self.p.max_polarization * (1 - cos_g**2) / (1 + cos_g**2)
        return e, degree * float(sun[2] > 0)

    def state_dict(self) -> dict:
        return {"photoperiod_h": self.p.photoperiod_h}

    def load_state_dict(self, s: dict) -> None:
        self.p.photoperiod_h = float(s["photoperiod_h"])


# --- looming events ------------------------------------------------------------------------------


@dataclass
class LoomParams:
    radius_mm: float
    speed_mm_s: float
    start_distance_mm: float
    albedo: float
    natural_rate_per_fly_h: float
    predation: bool

    @classmethod
    def from_registry(cls, reg: Registry) -> LoomParams:
        g = reg.get
        return cls(
            radius_mm=float(g("world.looming.radius_mm")),
            speed_mm_s=float(g("world.looming.speed_mm_s")),
            start_distance_mm=float(g("world.looming.start_distance_mm")),
            albedo=float(g("world.looming.albedo")),
            natural_rate_per_fly_h=float(g("world.looming.natural_rate_per_fly_h")),
            predation=bool(g("world.looming.predation")),
        )

    @property
    def l_over_v_ms(self) -> float:
        return self.radius_mm / self.speed_mm_s * 1000.0  # registry-ok: s → ms


class Looming:
    """At most one active looming event per world: a dark sphere moving toward a target point.

    State per world: active, start time (neural s), unit direction from target to the start point,
    target point (mm), radius and speed. The sphere's centre is target + dir·d(t), with
    d(t) = d0 − v·(t − t0); the event ends at the projected collision (d = 0).
    """

    def __init__(self, n_worlds: int, params: LoomParams, device: torch.device):
        f64 = torch.float64
        self.p = params
        self.active = torch.zeros(n_worlds, dtype=torch.bool, device=device)
        self.t0 = torch.zeros(n_worlds, dtype=f64, device=device)
        self.dir = torch.zeros(n_worlds, 3, dtype=f64, device=device)  # registry-ok: state keys
        self.target = torch.zeros(n_worlds, 3, dtype=f64, device=device)  # registry-ok: state keys
        self.radius = torch.full((n_worlds,), params.radius_mm, dtype=f64, device=device)
        self.speed = torch.full((n_worlds,), params.speed_mm_s, dtype=f64, device=device)
        self.d0 = torch.full((n_worlds,), params.start_distance_mm, dtype=f64, device=device)

    def start(self, world: int, t_s: float, target, direction) -> None:
        """Start an event (world command). `direction` points from the target toward the start."""
        d = torch.as_tensor(direction, dtype=torch.float64, device=self.dir.device)
        self.dir[world] = d / d.norm()
        self.target[world] = torch.as_tensor(target, dtype=torch.float64, device=self.dir.device)
        self.t0[world] = t_s
        self.active[world] = True

    def collision_time(self) -> torch.Tensor:
        """Projected collision: the sphere's surface reaches the target point (d = r)."""
        return self.t0 + (self.d0 - self.radius) / self.speed

    def update(self, t_s: float) -> None:
        """End events whose projected collision has passed."""
        self.active &= torch.as_tensor(t_s, dtype=torch.float64) < self.collision_time()

    def spheres(self, t_s: float) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """(centres [W, 3], radii [W], active [W]) at neural time t_s."""
        d = (self.d0 - self.speed * (t_s - self.t0)).clamp_min(self.radius)
        return self.target + self.dir * d.unsqueeze(-1), self.radius, self.active

    def state_dict(self) -> dict[str, torch.Tensor]:
        return {
            k: getattr(self, k) for k in ("active", "t0", "dir", "target", "radius", "speed", "d0")
        }

    def load_state_dict(self, s: dict[str, torch.Tensor]) -> None:
        for k, v in s.items():
            setattr(self, k, v.to(self.active.device))


def hours_to_s(h: float) -> float:
    return h * SECONDS_PER_HOUR
