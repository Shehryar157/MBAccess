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
- First run was with NO scene open (trade screen; the old Jelkala tavern mission still in
  memory, 7 agents): health candidates +0x864, +0x5d6c, +0x5f50, +0x5ff8; +0x864 read
  spawn ?, max 45, now 0 for all seven. Means nothing until run in a live scene: a stale
  mission's numbers may be cleared. NEXT: run it in the village centre, then in the arena.
