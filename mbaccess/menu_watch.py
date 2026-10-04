"""Speaking the game's button screens and choosing options by keyboard.

That covers the main menu and the game menus (town, village and event
menus). We poll: every tick we check which screen is showing, read its
visible buttons (and, for game menus, the menu text with the game's
variables already filled in, e.g. "You are in Praven"), and speak when
anything changes.

Where the buttons come from (found 2026-10-05, see docs/findings.md): the
engine keeps 32 "game windows" in a global array; number 4 is the main menu
and number 18 the game menu window. Each owns a table of button slots; the
ones in use have text and no "hidden" flag. A separate list of open windows
tells us which window is on top, so stale buttons are never read. The
profile's screen["windows"] says, per window number, where its button table
is and how many slots it has.

The game's menus are mouse-only, so we keep our own cursor: Up/Down move it
and speak the option, Enter clicks the option's button for the player.
"""
import struct

from . import keys
from . import text as text_mod
from .mem import ReadError

HIDDEN = 0x1
# Click a little right of the button's left edge and halfway up its row.
DEFAULT_CLICK = (0.1, 0.02)


class Option:
    def __init__(self, text, x, y):
        self.text, self.x, self.y = text, x, y

    def __repr__(self):
        return f"Option({self.text!r}, {self.x}, {self.y})"


class MenuWatcher:
    def __init__(self, reader, game_address, offsets, menus, say, screen=None, clicker=None):
        self.reader = reader
        self.game = game_address     # the campaign object; None at the main menu
        self.offsets = offsets
        self.screen = screen or {}   # the profile's "screen" addresses
        # JSON keys are always strings, so turn "18" back into 18.
        self.windows = {int(k): v for k, v in self.screen.get("windows", {}).items()}
        self.menus = menus
        self.say = say
        self.clicker = clicker       # function(x, y) that clicks; None = can't click
        self.last = None
        self.options = []
        self.cursor = 0
        self.click_offset = DEFAULT_CLICK

    def set_game(self, address, menus):
        """A campaign started or a save was loaded: the game object moved."""
        self.game, self.menus = address, menus

    @property
    def enabled(self):
        """Can we read game menu text (needs offsets found by the discovery tool)?"""
        return self.offsets.get("cur_menu_no") is not None and \
            self.offsets.get("cur_menu_text") is not None

    @property
    def reads_buttons(self):
        return self.screen.get("game_windows") is not None and bool(self.windows)

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

    def read_options(self, number, config):
        s, r = self.screen, self.reader
        window = r.ptr(s["game_windows"] + 4 * number)
        options = []
        for slot in range(config["slots"]):
            button = r.ptr(window + config["buttons"] + 4 * slot)
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

    def read(self):
        """What's showing now: (state, options, window config), or None.

        state is a tuple we compare with last tick's to notice changes.
        """
        if not self.reads_buttons:
            # No button addresses for this game version yet: menu text only.
            if not (self.enabled and self.game):
                return None
            number, body = self.read_state()
            return ("menu", number, body), [], {"menu_text": True}
        top = self.top_window()
        config = self.windows.get(top)
        if config is None:
            return None
        options = self.read_options(top, config)
        number, body = None, ""
        if config.get("menu_text"):
            if not (self.enabled and self.game):
                return None
            number, body = self.read_state()
        return (top, number, body, tuple(o.text for o in options)), options, config

    # --- speaking --------------------------------------------------------

    def describe(self, number, body, config):
        parts = [config.get("name", ""), text_mod.clean(body)]
        if self.reads_buttons:
            if self.options:
                parts.append(self.option_text())
        elif number is not None and 0 <= number < len(self.menus):
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
        try:
            found = self.read()
        except ReadError:
            return  # mid-update or loading; try again next tick
        if found is None:
            self.last, self.options = None, []  # speak the screen again when it comes back
            return
        state, options, config = found
        if state != self.last:
            self.last = state
            self.options, self.cursor = options, 0
            self.click_offset = tuple(config.get("click", DEFAULT_CLICK))
            self.say(self.describe(state[1], state[2], config))
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
                dx, dy = self.click_offset
                self.clicker(option.x + dx, option.y + dy)
