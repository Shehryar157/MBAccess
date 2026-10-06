# World map (Warband 1.174)

## Parties (VERIFIED 2026-10-06, session 10, in a town menu; tools/probe_parties.py)

- game+0x140b8 is the `items` stl::vector of rgl::hash_vector<party>, but it holds BLOCKS of 16
  parties, not single parties: party n = items[n // 16] + (n % 16) * 0x5d28. 441 slots in use
  at the start of a Native campaign (0x1b9 just before the vector and again after it; 0x1c0 =
  448 = room for 28 blocks). So the "29 items" in screens.md were blocks; party_skills.py found
  p_main_party only because it is party 0, the first in block 0.
- game_object base: +0 vtable, +4 valid, +8 no (the party's number).
- Party fields match WarbandLib/party.h up to faction_no; after that one extra int (flags land at
  +0x238 instead of +0x230) and timers are 16 bytes:
  - +0x0c name (rgl::string), +0xa0 id, +0x130 position (2 floats: x east, y north)
  - +0x1e4 radius, +0x1e8 label_transparency, +0x1ec label_visible (0 for towns while in a town
    menu: check on the map), +0x1f0 faction_no
  - +0x238 flags (u64): low byte = map icon, 0x400 static, 0x4000 always visible, 0x400000 show
    faction, 0x100 disabled (hidden). Sargoth: 0x40640c.
  - +0x240 stacks vector (first +0x244), +0x250 num_stacks, +0x258 speed, +0x25c speed multiplier
  - +0x274 attached_to_party_no (-1), +0x294 ai_default_behavior, +0x29c initial position,
    +0x2a4 patrol radius, +0x2d0 ai_current_behavior, +0x2d4 its object, +0x2dc last known
    target position, +0x320 destination position
  - +0x328 path faces [1024], +0x1328 path positions [1024 x 16 bytes]
  - +0x5330 cur_quad, **+0x5334 cur_terrain_type** (3 = plain in the town), then u9[7],
    +0x5354 move_mode?, +0x5358 move_target_position?, +0x5364 move_target_party_no? (the last
    three are guesses by counting: verify while travelling)
- Map axes: +x = east, +y = north (Sargoth y 79.7 north, Shariz y -107 south, Tulga x 135 east).
- Terrain numbers (header_terrain_types.py): 0 water, 1 mountain, 2 steppe, 3 plain, 4 snow,
  5 desert, 7 bridge, 8 river, 9 mountain forest, 10 steppe forest, 11 forest, 12 snow forest,
  13 desert forest.
- AI behaviours (header_parties.py): 0 hold, 1 travel to party, 2 patrol location, 3 patrol
  party, 4 attack party, 5 avoid party, 6 travel to point, 7 negotiate, 8 in town, 9 travel to
  ship, 10 escort, 11 driven by party.

## Factions (VERIFIED)

- game+0x1413c pointer to the factions array, +0x14140 count (34 in Native). Stride 0xca4.
  Faction: +0 name (rgl::string, "Kingdom of Nords"), +0x94 id ("fac_kingdom_4").
  Names starting "{!}" are internal.

## Not yet known

- How the game decides a party is visible to the player (label_visible? entity flags?).
- What a map click writes (move_mode values, target party vs point), to make Enter = click.

## Plan agreed with the user (session 10, 2026-10-06)

- RULE: only what a sighted player has. No "fake walking" (holding an arrow to steer). Map travel
  is clicking a place, a party or a ground spot; WASD only pans the camera.
- To build: (1) a list key: visible places and parties, nearest first, with compass direction
  and distance (and troops/kingdom); Enter = the same as clicking it (travel or chase).
  (2) Announcements a sighted player would notice on screen: terrain change, parties coming
  into or leaving view, arriving or stopping, night and day; each switchable on the
  Accessibility tab. (3) A status key: nearest place and terrain, moving or not and where to,
  date and time. Clicking empty ground: later.
- Next research (needs the player ON THE MAP): the visibility flag (label_visible +0x1ec?), and
  what a map click writes (move_mode / target fields near +0x5354, guessed). The user allowed a
  short click test only after asking; ask again.
- AFTER the map, scenes: wall-proximity sine beeps in ALL directions (stereo pan; behind needs a
  different sound), 3-4 pitches rising as you get closer, starting about 4 m on foot (the user
  asked for 5 ft "or more if too short"; M&B units are metres), further on horseback. Sounds
  for objects, doors and people will come from the user. Hard part: finding walls (engine
  raycast from inside the game via the loader DLL, or our own collision from scene files).

## Session state at the end of session 10

- No save game exists (Savegames folder empty): the old intro campaign is gone. The user does
  character creation themselves, then asks me to take over through the intro to the map; save
  as soon as we're on the map.
- Starting the game: mb_warband.exe started directly exits (Steam relaunch), and
  "steam.exe -applaunch 48700" and steam://rungameid/48700 did nothing. Ask the user to start it.
