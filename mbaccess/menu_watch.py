"""Speaking game menus (the town, village and event menus) and choosing options by keyboard.

We poll: every tick we read the current menu number, its text (with the
game's variables already filled in, e.g. "You are in Praven") and the
visible option buttons, and speak when any of them changes.

Where the buttons come from (found 2026-10-05, see docs/findings.md): the
engine keeps 32 "game windows" in a global array; number 18 is the menu
window. It owns 16 button slots; the ones in use have text and no "hidden"
flag. A separate list of open windows tells us whether the menu window is
actually showing (it's on top), so stale buttons are never read.

The game's menus are mouse-only, so we keep our own cursor: Up/Down move it
and speak the option, Enter clicks the option's button for the player.
"""
import struct

from . import keys
from . import text as text_mod
from .mem import ReadError

MENU_WINDOW = 18
HIDDEN = 0x1
# Click a little right of the button's left edge and halfway up its row.
CLICK_DX, CLICK_DY = 0.1, 0.02


class Option:
    def __init__(self, text, x, y):
        self.text, self.x, self.y = text, x, y

    def __repr__(self):
        return f"Option({self.text!r}, {self.x}, {self.y})"


class MenuWatcher:
    def __init__(self, reader, game_address, offsets, menus, say, screen=None, clicker=None):
        self.reader = reader
        self.game = game_address
        self.offsets = offsets
        self.screen = screen or {}   # the profile's "screen" addresses
        self.menus = menus
        self.say = say
        self.clicker = clicker       # function(x, y) that clicks; None = can't click
        self.last = None
        self.options = []
        self.cursor = 0

    @property
    def enabled(self):
        return self.offsets.get("cur_menu_no") is not None and \
            self.offsets.get("cur_menu_text") is not None

    @property
    def reads_buttons(self):
        return self.screen.get("game_windows") is not None

    # --- reading ---------------------------------------------------------

    def top_window(self):
        """Number of the window on top of the open-window list (a std::deque<int>)."""
        r, base = self.reader, self.screen["open_windows"]
        block_map, map_size, first, count = struct.unpack("<IIII", r.read(base, 16))
        if count == 0 or map_size == 0:
            return None
        index = first + count - 1           # the last one pushed is on top
        block = r.ptr(block_map + 4 * ((index // 4) % map_size))  # 4 ints per block
        return r.i32(block + 4 * (index % 4))

    def read_options(self):
        s, r = self.screen, self.reader
        window = r.ptr(s["game_windows"] + 4 * MENU_WINDOW)
        options = []
        for slot in range(s["menu_button_slots"]):
            button = r.ptr(window + s["menu_buttons"] + 4 * slot)
            if r.u32(button + s["widget_flags"]) & HIDDEN:
                continue
            label = text_mod.clean(r.rgl_string(button + s["widget_text"]))
            if not label:
                continue
            x, y = struct.unpack("<ff", r.read(button + s["widget_position"], 8))
            options.append(Option(label, x, y))
        options.sort(key=lambda o: -o.y)    # top of the screen first
        return options

    def read_state(self):
        number = self.reader.i32(self.game + self.offsets["cur_menu_no"])
        body = self.reader.rgl_string(self.game + self.offsets["cur_menu_text"])
        return number, body

    # --- speaking --------------------------------------------------------

    def describe(self, number, body):
        parts = [text_mod.clean(body)]
        if self.reads_buttons:
            if self.options:
                parts.append(self.option_text())
        elif 0 <= number < len(self.menus):
            # Without the button addresses, list every option the menu could
            # show (some may be hidden in-game).
            options = [text_mod.clean(i.text) for i in self.menus[number].items]
            if options:
                parts.append("Options: " + "; ".join(o for o in options if o))
        return "\n".join(p for p in parts if p)

    def option_text(self):
        return f"{self.options[self.cursor].text}, {self.cursor + 1} of {len(self.options)}"

    # --- the loop --------------------------------------------------------

    def poll(self, pressed=()):
        if not self.enabled:
            return
        try:
            if self.reads_buttons:
                if self.top_window() != MENU_WINDOW:
                    self.last = None    # speak the menu again when it comes back
                    return
                options = self.read_options()
            else:
                options = []
            state = self.read_state() + (tuple(o.text for o in options),)
        except ReadError:
            return  # mid-update or loading; try again next tick
        if state != self.last:
            self.last = state
            self.options, self.cursor = options, 0
            self.say(self.describe(*state[:2]))
            return
        self.handle_keys(pressed)

    def handle_keys(self, pressed):
        if not self.options:
            return
        for key in pressed:
            if key in (keys.UP, keys.DOWN, keys.HOME, keys.END):
                n = len(self.options)
                self.cursor = {keys.UP: (self.cursor - 1) % n, keys.DOWN: (self.cursor + 1) % n,
                               keys.HOME: 0, keys.END: n - 1}[key]
                self.say(self.option_text())
            elif key == keys.RETURN and self.clicker:
                option = self.options[self.cursor]
                self.clicker(option.x + CLICK_DX, option.y + CLICK_DY)
