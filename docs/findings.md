# Findings diary: index

The diary is split by topic in docs/findings/ so a session reads only what its task needs.

**How to use it:** always read basics.md (the game object, the techniques that worked, the
environment: windowed mode, screenshots, coordinates). Then pick files from the task's words
using the table below. If the task touches a screen or widget and you're not sure which file
covers it, read menus.md and screens.md: most work builds on them. Don't read everything.

| File | Covers | Read it when the task mentions |
|---|---|---|
| basics.md | cur_game, menu text and number, rgl::string, memory search techniques, windowed mode, screenshots, click coordinates | always |
| menus.md | game_windows array, open-window deque (top window), menu and main menu button tables, clicking and hover, window numbers 2-6, 17, 18 | game menus, main menu, Enter/clicks, which screen is on top, a new window number |
| screens.md | widget tree walker, widget classes (vtables), checkboxes, sliders, spinners, drop-downs, scrolling, Options/Video/Controls (13-15), Load game, Custom battle, Character, Esc menu, party screen, party skills (troops and parties arrays, troop skills), face editor | any form-like screen, Options, settings, character creation, party, troops, skills, a widget kind, scrolling |
| inventory.md | inventory window, cells, tooltip global, picking up and putting down, item kinds table, right-click actions, F9 help | inventory, items, trading, looting, tooltips, help keys |
| messages.md | message_log vector, message_queue, categories | game messages, message buffers, notifications |
| launcher.md | launcher dialog control IDs, combo box | the launcher, Play/Configure |
| loader.md | dinput8 proxy loader, build and install, logs | auto-start, the loader DLL, installing |
| conversations.md | conversation window 12, conversation manager, skills array in memory, reaching a conversation without walking | conversations, dialogue, skill names, replacing text files with memory |
| map.md | world map: parties (blocks of 16), positions, flags, terrain, factions, axes | the map, travel, parties, terrain, kingdoms, radar |
| scenes.md | mission and scene objects, collision shapes (walls), agents (player, horses), facing angle, wall finder, scanner, prompts and use cue, dismounting, reach, turning, tracking beacon, scene key map | walking, scenes, walls, beeps, agents, battles, towns, scanner, prompts, mounting, turning, sounds |
| wfs.md | With Fire & Sword status | anything about WFS or porting to it |

**Adding findings:** put each one in the file for its topic, with its date, how it was found
and whether it's verified. A new topic gets a new file and a row in this table.
