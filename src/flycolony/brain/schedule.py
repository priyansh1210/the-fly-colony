"""Fixed integer-ratio schedule of brain, physics, senses and vision (BRAIN-R-023)."""

from __future__ import annotations

from dataclasses import dataclass

# A period counts as a whole number of steps when it is within this many steps of one.
_TOLERANCE = 1e-9  # registry-ok: floating-point tolerance for ms / dt


class ScheduleError(ValueError):
    """A period is not a whole number of brain steps."""


@dataclass(frozen=True)
class Schedule:
    dt_ms: float
    every: dict[str, int]  # component -> period in brain steps

    @classmethod
    def build(cls, dt_ms: float, periods_ms: dict[str, float]) -> Schedule:
        every = {}
        for name, period in sorted(periods_ms.items()):
            ratio = period / dt_ms
            steps = round(ratio)
            if steps < 1 or abs(ratio - steps) > _TOLERANCE * max(1.0, ratio):
                raise ScheduleError(
                    f"{name}: period {period} ms is not a whole number of {dt_ms} ms brain steps"
                )
            every[name] = steps
        return cls(dt_ms, every)

    def due(self, step: int) -> list[str]:
        """Components that run at this brain step (all of them at step 0)."""
        return [name for name, k in self.every.items() if step % k == 0]

    def snapshot(self) -> dict:
        """Part of the config snapshot."""
        return {"brain_dt_ms": self.dt_ms, "every_steps": dict(self.every)}
