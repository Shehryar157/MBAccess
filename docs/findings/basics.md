## Warband 1.174 (Steam, mb_warband.exe 5362688 bytes, 32-bit, no ASLR: base 0x400000)

### Verified 2026-10-05

- `[0x8b82a0]` = cur_game, the wb::game object. It exists only once a campaign has started
  (new game or load); at the main menu it isn't valid yet.
- wb::game layout:
  - `+0xa0` module_name ("Native"). Same as the 1.153 headers.
  - After module_name: class_names ("Infantry", "Archers", "Cavalry", "Unnamed 1".."6").
  - `+0x714` cur_menu_text, an rgl::string with the variables already filled in.
  - `+0x1436c` cur_menu_no (int). Index into menus.txt: menu_start_game_0 = 0,
    menu_start_game_1 (gender) = 7.
- rgl::string layout as in the reference: cursor, buffer, capacity (128 when static), length,
  static_buffer[128]. 144 bytes.
- `[0x8b8528]` points at the loaded menus array; menus[0] begins with its text rgl::string.
  Not verified further.
- On-screen widget pool: widgets every 0x2e8 bytes, each with a text rgl::string. The text box
  and the visible buttons appeared next to each other ("Welcome..." then "Continue..."), but
  "Go back" (which was visible) wasn't in the next slot. Needs work: this is how we'll read the
  visible options and the hover highlight (hovered option shows green).
- Other rgl::strings holding "Native": 0xdcf728 (a lone global) and 0x2dab5d0/0x2dab660 (the
  module settings object, next to "Modules/Native/"). Not the game object.

### Techniques that worked

- Find a struct by a known string, then find the global pointer to it: search the exe's
  0x400000-0xE00000 range for dwords pointing a little before the string.
- Find an int field by before/after snapshots across a menu change. Snapshot the whole
  object (0x40000 bytes), not just 0x10000: cur_menu_no is at +0x1436c.
- A full memory search for a string takes about 4 s (700 MB). Do it once, not in a loop.

### Environment

- Launcher: a #32770 dialog with image buttons (no text, so NVDA can't read them). Control IDs:
  1029 Play, 1055 Configure, 1131 Cancel, 1056 module combo box. PostMessage BM_CLICK
  (0x00F5) presses one without taking focus.
- Steam's window hung ("Steamwebhelper is not responding"); starting the exe directly works.
- Screenshots: turn off NVDA Screen Curtain, and run windowed
  (Documents\Mount&Blade Warband\rgl_config.txt: start_windowed = 1, backup in .bak).
  CFCAccess tools/win.py screenshot() (PrintWindow) works on the windowed game; focus() is
  needed before clicks. Game client area 1898x922; the screenshot comes out 1280x720, so
  scale the coordinates.
- Main menu at 1280x720: "Start a New Game" at (244, 288). Welcome menu: Continue (426, 482).
  Gender menu: Male, Female, then Go back (426, 556).

### Responsiveness (measured 2026-10-06)

- One memory read costs about 0.1 ms whatever its size (the trip to Windows, plus pymem). A main
  loop pass is about 5 ms on menus and conversations; form screens were the slow part (Options 54
  ms, character screen about 76 ms) because the tree walker makes hundreds of small reads.
- Fix: Reader.cached() fetches whole 4 KB pages and keeps them for one screen read
  (MenuWatcher.read). Options: 54 -> 28 ms, same items. The rest is mostly Python work in the
  tree walker (text.clean, form.control): the next thing to speed up if needed.
- Keys come from a low-level keyboard hook (keys.HookKeyWatcher): no lost presses, the loop
  wakes the moment a key arrives, arrows auto-repeat, and repeats that pile up while busy count
  once.
- Clicks: menu options use a quick click (0.06 s); other screens a held one (0.18 s), because
  Custom Battle missed quick clicks. Profile "quick_click": true switches a screen to the quick
  one. Verified: Esc menu (window 5). Character screen: a quick click on Statistics closed the
  screen or missed (unclear), so it stays slow until tested with skill points to spend.
- Character screen has no "-" or Reset buttons: points can't be taken back (verified 2026-10-06).
- Later 2026-10-06: a read costs about 33 microseconds direct (ReadProcessMemory via ctypes) vs
  35 through pymem: nearly all of it is Windows, so cutting the NUMBER of reads (page cache) is
  what matters. text.clean is memoized (lru_cache); the launcher check runs twice a second
  unless the launcher is open. Scene screen poll 3.1 -> 1.3 ms.
