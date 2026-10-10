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
- The user wants to play arena fights THEMSELVES: record passively, never drive them.
- First run was with NO scene open (trade screen; the old Jelkala tavern mission still in
  memory, 7 agents): health candidates +0x864, +0x5d6c, +0x5f50, +0x5ff8; +0x864 read
  spawn ?, max 45, now 0 for all seven. Means nothing until run in a live scene: a stale
  mission's numbers may be cleared. NEXT: run it in the village centre, then in the arena.
