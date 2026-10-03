# 003 — Body & World

| Field | Value |
|---|---|
| Status | Draft — awaiting review |
| ID prefixes | `WORLD` (environment), `BODY` (ColonyBody) |
| Phase | 2 (dome, body, basic fields); 4–5 (food lifecycle, nursery, life-cycle entities); 7 (chamber world side) |
| Plan refs | §5.1, §5.2, §5.5 (entities), §7 (contact physics), §10.1 (naturalization), §10.4 (chambers) |
| Depends on | 000, 009 (clocks, Control API) |
| Used by | 004, 005, 006, 008, 012 |
| Constitution | CONST-1.2 (world and physics layer), CONST-2.1 and 2.4 (no Watcher entity; naturalized changes), CONST-5 |

## 1. Purpose

Provide the physical world the flies live in (the Colony Dome and the separate Puzzle Chambers) and the bodies they live in (ColonyBody). The world supplies everything the senses can detect. The body executes motor commands under physical law. **Neither ever makes a choice for a fly.**

## 2. Scope

**In scope:** world structure and zones; food, water and substrates; light, sky, polarization and weather; odor, acoustic and contact-chemical fields; life-cycle entities (eggs, larvae, pupae, corpses); ColonyBody walking, flight and contact physics; copulation coupling; injury; egg deposition; the world side of chambers; how environment commands are applied (naturalization).

**Out of scope:** turning fields into neural input (004); DN → primitive readout (005); metabolism and development timing (006); the chamber and task schema and scoring (012); the v2 FlyGym body (only its interface is kept compatible).

## 3. Requirements — World

### 3.1 Structure and determinism

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WORLD-R-001 | M | THE ENGINE SHALL keep one Colony Dome and zero or more Puzzle Chambers. Each is a closed space with no physical path to any other, and every entity belongs to exactly one of them at a time. | T-WORLD-U-001 |
| WORLD-R-002 | M | THE ENGINE SHALL update each world deterministically on a fixed timestep, synchronized with the brain schedule (BRAIN-R-023). | T-WORLD-I-001 |
| WORLD-R-003 | M | THE ENGINE SHALL be able to serialize and restore the complete world state. | T-WORLD-I-002 |
| WORLD-R-004 | M | THE ENGINE SHALL contain no entity type, field or effect that represents the Watcher. | T-WORLD-I-003 |

### 3.2 Colony Dome

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WORLD-R-010 | M | The dome SHALL default to a 50 cm floor diameter and 30 cm height (configurable). Walls and ceiling are walkable surfaces. | T-WORLD-U-002 |
| WORLD-R-011 | M | THE ENGINE SHALL model the zones Orchard, Water springs, Nursery, Perches, Open plaza and Challenge Grounds as regions with physical properties defined in `config/colony.yaml`. **Zones never pull or push flies.** | T-WORLD-U-002, review |
| WORLD-R-012 | M | Every surface SHALL carry material properties: walkable, graspable (for landing), substrate type (for taste and egg-laying), and visual texture (for vision). | T-WORLD-U-002 |

### 3.3 Food, water and substrates

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WORLD-R-020 | M | Food patches SHALL go through the stages unripe → ripe → fermenting → rotting → depleted, with stage durations in life-clock time (registry). Each stage has its own nutrients (sugar, protein, water, ethanol, optional bitter or toxic compounds) and odor emission profile (e.g. ethanol, acetic acid, ethyl acetate). | T-WORLD-U-003 |
| WORLD-R-021 | M | Feeding SHALL deplete a patch by exactly the amount ingested (reported by 006). | T-WORLD-U-003 |
| WORLD-R-022 | M | Yeast SHALL grow on fermenting patches and provide protein. | T-WORLD-U-003 |
| WORLD-R-023 | M | Water springs SHALL be contact sources of water and local sources of humidity. | T-WORLD-U-004 |
| WORLD-R-024 | M | The Nursery SHALL provide egg-laying substrate with a finite larval food capacity. Pupae sit on nearby wall surfaces. | T-WORLD-U-005 |
| WORLD-R-025 | M | New food SHALL appear only by ripening in place from a small, low-odor state over a registry ramp duration (naturalized). | T-WORLD-U-003 |
| WORLD-R-026 | S | THE ENGINE SHALL support bitter and toxic food variants for tasks and survival scenarios. | T-WORLD-U-003 |

### 3.4 Sky, light and weather

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WORLD-R-030 | M | Light intensity SHALL ramp between night and day following the life clock (default 12 h light : 12 h dark, registry dawn/dusk ramp), with spectral channels sufficient for photoreceptor types R1–R8 (UV, blue, green). | T-WORLD-U-006 |
| WORLD-R-031 | M | THE ENGINE SHALL model sun position, a sky luminance gradient, and a polarized-light e-vector pattern derived from the sun's position. | T-WORLD-U-006 |
| WORLD-R-032 | M | THE ENGINE SHALL keep temperature and humidity fields with sources (vents, heat/cool zones, springs). Changes ramp gradually (registry minimum ramp time). | T-WORLD-U-007 |
| WORLD-R-033 | M | Vents SHALL drive a steady-state wind field, recomputed when vents change. The wind carries odors and pushes flying flies. | T-WORLD-U-008 |
| WORLD-R-034 | M | Day length and seasonal temperature profiles SHALL be adjustable through the Control API. | T-WORLD-U-006 |
| WORLD-R-035 | S | THE ENGINE SHALL produce looming-shadow events (an expanding dark disk on the sky), either at a natural random rate from the registry or on command. They are harmless unless a predation option is enabled. | T-WORLD-U-009 |

### 3.5 Odor, sound and contact chemistry

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WORLD-R-040 | M | THE ENGINE SHALL keep a 3D odor grid of 10–20 odorant species (list in the registry; includes ethanol, acetic acid, ethyl acetate, CO₂, geosmin, cVA) with wind advection, diffusion and decay. Sources: food stages, flies (e.g. cVA), optional corpse odor, and chamber odor ports. | T-WORLD-U-010 |
| WORLD-R-041 | M | Odor, sound, contact and visual sources SHALL carry a source-entity tag so the engine can attribute sensory input to its source (observation only; used by 008). | T-WORLD-U-011 |
| WORLD-R-042 | M | THE ENGINE SHALL model near-field sound: wing-vibration sources produce particle velocity at any point, falling off with distance per the registry model, and multiple sources superpose. | T-WORLD-U-012 |
| WORLD-R-043 | C | THE ENGINE MAY model substrate vibration (e.g. abdominal quivering) as an extra channel. | — |
| WORLD-R-044 | M | Each fly SHALL carry a cuticular hydrocarbon profile (e.g. 7-T in males, 7,11-HD in females, cVA on males and on mated females), available to the contact chemoreceptors of flies that touch it. Profiles can be transferred by mating (006). | T-WORLD-U-013 |

### 3.6 Life-cycle entities

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WORLD-R-050 | M | Eggs, larvae, pupae and corpses SHALL be world entities with a position and a visual appearance. Corpses stay visible and decay over a registry duration of life-clock time. | T-WORLD-U-005 |
| WORLD-R-051 | M | Pupae SHALL be fixed on surfaces. Eclosion creates the adult body at the pupa's location. | T-WORLD-U-005 |

### 3.7 Puzzle Chambers (world side)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WORLD-R-060 | M | THE ENGINE SHALL build chambers from declarative specs (012): geometry (including walls compiled from maze graphs), surfaces, light, temperature zones, odor ports, food, water, bitter and heat sources, and image panoramas. | T-WORLD-U-014 |
| WORLD-R-061 | M | Chambers SHALL use exactly the same physics and sensing as the dome. | T-WORLD-U-014 |
| WORLD-R-062 | M | A fly's physiology SHALL keep running while it is inside a chamber. | T-LIFE-U-001 |

### 3.8 Applying environment commands (naturalization)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| WORLD-R-070 | M | THE ENGINE SHALL accept environment changes only from the Control API (009), apply them at step boundaries, and use the naturalization method declared for that command type. | T-WATCH-I-003 |
| WORLD-R-071 | M | **Occluded placement.** Structural changes (adding or removing obstacles or zones, placing spawned pupae or eggs, removing a fly) SHALL be applied only when no awake fly in that world has the affected region in its visual field or within contact range, or during darkness. Otherwise the change is queued until the condition holds, and the delay is audited. | T-WORLD-U-015 |

## 4. Requirements — Body (ColonyBody v1)

| ID | Pri | Requirement | Verified by |
|---|---|---|---|
| BODY-R-001 | M | Each adult fly SHALL have a body with: position, orientation, linear and angular velocity, mode (grounded / airborne / coupled), contact sites (legs as left/right foreleg, midleg and hindleg groups, proboscis, head, wings, abdomen tip), wing angles and vibration state, proboscis extension, abdomen bend, ovipositor and vaginal-plate state, and size and mass (from genome × larval nutrition). | T-BODY-U-001 |
| BODY-R-002 | M | Grounded bodies SHALL walk on any walkable surface (floor, wall, ceiling, perch, fruit) using velocity and turning commands from motor primitives. Walking is limited by a maximum speed (registry, within ~1–3 cm/s, scaled by genome and stamina), adhesion and collisions. | T-BODY-U-002 |
| BODY-R-003 | M | THE ENGINE SHALL support simplified 3D flight: takeoff (voluntary, or an escape jump), steered flight from yaw/pitch/thrust commands, and landing on graspable surfaces. Wind force applies. Speeds and energy costs are in the registry. | T-BODY-U-003 |
| BODY-R-004 | M | THE ENGINE SHALL detect fly–fly contacts and resolve collisions, touches (for tapping and licking), impulses (lunges, boxing) and grasps (holding), and SHALL publish every contact on the Observation Stream. | T-BODY-U-004 |
| BODY-R-005 | M | **Copulation takes two brains.** WHEN a male's copulation primitive is active with genital contact to a female AND that female's vaginal-plate-opening output is active THEN the two bodies SHALL enter coupled mode. Coupling lasts while the male's coupling output is sustained (so its duration emerges) and ends when that output stops or a registry-defined physical disruption occurs. | T-BODY-U-005 |
| BODY-R-006 | M | Impacts above a registry threshold SHALL produce injury points (passed to 006). A wing-damage option (default off) reduces flight ability. Death from fighting is off by default. | T-BODY-U-006 |
| BODY-R-007 | M | THE ENGINE SHALL simulate all bodies in a deterministic GPU batch. | T-WORLD-I-001 |
| BODY-R-008 | M | A body SHALL move only because of motor-primitive commands or external physical forces (gravity, pushes, wind). A body never moves on its own. | T-BODY-I-001 |
| BODY-R-009 | M | WHEN the egg-laying primitive is active, the ovipositor touches a substrate, and egg load > 0, THE ENGINE SHALL deposit one egg at the ovipositor position. | T-BODY-U-007 |
| BODY-R-010 | C | The body interface (motor commands in, contacts and proprioception out) SHALL stay compatible with a v2 FlyGym 2.x / NeuroMechFly body driven by motor-neuron readout. | review |

## 5. Acceptance criteria

| ID | Criterion |
|---|---|
| WORLD-AC-01 | A body walking at 2 cm/s crosses the 50 cm dome in ≈ 25 s (geometry and scale sanity check). |
| WORLD-AC-02 | An odor released upwind of a vent-driven flow is detectable downwind and not upwind. Odor mass is conserved within tolerance, apart from decay. |
| WORLD-AC-03 | The day/night ramp follows the life clock, and changing D shifts the timing consistently. |
| WORLD-AC-04 | Food passes through every stage in order, with the specified odor profile at each stage. |
| WORLD-AC-05 | World and body steps are bit-identical across repeated runs. |
| WORLD-AC-06 | Copulation coupling needs both outputs: driving only the male side or only the female side produces no coupling; driving both does. |
| WORLD-AC-07 | With all DN outputs at zero, every body stays at rest apart from passive physics. |
| WORLD-AC-08 | A structural change is deferred while any awake fly can see the region, and it is applied (and audited) once none can. |
| WORLD-AC-09 | An audit of entity and field types finds nothing that represents the Watcher. |

## 6. Tests

| Test ID | Level | Checks |
|---|---|---|
| T-WORLD-U-001 | unit | World membership; no path between worlds. |
| T-WORLD-U-002 | unit | Dome geometry, zones and surface properties. |
| T-WORLD-U-003 | unit | Food lifecycle, depletion, yeast growth, ripening-in-place. |
| T-WORLD-U-004 | unit | Water springs. |
| T-WORLD-U-005 | unit | Nursery capacity; eggs, larvae, pupae and corpses. |
| T-WORLD-U-006 | unit | Light ramp, sun, polarization, seasons. |
| T-WORLD-U-007 | unit | Temperature and humidity fields and ramps. |
| T-WORLD-U-008 | unit | Wind field. |
| T-WORLD-U-009 | unit | Looming-shadow generator. |
| T-WORLD-U-010 | unit | Odor advection, diffusion, decay and conservation. |
| T-WORLD-U-011 | unit | Source tagging and attribution. |
| T-WORLD-U-012 | unit | Near-field sound falloff and superposition. |
| T-WORLD-U-013 | unit | Cuticular hydrocarbon profiles and transfer. |
| T-WORLD-U-014 | unit | Chamber instantiation and physics parity. |
| T-WORLD-U-015 | unit | Occluded-placement rule and deferral. |
| T-BODY-U-001..007 | unit | Body state; walking; flight; contacts; coupling; injury; egg deposition. |
| T-WORLD-I-001 | invariant | Determinism of world and body steps. |
| T-WORLD-I-002 | invariant | World checkpoint round trip. |
| T-WORLD-I-003 | invariant | No Watcher entity. |
| T-BODY-I-001 | invariant | No self-motion without commands or forces. |

## 7. Assumptions and open questions

| ID | Question | Proposal |
|---|---|---|
| WORLD-OQ-01 | Odor grid resolution and species list. | 2.5–5 mm cells in the dome (finer in chambers); 12 species to start. Decide in design against the VRAM budget. |
| WORLD-OQ-02 | Do corpses smell? | Off by default (`ASSUMPTION`); visual only. |
| WORLD-OQ-03 | Is the occluded-placement rule (R-071) an acceptable naturalization for structural changes? | Yes, together with a darkness option; queued delays are shown to you. |
| WORLD-OQ-04 | Larvae as positioned entities or as abstract "nursery pools"? | Positioned entities with no behavior (CONST-1.5), so they are visible to adults. |
| WORLD-OQ-05 | Individual leg contacts vs grouped contact sites? | Grouped per leg pair and side (enough for foreleg tapping). Full legs arrive with the v2 FlyGym body. |
| WORLD-OQ-06 | Are looming shadows ever dangerous? | Harmless by default; predation is a flagged option. |
