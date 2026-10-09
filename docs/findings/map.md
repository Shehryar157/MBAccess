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

## Visibility (session 11, 2026-10-06, on the map just outside Jelkala; PROBABLE)

- The map is window 6. Its tree reads: "Paused" (shown while not travelling), the six buttons
  Camp/Reports/Notes/Inventory/Character/Party, the date and the time of day.
- Party 0 at Jelkala (-73, -80.4), 474 parties. label_visible (+0x1ec) = 1 and
  label_transparency (+0x1e8) = 1.0 for the nearest Looters (2.4 away); Looters 4.2 away and
  further: 0 and 0.0. So for moving parties +0x1ec / +0x1e8 look like "spotted" (in sight
  range), NOT "on camera": the screenshot (camera low, looking north) didn't show those Looters.
- Lords inside a town (King Graveth 1.8 away, flags 0x410004) have 0 / -1000: hidden.
- Towns and castles carry flag 0x4000 (always visible) and show on the map whatever their
  label_visible; only the nearest town had it at 1. Plan: list static places always (unless
  0x100 disabled), moving parties only while +0x1ec is 1.
- Unverified: the spotting range (party skill Spotting), night, and whether +0x1ec stays 1 while
  a spotted party is behind the camera.

## Travel orders (session 11, 2026-10-07; VERIFIED by clicks and memory writes)

- A ground click writes, in party 0: +0x2d0 ai_current_behavior = 6 (travel to point),
  +0x5354 move mode = 1, +0x5358/+0x535c target point (x, y); +0x320 destination follows.
- A click on a party (Looters 463) writes: +0x2d0 = 4 (attack: they're hostile; a friendly place
  should be 1, travel to party), +0x2d4 = 463, +0x5354 = 2, +0x5364 = 463 (target party),
  +0x5358 = its position (kept updated as it moves).
- WRITING the order works: +0x5364 = target, +0x5358 = its position, +0x5354 = 2 made the
  party ride straight to Jelkala (the game plans the route; the camera doesn't matter).
  Without +0x2d0 = 1 / +0x2d4 = target it stopped on top of the town. With them it arrived and
  behaviour became 8 (in town) with +0x2d4 = 158 (Ibdeles), BUT NO MENU OPENED.
- A real click on Ibdeles while standing on it opened the village menu at once. In the game
  object: +0x140fc 463 -> 158 (it held the Looters after their robbery talk: "encountered party"?),
  +0x14104 1 -> 0, +0x14108 0 -> 1, +0x14224 0 -> 1, cur_menu_no -> 88. NEXT: test whether
  writing +0x140fc (and the flags) on arrival opens the menu. Fallback: on arrival do one real
  click on the place (it's under the party, on screen), as a sighted player would.
- The map clock runs only while the party moves and no other window (party screen) is open.
- Hostile parties that spotted you chase you: behaviour 7 (negotiate) + their number in +0x2d4
  appeared when Looters caught the player; the conversation (window 12) followed.
- Surrender to Looters: lost ~80 denars, health 100%, moved ~22 units south (Jelkala ->
  near Ibdeles).

## Map list BUILT (session 12, 2026-10-07; list verified read-only, travel UNTESTED)

- mbaccess/world_map.py, profile screen["map"] (all offsets above), window 6
  {"name": "Map", "tree": true, "map": true}. The places are virtual items (widget = the
  party's address, so the cursor follows a place as the list re-sorts) in their own section
  "Places"; Tab goes to "Map buttons". Re-read once a second: one 0x278-byte read per party,
  25 ms for 474 slots. tools/probe_map.py prints the list (read-only).
- Verified in the Ibdeles village menu: 185 items, nearest first; directions agree with the
  known towns (Jelkala 18 north of Ibdeles). Wording: "Jelkala, town, 18 north, Kingdom of
  Rhodoks"; moving parties add "N troops". Distances are map units (meaning unknown).
- Enter writes the order (behaviour 1 + target, move target point and party, move mode 2
  last). Reader.write / Game.write (pymem write_bytes) added for it. Arrival is announced when
  behaviour becomes 8 with the target as object. KNOWN GAP: the place's menu doesn't open on
  arrival (see Travel orders). Unverified: behaviour 1 for a hostile party (a click wrote 4).
- Ideas not built: 185 items is long: first-letter jump or a filter (towns only / parties
  only); a status key; announcements (spotted, terrain, night); clicking ground.

## Escape and type search (session 12, 2026-10-07; unit-tested, UNTESTED in game)

- All screens (menu_watch.back_item / type_search): Escape presses the LAST option or button
  whose label starts with go back / back / leave / return / resume travel / cancel / never mind
  / forget it / done / close; the hook swallows Escape only then (run.py), so the map and
  scenes keep the game's Escape. Letters and digits type-search (1 s pause starts over; the
  same letter repeated steps through matches); swallowed only while a screen has items and
  no edit box is focused. Window 10 (scene) has "type_search": false, "escape": false so
  walking keys can never be eaten. Side effect: on the map the game's I/P/C shortcuts are
  replaced by type search (the map buttons do the same).
- The user found Esc missing in a "travel menu" (probably Camp: "Resume travelling").
- Silence on the map and in menus: Native has no ambience outside 3D scenes; the user's
  rgl_config.txt had music_volume = 0.0746 (7%).

## Not yet known

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

## Arrival opens the menu: FIXED (session 13, 2026-10-07; VERIFIED live)

- Diffing a real click on a distant town (Jelkala) showed the player's click order is
  behaviour **4** (+0x2d0, "attack party" in the header, but for the player it means "go and
  meet") with +0x2d4 = the place, move mode **1** (ride to a point) and +0x5358 = the place's
  position; +0x5364 is left alone. Our old write used behaviour 1 (travel to party, the AI
  lords' order): the party rode in and became 8 (in town) quietly, so no menu opened.
- With behaviour 4 the arrival starts the encounter: behaviour becomes 7 (negotiate) with the
  place as object and the place's menu opens (window 18). Verified Jelkala (real click) and
  Ibdeles Castle (the mod's write). For a moving party the mod writes behaviour 4 + move mode 2
  + target party, as the earlier Looters click did (not re-tested).
- A real click on the place you're standing on also opens its menu (castle at about x 0.52,
  y 0.23 engine coordinates: the camera centres on the player's party). Fallback if ever needed.
- game+0x14224 flips to 1 on any map click (not "menu open"); +0x140fc / +0x14108 writes alone
  did nothing while the map was paused.

## Right-click context menu on the map (found 2026-10-10, session 17, from the Module System; not tried live)
- Right-clicking a party on the world map opens a small menu the module script fills
  (module_scripts.py "game_context_menu_get_buttons", party number as argument):
  "Move here" (any party but the player's), "View notes" (towns/castles/villages, or a party led
  by a companion/lord: opens the notes screen), "Accompany" (follow: parties of the player's own
  kingdom or caravans, not places). The click goes to "game_event_context_menu_button_clicked".
- Useful later: map list keys for "Accompany" and "View notes" (a sighted player has them by
  right click). Where the menu lives in memory (a window number?) is unknown.
