# WFS Access: groundwork research

Goal: screen reader accessibility for Mount & Blade: With Fire & Sword (Steam app 48720),
starting with menus, then dialogue, screens, the campaign map, auto-resolved battles and,
last, real battles.

## What kind of game this is, technically

- WFS runs on TaleWorlds' engine from the Warband era: native C++, 32-bit
  (addresses look like 0x00xxxxxx, image base 0x400000), DirectX 9.
- There's no C#, so no BepInEx or Harmony. The approach is like CFC Access: either an external
  Python process that reads the game's memory, or a small injected DLL loaded through a proxy
  (a d3d9.dll or dinput8.dll proxy, the way CFCAccess's Zig loader works).
- The module's content is plain text, in the module folder (menus.txt, conversation.txt,
  strings.txt, troops.txt, items.txt, parties.txt, quests.txt...), plus translations in
  languages/<lang>/*.csv. Load these from the game at runtime; never copy them into this repo.

## Reference code (reference/, gitignored)

- `reference/wse`: the Warband Script Enhancer 1 source (by cmpxchg8b), mirror of Swyter/wse.
  License: WTFPL, so we can reuse it freely. `WarbandLib/` maps the engine's internal
  structures for Warband 1.153. WFS is an older sibling, so field layouts should be close but
  NOT identical, and every address will differ. Treat it as a map, not as ground truth.
- `reference/module_system`: the Warband 1.171 Module System (Python), from
  int19h/mb_warband_module_system. It shows how menus, dialogue, troops and so on are defined
  and compiled into the .txt files.
- `reference/warbend`: int19h's Python library for Warband save files. Useful for the
  layout of parties, troops and the map, and as Python we can follow.

## Most useful structures found so far (WarbandLib)

- `rgl::string` (rgl_string.h): `int cursor; char *buffer; size_t buffer_length;
  size_t str_length; char static_buffer[128];`. To read one: follow `buffer`, read
  `str_length` bytes (it can point at `static_buffer` for short strings).
- `wb::game` (game.h): the big global game object. It holds `cur_menu_no`, `cur_menu_text`
  (the current game menu's text with variables already filled in), `main_party_no`,
  `player_troop_no`, `paused`, `context_menu_items[50]`, and more.
- `wb::menu` / `wb::menu_item` (menu.h): a menu's text, id, flags and items (each with text,
  id and conditions).
- `wb::conversation_manager` (conversation.h): `speaker_text` (what the NPC just said),
  `num_options`, and `partner_options[1024]` (your reply choices, each with its text),
  plus the conversation partner's troop, party and agent numbers.
- `rgl addresses: window_manager_DisplayMessage`: the function behind every on-screen
  message line ("You received 50 denars", and so on). Hooking it would speak all game messages.
- party.h, agent.h and mission.h: for the campaign map (parties and their positions) and
  battles (agents = every soldier, with position, team and health).

## Plan once the game is installed (passive first; don't steal keyboard focus)

1. Record the exe's name, size, CRC and version, and confirm it's 32-bit.
2. Read the module's text files to see the menu and dialogue formats (and check that they
   match the Module System's).
3. Check rgl_log.txt and anything else the game writes, as a possible speech bridge.
4. Find the global `game` object in memory (by searching for known strings such as
   `module_name` or `savegame_name`, then comparing the layout with game.h).
5. First milestone: speak the current game menu (text plus the highlighted option), then
   conversations.
