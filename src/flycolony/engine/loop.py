"""The closed sense → brain → body loop for one template and one world group (005 M6).

Every brain step (dt) the components due on the integer schedule (BRAIN-R-023) run in a fixed
order:

1. world fields, entities and events (`fields`);
2. vision → photoreceptor input (`vision`), other senses → sensory rates (`senses`), handed to the
   brain together;
3. one brain step;
4. motor readout → body physics → contacts → physiology → drop depletion (`physics`);
5. body → brain routes such as sleep pressure (`physio`);
6. the clock advances by one tick.

Nothing else moves a body or writes a brain: the loop only routes data between the layers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import torch

from flycolony.body.body import GROUNDED, BodyBatch, BodyParams
from flycolony.brain.build import setup_brain
from flycolony.brain.engine import FlyBrainSpec
from flycolony.config.schemas import ColonyConfig
from flycolony.connectome.template import BrainTemplate
from flycolony.engine.clock import MS_PER_S, Clock
from flycolony.motor.readout import MotorBatch, MotorOutput, load_primitives, split_groups
from flycolony.physiology.minimal import PhysioBatch, PhysioParams
from flycolony.registry import Registry
from flycolony.senses.layout import build_layout
from flycolony.senses.senses import SenseBatch
from flycolony.senses.vision import Vision
from flycolony.world.entities import TASTANTS
from flycolony.world.world import WorldGroup

SUCROSE = TASTANTS.index("sucrose")


@dataclass
class FlyStart:
    fly_id: str
    seed: int
    world: int
    xy: tuple[float, float]
    heading: float
    energy_frac: float = 1.0
    sleep_pressure: float = 0.0


class ClosedLoop:
    def __init__(
        self,
        template: BrainTemplate,
        world: WorldGroup,
        cfg: ColonyConfig,
        reg: Registry,
        device: torch.device,
        *,
        columns: dict[int, int] | None = None,
        motor_cls: type = MotorBatch,
    ):
        self.template, self.world, self.reg, self.device = template, world, reg, device
        table = load_primitives()
        self.setup = setup_brain(template, device, cfg, reg, split_sides=split_groups(table))
        self.brain = self.setup.new_batch()
        self.schedule = self.setup.schedule
        self.dt_ms = self.setup.dt
        self.clock = Clock.build(self.dt_ms, cfg.clock.fly_day_neural_s, reg)
        self.layout = build_layout(template)
        self.brain.attach_senses(self.layout.sensory_ids, self.layout.photo_ids)
        self.senses = SenseBatch(self.layout, reg, device)
        self.vision = Vision(self.layout, reg, device, columns=columns)
        self.bodies = BodyBatch(world.spec.arena, BodyParams.from_registry(reg), device)
        phys_ms = self.schedule.every["physics"] * self.dt_ms
        self.motor = motor_cls(
            self.brain.group_names, self.setup.output_groups, reg, phys_ms, device, table
        )
        self.brain.taps.append(self.motor.tap)
        self.physio = PhysioBatch(PhysioParams.from_registry(reg), device)
        self.move_threshold = float(reg.get("life.sleep.move_threshold"))
        self._photo: torch.Tensor | None = None
        self.last_motor: MotorOutput | None = None
        self.observers: list[Callable[[ClosedLoop], None]] = []  # called after each physics step

    # --- flies -------------------------------------------------------------------------------------

    def add(self, start: FlyStart) -> None:
        self.brain.add(FlyBrainSpec(start.fly_id, start.seed))
        self.bodies.add(start.fly_id, start.world, start.xy, start.heading)
        self.physio.add(start.energy_frac, start.sleep_pressure, self.clock.life_s)
        if self.brain.fly_ids != self.bodies.ids:
            raise RuntimeError("brain and body batches are out of step")

    @property
    def n(self) -> int:
        return self.bodies.n

    # --- stepping ------------------------------------------------------------------------------------

    def step(self) -> None:
        due = set(self.schedule.due(self.clock.tick))
        ms = lambda k: self.schedule.every[k] * self.dt_ms  # noqa: E731
        if "fields" in due:
            self.world.step(self.clock, ms("fields"))
        if "vision" in due:
            self._photo = self.vision.photoreceptors(
                self.world, self.bodies, self.clock, ms("vision") / MS_PER_S
            )
        if "senses" in due:
            intero = {"physiology.energy_deficit": self.physio.deficit}
            rates = self.senses.step(self.world, self.bodies, ms("senses") / MS_PER_S, intero)
            self.brain.set_senses(rates, self._photo)
        self.brain.step()
        if "physics" in due:
            self._physics(ms("physics") / MS_PER_S)
        if "physio" in due:
            self._routes()
        self.clock.advance(1)

    def run(self, steps: int) -> None:
        for _ in range(steps):
            self.step()

    def run_for(self, seconds: float) -> None:
        self.run(round(seconds * MS_PER_S / self.dt_ms))

    def _physics(self, dt: float) -> None:
        out = self.motor.read(self.brain.rates)
        self.last_motor = out
        wind = self.world.wind_at(self.bodies.world, self.bodies.sites()["center"])
        self.bodies.step(out.commands, dt, wind)
        # Contacts → ingestion (labellum in a drop, proboscis extended: biomechanical constraint).
        lab = self.bodies.sites()["labellum"]
        slot = self.world.patches.contains(self.bodies.world, lab)
        comp = self.world.composition()[self.bodies.world, slot.clamp_min(0)]
        sucrose = torch.where(slot >= 0, comp[:, SUCROSE], torch.zeros_like(comp[:, SUCROSE]))
        can = ((slot >= 0) & (self.bodies.proboscis >= self.motor.ingest_min_extension)).double()
        quiet = (
            (self.bodies.mode == GROUNDED)
            & (self.bodies.speed.abs() < self.move_threshold)
            & (self.bodies.yaw_rate.abs() < self.move_threshold)
        )
        want = self.physio.intake(self.clock, dt, out.pump, can)
        if bool((want > 0).any()):
            taken = self.world.patches.ingest(self.bodies.world, slot, want)
        else:
            taken = torch.zeros_like(want)
        self.physio.step(self.clock, dt, out.effort, quiet, taken, sucrose)
        for obs in self.observers:
            obs(self)

    def _routes(self) -> None:
        mod = self.brain.modulation
        if mod is None:
            return
        for i, fid in enumerate(self.brain.fly_ids):
            mod.apply_route(fid, "sleep_pressure", float(self.physio.pressure[i]))
