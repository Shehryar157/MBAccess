# Findings diary

Read this before searching memory or the reference again. Add each new finding with its
date, how it was found and whether it's verified.

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

## With Fire & Sword (mb_wfas.exe 5197312 bytes, 32-bit, module "Ogniem i Mieczem", 298 menus)

Nothing verified in memory yet. Try the same techniques: search for menu 0's text
("Welcome, adventurer, to Mount and Blade: With Fire and Sword").

## Launcher (both games, verified 2026-10-05)

- WFS launcher: #32770 'Mount&Blade With Fire and Sword', same control IDs as Warband except no 1202 (delete module). It can take 30+ s to appear on first start.
- The module combo box has no window text; read it with CB_GETCURSEL + CB_GETLBTEXT. WFS's combo showed 'Native' although the only module folder is 'Ogniem i Mieczem' (check this).
- GetGUIThreadInfo(launcher thread).hwndFocus gives the focused control without needing foreground; WM_NEXTDLGCTL (0x28) moves focus like Tab.
- mbaccess/launcher.py speaks the labels (run.py polls it). The user wants the launcher kept, just made accessible: no auto-skip.

## Menu widgets (Warband 1.174, partly verified 2026-10-05)

- Each on-screen menu option is an rgl::widget whose text rgl::string (T) holds the option text. Fields relative to T, matching reference/wse/WarbandLib/rgl_widget.h: size T-100 (vec2), absolute_position T-92 (vec2: x, y), relative_position T-84, flags T-60 (0x1 hidden, 0x2 disabled), highlighted byte T-6, dynamic byte T-5. VERIFIED: options stack downward as y falls by 0.04 (welcome menu: Continue y=0.22, Go back y=0.18).
- NOT verified: container_widget/parent_widget at T+0xb4/T+0xb8 read 0, so that guess is wrong for 1.174.
- Stale widgets keep their text after a menu closes (an old 'Male' and a 3rd 'Go back' at y=0.14 lingered), and widgets move to new addresses when a menu rebuilds. So text alone can't tell which buttons are live. Next idea (interrupted): search memory for pointers into [T-0x300, T) to find each widget's start and the container's child_widgets vector (stl::vector of widget*; container_widget = widget + container_name string + child vector). Pointer scan over 700 MB takes minutes in pure Python, so use bytes.find on packed values or numpy.
- Screen mapping (rough): on a 1280x720 capture, Continue was at (426, 482) and Go back at (426, 518). x is centred; absolute x 0.015 is relative to a scroll container.
- Plan for keyboard menus: list the live option widgets (y order), our own cursor on the arrow keys (read with GetAsyncKeyState while the game window is in front), speak the option, and on Enter click its screen position (SetCursorPos + mouse_event after focus).

## Menu window and live buttons (Warband 1.174, VERIFIED 2026-10-05)

- Found by shape, not by the headers: a run of 32 pointers in .data, each to an object of a different class (vtables in .rdata 0x7be000-0x85e000) = game_screen.game_windows[32] at **0xdd9af0**. The exe's .data section is huge (0x85e000-0x2db4000) and some windows live inside it, so scans must cover all of it. The 1.153 'type at +4' guess did NOT hold.
- game_windows[18] = the menu window (gwt_menu). Its button table: **16 widget pointers at window+0x178**. Live buttons have text and flags bit 0x1 clear; the spares are blank and hidden. This solves the stale-widget problem.
- Widget fields used (relative to the widget start; text rgl::string at +0x1f8): absolute position +0x19c (vec2, engine coordinates: x from the left, y UP from the bottom, screen 1.0 x 0.75), flags +0x1bc, parent pointer +0x2a8. Chain: button -> 'menu_buttons' -> 'menu_buttons_s' -> 'menu'. The 'absolute position' is truly absolute (the containers sit at about 0.01, 0.02 and the button already includes that).
- Menu window +0x200 -> 'menu_text' container, +0x204 -> 'menu_buttons_s', +0x13c -> 'menu' root.
- Open windows: std::deque<int> right after the array; its map pointer, map size, first index and count are at **0xdd9b80**, with 4 ints per block. Top of the stack = the last element. On the welcome menu: count 1, value 18.
- Clicking: engine (x, y) -> client pixels (x*W, H - y/0.75*H). We click at (x+0.1, y+0.02): Continue y=0.22 and Go back y=0.18 match earlier clicks that worked. Dry run in the live game read 'Continue..., 1 of 2' correctly. The Enter click is NOT yet tested by the user.
- Code: mbaccess/menu_watch.py (read_options, top_window, cursor), keys.py, click.py; addresses in profiles/warband.json 'screen'.
- Both exes import DINPUT8.dll, so the CFC proxy loader idea applies (built 32-bit).

## Auto-start loader (2026-10-05, installed; first real launch NOT yet tested)

- loader/dinput8.c (copied from CFCAccess, names changed) built 32-bit: zig cc -target x86-windows-gnu. In 32-bit the .def must name the stdcall-decorated functions (Proxy_DirectInput8Create@20, DllGetClassObject@12, the others @0). Verified with pefile: machine 0x14c, 6 plain export names.
- python tools/build_loader.py install|uninstall finds both games through Steam's libraryfolders.vdf and writes <game>\MBAccess.txt (pythonw run.py --with-game). It writes <game>\MBAccess_loader.log; the mod logs to logs\mbaccess.log. Mutex: MBAccess.SingleInstance.
- PowerShell 5 Set-Content -Encoding utf8 adds a BOM; strip it (Python copes, other tools may not).

## Main menu and other windows (Warband 1.174, VERIFIED 2026-10-05)

- Main menu = game_windows[**4**] (gwt_initial). Same layout as the menu window: button table at window+0x178. 8 buttons (Play Tutorial, Start a New Game, Load Game, Multiplayer, Custom Battle, Options, Credits, Exit; x 0.05, y 0.48 down to 0.20 in 0.04 steps, but the table order isn't screen order, so sort by y). Slot 9 (+0x198) is the "v1.174" label: excluded by slots = 8.
- Hover test: the highlighted byte (text - 6, i.e. widget +0x1f2) turns 1 under the mouse. SetCursorPos alone (no click) is a safe way to test click spots. Main menu buttons react from x+0.08 to x+0.22 and y+0 to y+0.02; x+0.03 misses. We click at (x+0.15, y+0.012). Widget "size" (position - 8) reads (1, 1): a scale, not a size.
- At the main menu the menu window's button table (window 18) points at freed widgets reused by the main menu: proof that only the top window may be trusted.
- Window 2 (and 3) = loading screen: +0x140 -> "Finished." label, +0x50c -> the loading hint ("Hint #5: ..."). Not used yet; a cheap next win.
- Window 6 holds pointers to the main menu buttons at +0x5a8 and window 17 at +0x4d8: probably stale or shared containers, not checked.
- click.click doesn't bring the game to the front. Fine when the user presses Enter in the game; for tests from outside, call CFCAccess tools/win.py focus() first.
- Code: profile screen["windows"] maps window number -> {name, buttons, slots, click, menu_text}. Adding a screen with the same button-table shape is one JSON entry.
