"""The single clock service (CLOCK-R-001, -003, -004, -010; spec 009, Phase-2 subset).

Neural time advances only by engine steps (an integer tick count × dt). The life clock is
integrated every step as Δlife = Δneural × 86400 / D(t), so it stays continuous when D changes.
Every life-clock process reads time from here; modules never keep their own time.
"""

from __future__ import annotations

from dataclasses import dataclass

from flycolony.registry import Registry

SECONDS_PER_DAY = 86400.0  # registry-ok: definition of a day
SECONDS_PER_HOUR = 3600.0  # registry-ok: definition of an hour
HOURS_PER_DAY = 24.0  # registry-ok: definition of a day
SECONDS_PER_MINUTE = 60.0  # registry-ok: definition of a minute
MS_PER_S = 1000.0  # registry-ok: unit conversion


class ClockError(ValueError):
    """An out-of-range clock setting."""


@dataclass
class Clock:
    """Tick-exact neural time plus the integrated life clock (both start at genesis)."""

    dt_ms: float
    fly_day_neural_s: float
    genesis_fly_s: float  # life-clock seconds after midnight of Day 1 at genesis
    d_range: tuple[float, float]
    tick: int = 0
    life_s: float = 0.0  # life-clock seconds since genesis

    @classmethod
    def build(cls, dt_ms: float, fly_day_neural_s: float, reg: Registry) -> Clock:
        lo, hi = reg.get("clock.fly_day_neural_s_range")
        c = cls(
            dt_ms=dt_ms,
            fly_day_neural_s=fly_day_neural_s,
            genesis_fly_s=float(reg.get("clock.genesis_hour")) * SECONDS_PER_HOUR,
            d_range=(float(lo), float(hi)),
        )
        c._check_d(fly_day_neural_s)
        return c

    def _check_d(self, d: float) -> None:
        lo, hi = self.d_range
        if not lo <= d <= hi:
            raise ClockError(f"D = {d} neural s per fly day is outside [{lo}, {hi}]")

    @property
    def compression(self) -> float:
        """Life-clock seconds per neural second (86400 / D)."""
        return SECONDS_PER_DAY / self.fly_day_neural_s

    def advance(self, steps: int = 1) -> None:
        """Advance by whole engine steps (the only way time moves)."""
        self.tick += steps
        self.life_s += steps * self.dt_ms / MS_PER_S * self.compression

    def set_fly_day(self, fly_day_neural_s: float) -> None:
        """Change D at a step boundary (CLOCK-R-005); the life clock stays continuous."""
        self._check_d(fly_day_neural_s)
        self.fly_day_neural_s = fly_day_neural_s

    # --- timestamps (CLOCK-R-004) ------------------------------------------------------------

    @property
    def sim_ts(self) -> float:
        """Neural seconds since genesis, tick-exact."""
        return self.tick * self.dt_ms / MS_PER_S

    @property
    def fly_s(self) -> float:
        """Life-clock seconds since midnight of Day 1."""
        return self.genesis_fly_s + self.life_s

    @property
    def fly_hour_of_day(self) -> float:
        return (self.fly_s % SECONDS_PER_DAY) / SECONDS_PER_HOUR

    @property
    def fly_ts(self) -> str:
        """'Day N, HH:MM:SS' with genesis at Day 1, 06:00:00 (registry genesis hour)."""
        total = int(self.fly_s)
        day, rem = divmod(total, int(SECONDS_PER_DAY))
        h, rem = divmod(rem, int(SECONDS_PER_HOUR))
        m, s = divmod(rem, int(SECONDS_PER_MINUTE))
        return f"Day {day + 1}, {h:02d}:{m:02d}:{s:02d}"

    def neural_s_for_fly_s(self, fly_seconds: float) -> float:
        """Neural seconds that span `fly_seconds` of life-clock time at the current D."""
        return fly_seconds / self.compression

    # --- checkpoint ---------------------------------------------------------------------------

    def state_dict(self) -> dict:
        return {
            "tick": self.tick,
            "life_s": self.life_s,
            "dt_ms": self.dt_ms,
            "fly_day_neural_s": self.fly_day_neural_s,
        }

    def load_state_dict(self, s: dict) -> None:
        if s["dt_ms"] != self.dt_ms:
            raise ClockError(f"checkpoint dt {s['dt_ms']} ms != engine dt {self.dt_ms} ms")
        self.tick, self.life_s = int(s["tick"]), float(s["life_s"])
        self.set_fly_day(float(s["fly_day_neural_s"]))
