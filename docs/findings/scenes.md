# Scenes: walking, walls, agents (Warband 1.174)

## Found 2026-10-09/10 (session 14), VERIFIED live in a village on horseback

- Mission: `[cur_game_ptr - 4]` (WSE game_data: cur_mission sits right before cur_game).
  The pointer lands ON the mission's scene field (WSE's mission_scene), so `[mission]` = the
  rgl::scene and the agents follow at mission+4. Found because entity+4 points back to the
  scene (entities have a vtable at +0, so WSE's fields shift by 4).
- Every std::vector in these structs has an extra leading word: (0, begin, end, capacity).
- scene+0x58: stored_bodies (begin, end): EVERY collision shape (village: 28,258).
  scene+0xa0: entities (524). Only 15 entities had their own body list (+0x118); the rest
  of the collision is in stored_bodies.
- Shape kinds by vtable (body_part header = 68 bytes: vtable, face_no, flags +8, entity_no
  +0xc, grid cells, parent +0x20, b_min +0x24, b_max +0x34):
  - 0x7c131c QUAD: 4 corners in WORLD coordinates at +0x44 (16-byte stride), normal +0xc4.
    Flag 0x10 = terrain tile (3x3 m ground; 0x4010 dusty). Buildings are composites of quads.
  - 0x7c1474 COMPOSITE: parts pointer +0x44, count +0x48 (trees flag 0x208, buildings 0x8).
  - 0x7c12bc CAPSULE: end points +0x44 and +0x54 (world), radius +0x84 (fences, logs, trunks).
  - 0x7c1264 SPHERE: centre +0x54, radius +0x64.
  - Flags seen: 0x8 indestructible, 0x208 tree, 0x80008 ladder, 0x40008 moveable, 0x1000c.
- Agents: rgl::stable_vector at mission+4: num_items, num_ids, ids vector, items vector
  (chunk list begin at mission+0x20). 16 agents per chunk, agent size 0x6200.
  Agent: vtable, valid +4, no +8, stored angle +0x20, type +0x28 (1 = horse), status +0x30
  (1 alive), flags +0x34 (1 = player), position x y z +0x40. A rider and their horse share
  position and angle exactly.
- Facing: forward = stored angle + 90 degrees (world angles anticlockwise, x/y map plane, z up).
  Verified by riding forward and backward. Left/right handedness assumed, NOT yet verified.
- Speed: reading all shapes 0.14-0.8 s once per scene; slicing + 32 rays x 2 heights ~1 ms.

## How the wall finder works (mbaccess/walls.py, tools/wall_probe.py)

- Keep upright quads (|normal z| < 0.7), capsules, spheres; skip terrain and no-collision.
- Slice at knee (0.5 m) and chest (1.3 m) above the feet: quads become 2D segments,
  capsules rows of circles, spheres circles. One height alone flickered on slopes.
- 32 rays, nearest hit per quarter (front/right/behind/left), reach 15 m.

## Open

- Vtables are hard-coded; for WFS, classify shapes by structure instead (discover rule).
- Other agents as obstacles; doors (moveable flag), ladders. Sounds: user will supply some.
- Sounds: four zones with distinct sounds (agreed direction, user to confirm), pitch steps
  rising when closer, start ~4 m on foot, further on horseback.
