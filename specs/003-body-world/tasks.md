# 003 — Body & World: Tasks

| Field | Value |
|---|---|
| Status | Phase 2 in progress |
| Design | [design.md](design.md) |

`[x]` = done and its tests pass.

## Phase 2

- [x] **W1** Clock service: ticks, life clock, `sim_ts` / `fly_ts`. *CLOCK-R-001, -003, -004, -010* · T-CLOCK-U-002, -003
- [x] **W2** Geometry: cylinder dome, box arenas, discs; surface table with material properties; zones from `colony.yaml`. *WORLD-R-001, -010..012* · T-WORLD-U-001, -002
- [x] **W3** Field grid: conservative upwind advection, diffusion, decay, sources, sub-cycling, stability checks. *WORLD-R-040* · T-WORLD-U-010, WORLD-AC-02
- [x] **W4** Wind: potential-flow solve from vents; face velocities; point sampling. *WORLD-R-033* · T-WORLD-U-008
- [x] **W5** Temperature and humidity as transported scalars with relaxing sources and ramps. *WORLD-R-032* · T-WORLD-U-007
- [x] **W6** Sky: light ramp from the life clock, sun, sky gradient, polarization; day length via command. *WORLD-R-030, -031, -034* · T-WORLD-U-006, WORLD-AC-03
- [x] **W7** Looming events (natural rate and on command). *WORLD-R-035* · T-WORLD-U-009
- [x] **W8** Food patches (stages, composition, emission, depletion, ripening in place), water springs, fixed test media. *WORLD-R-020, -021, -023, -025, -026* · T-WORLD-U-003, -004, WORLD-AC-04
- [ ] **W9** Source tags on odor/contact/visual sources. *WORLD-R-041* · T-WORLD-U-011
- [x] **W10** World serialize/restore; determinism. *WORLD-R-002, -003* · T-WORLD-I-001, -002, WORLD-AC-05
- [ ] **W11** No-Watcher audit of entity and field types. *WORLD-R-004* · T-WORLD-I-003, WORLD-AC-09
- [x] **B1** BodyBatch state. *BODY-R-001* · T-BODY-U-001
- [x] **B2** Walking on surfaces with edge crossing, limits, collisions. *BODY-R-002* · T-BODY-U-002, WORLD-AC-01
- [x] **B3** Flight: point mass, escape jump, gliding, landing, impact injury points. *BODY-R-003, -006* · T-BODY-U-003, -006
- [x] **B4** Contacts: sites, surfaces, drops, fly-fly. *BODY-R-004* · T-BODY-U-004
- [x] **B5** No self-motion. *BODY-R-008* · T-BODY-I-001, WORLD-AC-07

## Later phases

- [ ] **L1** Yeast growth; food lifecycle in the dome; nursery. *WORLD-R-022, -024* (Phase 4)
- [ ] **L2** Eggs, larvae, pupae, corpses; eclosion. *WORLD-R-050, -051* (Phase 5)
- [ ] **L3** Near-field sound; cuticular hydrocarbons. *WORLD-R-042, -044* (Phase 5)
- [ ] **L4** Copulation coupling; egg deposition. *BODY-R-005, -009* · WORLD-AC-06 (Phase 5)
- [ ] **L5** Control API application and occluded placement. *WORLD-R-070, -071* · WORLD-AC-08 (Phase 3)
- [ ] **L6** Chambers from task specs. *WORLD-R-060..062* (Phase 7)
