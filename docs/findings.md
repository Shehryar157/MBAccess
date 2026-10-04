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
