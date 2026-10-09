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
- ~~32 rays, nearest hit per quarter~~ (2026-10-10: replaced). The user heard front AND left
  beeps when pressing A toward a wall on the left: a 90-degree wedge includes its diagonal
  rays, which reach a side wall at 1.4x its distance, so one wall counted in two zones.
- Now: each zone is a CORRIDOR as wide as the body (5 parallel rays; half width 0.3 m on foot;
  on horseback 0.5 m ahead/behind, 1.2 m sideways). The distance = how far that movement
  key can take you before touching something. Verified on a fake scene; untested in game.
- 2026-10-10 later: EIGHT corridors (the eight movement-key directions). walls.corners_only()
  hears each wall once: a diagonal is dropped when its two neighbours' walls explain it
  (sqrt2 x nearest neighbour - half width - 0.3 m), so a flat wall beeps only as left, a
  post or corner in the diagonal beeps as that diagonal. Verified on fake scenes.
- Sound: OpenAL Soft 1.18.2 from the PyOpenAL wheel (pip install PyOpenAL; its
  soft_oal_64.dll), via ctypes in mbaccess/sound3d.py. HRTF status 4 = on because
  headphones detected; built-in HRTF only. Sources are listener-relative at fixed angles.
  Pure sines place badly in HRTF, so diagonals have overtones: front ones bright single
  blip, back ones hollow (odd harmonics) double blip. DIAGONAL_ANGLE (45) in
  wall_beeps.py moves them; tools/beep_demo.py [angle] plays all eight. Untested by user.
- 2026-10-10 "keeps moving after I let go" (tools/move_probe.py, on horseback): the mod's hook
  passes releases in 5-25 ms (worst 157 ms), so NOT the mod. The horse coasts: up to 18 s
  and 11 m after letting go of A. Game behaviour: W speeds up, S brakes, A/D steer.
  On foot not measured yet. Idea offered: a cue when the horse comes to a halt / speed level.
- Horse drone (wall_beeps.py): starts when W is let go on a moving horse; pitch slides only
  downward (ratchet) from the let-go speed to 0.35x at the halt; S backing up after a halt is
  silent. Simulated; untested by the user.
- CAUTION: the mission pointer and player agent stay readable after leaving a scene (they
  read "on horse" in the village menu). Always check the top window is 10 before testing:
  on 2026-10-10 my F and W test presses landed on the village menu ("No w" type-search).
- Action prompts: tactical_window (WSE header) has use_object_type / use_object_no /
  use_object_in_range after the camera fields; camera_agent_no = player agent no found at
  window 10 +0x3e8 (+0x3ec prev). +0x400 is a ticking timer. Use fields NOT confirmed yet
  (no changes seen; the user was likely not facing anything). tools/use_probe.py ready.
- Open: dismounting with F (the only Action key; no separate dismount control) not yet
  tried in a scene by me.
- Open: on foot, does the stored angle follow the camera or turn toward the strafe
  direction? Only verified on horseback. Test: tools/wall_probe.py while the user strafes.

## Open

- Vtables are hard-coded; for WFS, classify shapes by structure instead (discover rule).
- Other agents as obstacles; doors (moveable flag), ladders. Sounds: user will supply some.
- Sounds: four zones with distinct sounds (agreed direction, user to confirm), pitch steps
  rising when closer, start ~4 m on foot, further on horseback.

## Scanner (2026-10-10, session 16): objects and people by name. VERIFIED read-only in a village

- mission+0xc75c: mission_objects, an rgl::stable_vector shaped like the agents (num_items,
  num_ids, ids vector (a free list, NOT one per item), chunk vector at +0x1c). Found by shape
  with tools/probe_objects.py (it lists every stable_vector in the mission; the agents show
  as +0x4, stride 0x6200). Object size 0x298, 16 per chunk.
- Object fields: vtable 0x8108d4, valid +4, no +8, position matrix +0x18 (s, f, u, origin;
  origin x y z at +0x48), meta type +0x1ac (0 prop, 1 entry point, 2 scene item, 4 plant,
  5 passage...; +0x1a8 is always 4), sub kind +0x1b0 (prop or item number), id rgl::string
  +0x1b4 (buffer pointer +0x1b8, length +0x1c0, inline text +0x1c4: "spr_village_house_e",
  plants "big_bush", items "itm_quest_wine"), variation +0x244 (assumed from WSE order).
- Village count: 418 objects = 339 plants, 18 entry points, 5 scene items, the rest props
  (incl. invisible spr_light_night, spr_barrier_16m: skipped by a name list, hard-coded).
- Agent troop number +0x298 (found: player 0, villagers all "Villager"); horse item +0x29c
  assumed from WSE (troop_no then horse_item) and NOT verified.
- Troop name = rgl::string at troop+4 (party_skills offsets).
- Passages (meta 5): none in a village; name = the current game menu's option at the
  variation index (guess, untested: needs a town). Door/stairs/gate props count as Exits.
- mbaccess/scanner.py: K/L/;/O by quarter around the facing (45 degree split), Shift+K/L categories,
  J where. Left = positive angle, same handedness assumption as the walls.
- 2026-10-10 later: a thing's number IS its slot in both stable_vectors (chunk no // 16,
  place no % 16; checked: 0 mismatches for agents and objects), so scanner.position()
  reads one thing cheaply for the tracking ping (Shift+J; played in the wall-beep thread).
- Compass (apostrophe): +y = north as on the world map; that a scene's north matches the
  map's is NOT verified, only consistent within a scene.
- Turning (mbaccess/turning.py, Shift+A/D 45 degrees), UNTESTED in game: on foot, relative
  mouse_event moves with a feedback loop on the stored angle (learns steps per degree, flips
  sign if wrong; gives up after 6 nudges with no change, which happens if the stored angle
  doesn't follow the camera while standing: unknown). On horseback, holds A/D by scan code
  until turned. The hook now ignores injected keys (LLKHF_INJECTED) so ours reach the game.
