# 003 — Body & World: Design (Phase 2 scope)

| Field | Value |
|---|---|
| Status | Phase 2 design, 2026-10-13 |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |

This design covers what Phase 2 needs: one embodied fly closing the sense → brain → body loop, plus the emergence-gate arenas. Food lifecycle beyond the basic stages, the nursery and life-cycle entities (Phases 4–5), near-field sound and cuticular hydrocarbons (Phase 5), and the chamber DSL (Phase 7) are scheduled in [tasks.md](tasks.md). Their interfaces are reserved here so that later phases add to the code rather than replace it.

## 1. Modules

```
src/flycolony/world/
  geometry.py   arenas: dome cylinder, box/tube chambers; surfaces and material properties
  fields.py     scalar transport on a 3D grid (odor species, temperature, humidity); wind solver
  sky.py        light ramp from the life clock, sun position, sky gradient, polarization, looming events
  entities.py   food patches (stages, composition, emission), water springs
  world.py      WorldGroup: batched worlds of identical geometry; step, serialize, restore
src/flycolony/body/
  body.py       BodyBatch: state, walking on surfaces, flight, contacts, coupling hook, injury hook
  contacts.py   contact-site positions, surface/food contacts, fly-fly contacts
src/flycolony/engine/
  clock.py      neural time and the life clock (CLOCK-R-001, -003, -004, -010)
  loop.py       the closed loop: brain ↔ senses ↔ motor ↔ body ↔ world on the multi-rate schedule
```

## 2. Worlds and batching (WORLD-R-001, -002, BODY-R-007)

- **`WorldGroup`.** It holds `W` worlds of identical geometry as tensors with a leading world dimension.
  - The Colony Dome is a group with `W = 1`.
  - The emergence arenas are groups with `W` = trials in a batch, so 50 trials run as one batched step.
  - Each world is closed: no field, contact or ray crosses the world index.
  - Every fly carries a `world` index, and every lookup is gathered by it (WORLD-R-001).
- **Units.** Millimetres, seconds of neural time, °C, relative humidity in [0, 1]. Concentrations are in mol/m³ (odor) and mol/L (tastants).
- **Determinism (WORLD-R-002, BODY-R-007).** The step uses no floating-point atomics:
  - Field updates are stencil gathers.
  - Source injection and contact sums use sorted segment sums, the same scheme as the brain's integer sums where order could vary.
  - Random events (looming at a natural rate) use the counter-based RNG of 002 (`brain/rng.py`), with a world stream id.
- **Schedule.** The world reuses the integer schedule of BRAIN-R-023 with periods in `colony.yaml`:

  | Component | Period |
  |---|---|
  | `physics` (body) | 0.5 ms |
  | `senses` (non-visual) | 1 ms |
  | `vision` | 10 ms |
  | `fields` (new) | 10 ms |
  | `sky` (new) | 10 ms |

## 3. Geometry and surfaces (WORLD-R-010..012)

- **Analytic primitives.** Arenas are built from analytic primitives, so ray casting and surface walking need no mesh:
  - `cylinder` (dome: radius 250 mm, height 300 mm);
  - `box` (chambers, gate arenas);
  - `disc` (food and water on a surface);
  - `sphere` and `capsule` (fruit, perches; Phase 4).
- **Surface table.** Every primitive face is one row: kind, parameters, `walkable`, `graspable`, `substrate` id and `texture` id (a procedural pattern with contrast in the registry).
- **Zones (WORLD-R-011).** Zones are named regions (cylinders or boxes) in `colony.yaml` with physical properties only: substrate, temperature or humidity source, vent. They never act on a fly; they only parameterise surfaces and field sources.

## 4. Fields

### 4.1 Grid and transport (WORLD-R-040, WORLD-OQ-01)

- **Grid.** One cell-centred grid per world group. Cell size: 5 mm in the dome, 2.5 mm in gate arenas (registry `world.grid.cell_mm_dome` / `_chamber`). The dome grid is 100 × 100 × 60 cells.
- **Species.** Every grid holds S scalar species:
  - 12 odorants (registry `world.odor.species`): ethanol, acetic acid, ethyl acetate, CO₂, geosmin, cVA, apple-cider-vinegar volatiles (acetoin, 2-phenylethanol, isoamyl acetate), methyl salicylate (bitter-plant cue), benzaldehyde (aversive), ammonia;
  - temperature;
  - humidity.
- **Memory.** About 14 × 600k × 4 B ≈ 34 MB per dome.
- **Transport.** Finite-volume, conservative, deterministic. Each field step applies:
  1. **Advection.** First-order upwind fluxes on cell faces from the face-normal wind velocity. The flux leaving one cell enters its neighbour exactly, so mass is conserved apart from decay and open boundaries (WORLD-AC-02).
  2. **Diffusion.** Explicit 7-point Laplacian with a per-species coefficient (registry, e.g. 1e-5 m²/s for small odorants in air).
  3. **Decay.** Exponential, per species (registry).
  4. **Sources.** Added as amounts per step at their cells. Temperature and humidity sources relax their cells toward a set value with a time constant (registry), and set-point changes ramp at the minimum ramp rate (WORLD-R-032).
- **Boundaries.** Walls are no-flux. Vents are inflow or outflow faces, where outflow removes species by the advective flux.
- **Stability.** The field step is sub-cycled so that CFL ≤ 0.5 and the diffusion number ≤ 1/6. Construction checks both and raises if a registry change breaks them.

### 4.2 Wind (WORLD-R-033)

- **Potential flow.** Steady-state wind is incompressible potential flow: ∇²φ = 0 with Neumann conditions (the normal velocity is set on vent faces, zero on walls), and **u** = ∇φ.
  - Solved by conjugate gradient on the grid when vents change: once at build, then on a vent command at a step boundary. A fixed iteration cap and tolerance keep it deterministic.
  - The face velocities used by the transport are divergence-free to solver tolerance, which keeps the odor scheme conservative.
- **Body wind.** Flies sample wind by trilinear interpolation at a point (senses, flight drag).

### 4.3 Sky and light (WORLD-R-030, -031, -034, -035)

- **Light ramp.** Illuminance follows the life clock: day level, night level, photoperiod, and a dawn/dusk cosine ramp of `world.light.ramp_h` fly hours (all registry).
  - Day length can be set through a Control API command (stored in the world state, applied at a step boundary).
  - The sky's spectral weights for UV/blue/green come from the registry.
- **Sun and sky.** The sun's azimuth and elevation come from fly time of day: a simple circular path with registry latitude-like tilt. Sky luminance is a function of elevation and angular distance to the sun (a two-term gradient, registry).
- **Polarization.** The e-vector at each sky direction is perpendicular to the plane through the sun, observer and sky point (single-scattering Rayleigh). The degree of polarization is max·sin²γ, where γ is the angular distance to the sun.
- **Dome walls** are transparent to sky light (the dome is a mesh enclosure). The floor and walls carry their textures, lit by the current illuminance.
- **Looming events.**
  - A looming event is a dark disk of radius `r` approaching a target fly along a straight path at speed `v` from a start distance. It is rendered in that world's sky.
  - Events start at a natural random rate (registry; 0 by default in the dome) or on a world command.
  - The event state is the start time, direction, r/v and target; its angular size follows θ(t) = 2·atan(r / d(t)).
  - Harmless unless `world.looming.predation` is enabled (WORLD-OQ-06).

## 5. Entities (Phase-2 subset)

- **Food patches (WORLD-R-020, -021, -025, -026).** Discs on surfaces, each with a drop height (the liquid layer the labellum and tarsi can touch).
  - **Stage machine:** unripe → ripe → fermenting → rotting → depleted. Durations are in life-clock time (registry).
  - **Composition per stage** (registry): sucrose, protein, water fraction, ethanol, optional bitter (denatonium-equivalent) and toxic compound.
  - **Emission:** each stage has an odor emission profile per species (registry).
  - **Depletion:** ingested volume (reported by physiology) is removed exactly.
  - **New patches** ripen in place from a small, low-odor state over the registry ramp.
  - **Yeast growth** (WORLD-R-022) is a scalar on fermenting patches that raises protein (Phase 4 task; the field is reserved now).
- **Water springs (WORLD-R-023)** are discs with water composition and a humidity source.
- **Test media.** Gate arenas use fixed-composition drops (sucrose, sucrose + bitter, water) with stage `ripe` and no ripening: a substrate type, not a scripted stimulus.

## 6. Body (ColonyBody v1)

### 6.1 State (BODY-R-001)

`BodyBatch` holds one row per fly, as tensors:

| Group | Fields |
|---|---|
| Pose | position (3); orthonormal frame (forward, left, up); linear velocity (3); yaw rate |
| Mode | `grounded` / `airborne` / `coupled`; surface id and surface coordinates when grounded |
| Appendages | proboscis extension ∈ [0, 1]; wing angles L/R; wing vibration amplitude and frequency; abdomen bend; ovipositor extension; vaginal-plate state |
| Physical | size and mass (genome × larval nutrition; defaults for Phase 2); injury points |
| Ballistic timers | escape jump, lunge, egg deposition (MOTOR-R-002 exceptions) |

### 6.2 Walking (BODY-R-002)

- **Kinematic walking on surfaces.** The motor layer gives a forward speed command (signed) and a turning rate. Each physics step, the body moves along its surface in the tangent plane.
  - **Edges.** On the cylinder, the floor–wall and wall–ceiling edges are crossed by rotating the frame about the edge line: the fly walks up the wall.
  - **Limits.** Speed is limited by `body.walk.max_speed_mm_s` (registry, 20 mm/s) × stamina factor (1 until 006), and backward by `max_back_speed`.
  - **Adhesion.** Adhesion holds on every walkable surface. Ceiling walking is allowed, and the legs' grip limit is a registry value for future slipping.
- **Collisions.**
  - Fly–fly: discs of body radius on the same surface, resolved by a symmetric positional correction (deterministic pairwise sum over a cell list).
  - Arena: clamped to the surface bounds.

### 6.3 Flight (BODY-R-003)

- **Model.** A point mass with heading. The motor layer gives thrust, yaw rate and pitch commands.
  - Gravity and linear drag act against the air velocity relative to the local wind (WORLD-R-033).
  - Speed caps are in the registry.
- **Takeoff.** Voluntary takeoff sets airborne mode with an upward velocity.
  - The **escape jump** is ballistic: an impulse along `(forward·cos α + up·sin α)` with registry speed and angle, for the registry jump duration, after which the body is airborne.
- **Landing.** Contact with a graspable surface while airborne lands the fly on it, whether or not the landing primitive is active.
  - With landing extension, the impact speed limit is higher; above the limit, injury points accrue (BODY-R-006).
  - With no thrust, airborne flies glide down under drag and land on the floor.

### 6.4 Contacts (BODY-R-004, -009)

- **Contact sites.** Site positions come from the pose and body size: foreleg, midleg and hindleg groups L/R; proboscis tip (labellum: head + extension × proboscis length along `forward·cos β − up·sin β`); head; wings; abdomen tip.
- **Each physics step computes:**
  - Site ↔ surface contact. Tarsi are in contact when grounded.
  - Site ↔ drop contact. A site inside a food or water disc's drop volume touches that drop's composition.
  - Fly ↔ fly contacts, with site pairs and impulses.
- **Output.** Contacts are a structured tensor list per step. They feed senses (004), physiology (ingestion) and the Observation Stream.
- **Egg deposition (BODY-R-009)** is a Phase-5 task. The ovipositor contact site exists now.

### 6.5 Coupling and injury (BODY-R-005, -006)

- The coupling rule is a pure function of the two flies' primitive outputs and genital contact, so the "two brains" condition holds by construction. Implemented with tests in Phase 5; the mode exists now.
- Injury points from impacts above `body.injury.impact_threshold` are reported to physiology.

### 6.6 No self-motion (BODY-R-008)

- **Inputs.** The body integrator's only inputs are the motor command tensor (005) and external forces: gravity, wind, collisions.
- **Zero commands.** With zero commands, a grounded body's velocity is set to zero (static friction), and an airborne body follows passive physics.
- **Invariant test.** `T-BODY-I-001` runs 10 s with commands clamped to zero and checks every grounded pose is unchanged.

## 7. Clock (CLOCK-R-001, -003, -004, -010; Phase-2 subset)

- **Clock service.** `engine/clock.py` holds the integer tick count, `dt`, and the life-clock time integrated as `Δlife = Δneural × 86400 / D` in float64. It is the only time source for world, body, senses, physiology and motor.
- **Timestamps.** `sim_ts` (tick × dt) and `fly_ts` ("Day N, HH:MM:SS", genesis at Day 1, 06:00:00).
- **Deferred to Phase 3.** The pacer and the wall-clock report (CLOCK-R-002, -006..009).

## 8. Serialization (WORLD-R-003)

- `WorldGroup.state_dict()` and `BodyBatch.state_dict()` return tensors (as in the brain checkpoint) plus a JSON header: geometry spec, registry hash, clock.
- Restore checks the geometry hash and continues bit-identically (`T-WORLD-I-002`).

## 9. Registry entries (new, `config/params/world.yaml`, `body.yaml`)

Every number above is a registry entry with a citation or an `ASSUMPTION`. The main sources:

| Quantity | Value | Source or status |
|---|---|---|
| Walking speed | ≤ 20 mm/s | Strauss & Heisenberg 1993; Mendes et al. 2013 |
| Escape jump take-off velocity and angle | | Card & Dickinson 2008 |
| Looming stimulus l/v range | 10–80 ms | von Reyn et al. 2014 |
| Odorant diffusion coefficients | | standard gas-phase values (~1e-5 m²/s) |
| Body length | 2.5 mm | |
| Body mass | ~1 mg | |
| Proboscis length | 0.5 mm | ASSUMPTION within anatomical range |

## 10. Deviations and notes

- **Kinematic walking.** v1 walking has no leg dynamics. Physical walking with NeuroMechFly/FlyGym is the v2 body (BODY-R-010), and the command/contact interface is kept compatible.
- **Flight control is not yet mappable.** No flight-steering DNs are mapped in the Phase-0 I/O map. Until they are (MOTOR-OQ-02), airborne flies get thrust only from the escape jump and then glide and land.
- **No surface-condensation field.** Humidity and temperature are plain scalar fields.
