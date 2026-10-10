# Battles

## Start (2026-10-10, session 21): nothing verified yet
- Plan, in order: (1) per-fighter facts: team, alive, health, current attack/defend action and
  its direction; (2) enemies and allies on the radar; (3) own health and hits; (4) block cues;
  (5) troop orders (F1-F6, group keys); (6) sieges (ladders, doors), arenas, tournaments.
- First fight to test in: a town's arena (real teams, losing costs nothing). The user said
  battles last, and gave the go-ahead on 2026-10-10.
- mbaccess/battle.py: agents() yields every agent's whole struct (0x6200 bytes);
  find_health() finds hit_points_at_spawn / max / float / int by SHAPE (three floats then the
  last one again as an int, true for every living agent); small_int_fields() lists where a
  team, group or division number could be. agent.h (1.153) order: team_no, group_no,
  division_no, a timer, division_member_no, ..., wielded_items[2], ..., attack_action_direction,
  attack_action_type, defend_action_direction, ..., hit_points x4, ..., kill_count.
- tools/probe_battle.py (reads only): everyone with troop name and health guesses; "teams"
  adds the candidate team fields; "watch" prints what changes in the player's agent.
- HEALTH VERIFIED (Buvran village centre, read-only): agent +0x5ff8 hit points at spawn,
  +0x5ffc max, +0x6000 now (floats), +0x6004 now as an int. Villagers 42-44, elder 42, a
  horse 100, the player 52. H in a scene speaks "Health 52 of 52" (+ the horse's when
  mounted, via agent +0x114); battle.health_words. Untested by the user; never seen below max.
- TEAM not found yet: everyone in a village is peaceful. Guess from the header order:
  +0x7b0 team (all -1 here?), +0x7b4 group (-1, player 0), +0x7b8 division (-1, player 0),
  +0x7d0 division member (0-8 for the nine villagers). Other fields where only the player
  differs: +0x270 (1, player 2), +0x4f0, +0x6a0, +0x5f8c (1, player 0). Settle it in the arena.
- tools/record_battle.py [seconds] [name]: passive recorder for a fight the USER plays (they
  want to fight the arena themselves; never drive it). Player 5 times a second, others once;
  "read" prints each fighter's health and status over time. logs/stop ends it early.

## Arena melee recording (2026-10-10, session 21; logs/arena1.pkl.gz, the user fought and lost)
- TEAM VERIFIED: agent +0x7b4 (and +0x7b8, same value). Melee: six fighters 3, 5, 3, 5, 2, 2
  (pairs), Tournament Master watching -1, player 6. Village: everyone -1, player 0. Arena
  lobby afterwards: player -1, a Veteran Fighter 4.
- Status +0x30: 1 alive, 4 knocked unconscious (player and a Regular Fighter; health 0).
  The player's health stepped 52, 43, 37, 27, 19, 13, 9, 4, 0, then 52 again in the lobby.
- Likely "who hit me last": +0x5dbc (-1 until hit; the knocked-out fighter held 8 = the
  Veteran Fighter the message log named; the player cycled 12, 11, 13) and +0x5ea8 (similar,
  never -1 in the fight). +0x60f4 = -1 between hits, 85-99 during one (a hit animation?).
  NOT found: attack and block state. The player never swung, and the others were sampled only
  once a second: record again with everyone at 5-10 a second (tools/analyse_battle.py reads it).
- BUILT (untested by the user): scanner categories Enemies and Allies (battle.side: another
  team = enemy, -1 = bystander; a friendly lord's team in a real battle will wrongly count as
  enemy until the mission's team relations are found); B = "2 with you, 6 against, most of
  them 12 metres, ahead left"; N = nearest enemy; "Talk to" isn't offered for an enemy, and
  Close enough mode skips enemies.
- OPEN: in the melee the mod read the fight's HUD as a screen ("Opponents Beaten: 0, 1 of 2",
  "Opponents Remaining: 40", "80 80, 3 of 3"). It should speak changes, not take the cursor.
- FIXED after the user's first custom battle (same day): the scene window (10) has "hud":
  true in the profile, so its texts never form a menu (menu_watch.read_hud). The ORDER PANEL
  ("F1 - Movement orders" ...) is spoken whole when it appears or changes; the game only takes
  the F keys there (the user arrowed and pressed Enter, and no order was ever given: the log
  had no confirmation message). "10 10" was the AMMUNITION count (13 throwing daggers going
  down; drawn twice, text and shadow): now on H. Arena counters are on B. Other texts
  ("Battle won! Press tab key to leave...") are spoken once. "Talk to Swadian Footman" in a
  battle: no prompt now for anyone on a team (friend or enemy). All UNTESTED in a battle.
- User's settings (read from the Options screen in the log): Control Block Direction =
  Automatic; Control Attack Direction choices = By mouse movement, By inverse mouse movement,
  By movement keys, By relative enemy position (they tried them; the user leans to movement
  keys); Damage to Player = Reduced to 1/4 (Easiest). Suggested keys, not agreed yet: Up arrow
  attack, Down arrow defend (set on the game's Controls screen; Left/Right already turn).

## Attack and block state FOUND; swing cue built (2026-10-10, logs/battle2.pkl.gz, a custom battle)
- Agent +0x6e4 (and +0x6e8) = the upper body's ACTION NUMBER = an index into the module's
  actions.txt (670 actions in Native; an action's line starts with one space, its sequences'
  with two: modfiles.parse_actions). -1 between actions. Seen on the player: 143
  equip_default, 188 ready_throwing_knife, 189 release_throwing_knife, 320 defend_shield_keep
  (so the user's Down arrow = defend works). Names follow one scheme for every weapon:
  ready_<slashright|slashleft|overswing|thrust>_<onehanded|twohanded|staff|...> (melee),
  ready_bow / crossbow / javelin / throwing_knife ... (ranged), release_*, defend_*, parried_*,
  blocked_*, strike_* (being hit). The legs' action is probably +0x6c0 (127 lancer_ride_1?).
- battle.SwingWatch (in the wall-beep thread, every 50 ms): an ENEMY whose action changes to
  ready_* plays a 3D sound from where he stands: melee within 5 m = a short upward "zip",
  higher the closer; ranged within 80 m AND facing us within 3 m of where we stand = a low
  rising "creak". Up to 3 at once. Learn sound buttons "swing" and "aim". UNTESTED live.
- tools/replay_swings.py <recording> runs the watcher over a recording: battle2 gave 0 melee
  (nobody came near the user: their men charged off) and 3 ranged at 73-80 m before the aim
  was narrowed. The block direction is in the name if manual blocking is ever wanted.
- Orders: the user pressed 0 and 1 and heard the list, but never an F key, expecting to arrow
  through it. Added M = the order list again, and B now says where your own men are. Troops
  start a battle already charging, which is why they were far from the user.
- ORDER LIST, second pass (the user asked for arrows as well): Up/Down walk the open list (no
  wrap), Enter presses that row's function key for the game (keys.tap_scan, scan 0x3B + n - 1);
  the F keys still work directly. While a list is open run.py swallows Up and Down (the user's
  attack and defend) so they don't swing. The user had read "F1 - ..." as "press the letter F
  on it": the first list of a session now starts with a hint that F1 is a function key.
  Tested on a made-up list only; NOT in a battle (does a swallowed Up really not attack? does
  the list close by itself, and when?).
- HELD ITEMS (from the battle2 recording; NOT yet seen live): agent item slot n's kind at
  +0x7d4 + 8 * n (the next int is the item's own count: daggers thrown 0-5, a shield's 360);
  +0x830 right hand's slot, +0x834 left hand's (shield), -1 empty; +0x838/+0x83c repeat. The
  user had slot 0 = 541 Throwing Daggers, slot 1 = 491 Wooden Shield, hands (0, 1). Slots 2
  and 3 unverified. battle.HandWatch speaks the name when a hand changes ("Battle Axe", "no
  shield", "weapon put away") and H adds "holding ...". The user asked for this for next
  weapon / next shield (Page Up / Page Down). The old "+0x544 + n * 0x30" guess was wrong.
- Keys the user set on the game's Controls screen: Up attack, Down defend, Page Up next
  weapon, Page Down next shield. Still free in scenes: U V Z /.
- The user wants to play arena fights THEMSELVES: record passively, never drive them.
- First run was with NO scene open (trade screen; the old Jelkala tavern mission still in
  memory, 7 agents): health candidates +0x864, +0x5d6c, +0x5f50, +0x5ff8; +0x864 read
  spawn ?, max 45, now 0 for all seven. Means nothing until run in a live scene: a stale
  mission's numbers may be cleared. NEXT: run it in the village centre, then in the arena.
