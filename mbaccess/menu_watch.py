"""Speaking the game's screens and using them by keyboard.

That covers the main menu, the game menus (town, village and event menus)
and form screens like Options. We poll: every tick we check which screen is
showing, read what's on it, and speak when it changes.

Where things come from (see docs/findings.md): the engine keeps 32 "game
windows" in a global array, and a list of open windows tells us which one is
on top, so stale widgets are never read. The profile's screen["windows"]
says how to read each window number:
- "buttons"/"slots": a table of option buttons (main menu = 4, game menus =
  18). Game menus also have "menu_text", read from the campaign object.
- "tree": walk the window's whole widget tree (form.py), for screens with
  labels, checkboxes, spinners and sliders.

The game is mouse-only, so we keep our own cursor: Up/Down/Home/End move it,
Enter or Space presses, Left/Right change spinners and sliders, and we move
the real mouse to do it. Rows scrolled out of view are still readable (the
memory has them); before pressing one, we turn the mouse wheel until it's
in view.
"""
import struct

from . import keys
from . import text as text_mod
from .form import Item, TreeReader
from .mem import ReadError

HIDDEN = 0x1
# Click a little right of the button's left edge and halfway up its row.
DEFAULT_CLICK = (0.1, 0.02)
ROOT = 0x13c            # where a window's root widget usually is
ROOT_SEARCH = 0x1000    # how far into a window to look for it otherwise
SCROLL_TOP = 0.64       # top edge of a scrolling list (Options); bottom is read
WHEEL_STEP = 0.062      # one wheel notch moves a list this far
MAX_SCROLL_TRIES = 20
ACTION_KEYS = {keys.RETURN: "activate", keys.SPACE: "activate",
               keys.LEFT: "left", keys.RIGHT: "right"}


class MenuWatcher:
    def __init__(self, reader, game_address, offsets, menus, say, screen=None, mouse=None):
        self.reader = reader
        self.game = game_address     # the campaign object; None at the main menu
        self.offsets = offsets
        self.screen = screen or {}   # the profile's "screen" addresses
        # JSON keys are always strings, so turn "18" back into 18.
        self.windows = {int(k): v for k, v in self.screen.get("windows", {}).items()}
        self.tree = TreeReader(reader, self.screen)
        self.menus = menus
        self.say = say
        self.mouse = mouse           # has hover, click(x, y), drag(x1, x2, y), wheel(x, y, notches)
        self.last = None
        self.options = []
        self.cursor = 0
        self.pending = None          # (key, tries): an action waiting for scrolling
        self.root_offsets = {}       # window number -> where its root widget is

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

    def window(self, number):
        return self.reader.ptr(self.screen["game_windows"] + 4 * number)

    def root(self, number):
        """A window's root widget. It's usually at +0x13c, but not always
        (Load Game: +0xbf0), so search the window for an object of the root
        class and remember where it was."""
        window = self.window(number)
        offset = self.root_offsets.get(number, ROOT)
        if self.tree.kind_at(window + offset) == "root":
            return self.reader.ptr(window + offset)
        for offset in range(0, ROOT_SEARCH, 4):
            if self.tree.kind_at(window + offset) == "root":
                self.root_offsets[number] = offset
                return self.reader.ptr(window + offset)
        return self.reader.ptr(window + ROOT)

    def read_options(self, number, config):
        s, r = self.screen, self.reader
        window = self.window(number)
        click = tuple(config.get("click", DEFAULT_CLICK))
        options = []
        for slot in range(config["slots"]):
            button = r.ptr(window + config["buttons"] + 4 * slot)
            if r.u32(button + s["widget_flags"]) & HIDDEN:
                continue
            label = text_mod.clean(r.rgl_string(button + s["widget_text"]))
            if not label:
                continue
            x, y = struct.unpack("<ff", r.read(button + s["widget_position"], 8))
            options.append(Item("option", label, x, y, click=click))
        options.sort(key=lambda o: -o.y)    # top of the screen first
        return options

    def read_state(self):
        number = self.reader.i32(self.game + self.offsets["cur_menu_no"])
        body = self.reader.rgl_string(self.game + self.offsets["cur_menu_text"])
        return number, body

    def read(self):
        """What's showing now: (state, items, window config), or None.

        state is a tuple we compare with last tick's to notice a new screen;
        it leaves out values (a ticked box), which are spoken on their own.
        """
        if not self.reads_buttons:
            # No button addresses for this game version yet: menu text only.
            if not (self.enabled and self.game):
                return None
            number, body = self.read_state()
            return ("menu", number, body), [], {"menu_text": True}
        top = self.top_window()
        if top is None or not 0 <= top < 32:
            return None
        # Windows we haven't described get the tree reader: any screen built
        # from known widget kinds then reads without extra work.
        config = self.windows.get(top, {"tree": True})
        if config.get("tree"):
            items = self.tree.items(self.root(top), config.get("scroll_top", SCROLL_TOP),
                                    config.get("layout"))
            key = self.tree.key
            for item in items:      # each Options tab is its own window
                if item.kind == "tab" and item.label == config.get("selected_tab"):
                    item.value = "selected"
            if not items:
                return None     # nothing readable (e.g. the 3D scene)
        else:
            items = self.read_options(top, config)
            key = tuple(i.label for i in items)
        number, body = None, ""
        if config.get("menu_text"):
            if not (self.enabled and self.game):
                return None
            number, body = self.read_state()
        return (top, number, body, key), items, config

    # --- speaking --------------------------------------------------------

    def describe(self, number, body, config):
        parts = [text_mod.clean(body)]
        if self.reads_buttons:
            if self.options:
                parts.append(self.option_text())
        elif number is not None and 0 <= number < len(self.menus):
            # Without the button addresses, list every option the menu could
            # show (some may be hidden in-game).
            options = [text_mod.clean(i.text) for i in self.menus[number].items]
            if options:
                parts.append("Options: " + "; ".join(o for o in options if o))
        return text_mod.spoken(config.get("name", ""), *parts)

    def option_text(self):
        return f"{self.options[self.cursor].spoken()}, {self.cursor + 1} of {len(self.options)}"

    # --- the loop --------------------------------------------------------

    def poll(self, pressed=()):
        try:
            found = self.read()
        except ReadError:
            return  # mid-update or loading; try again next tick
        if found is None:
            self.last, self.options, self.pending = None, [], None
            return
        state, items, config = found
        if state != self.last and not self.same_screen(state, items):
            self.last, self.pending = state, None
            self.options, self.cursor = items, 0
            self.say(self.describe(state[1], state[2], config))
            return
        self.last = state
        # Same screen: a value may have changed (we ticked a box, moved a slider).
        old = self.options[self.cursor] if self.options else None
        self.options = items
        if not items:
            return
        # Follow the item itself, not its place in the list: rows can shift
        # for a moment while the list scrolls.
        same = [n for n, i in enumerate(items) if old and old.widget and i.widget == old.widget]
        self.cursor = same[0] if same else min(self.cursor, len(items) - 1)
        new = items[self.cursor]
        if old and new.label == old.label and new.value != old.value:
            if new.kind == "edit" and new.value.startswith(old.value):
                self.say(new.value[len(old.value):])   # echo what was typed
            else:
                self.say(new.value or "blank")
        if self.pending:
            key, tries = self.pending
            self.pending = None
            self.act(key, tries)
        self.handle_keys(pressed)

    def same_screen(self, state, items):
        """The same window still showing the item we're on: the screen only
        grew or shrank (spending a skill point adds a button). Keep our place
        instead of starting over."""
        if not (self.last and self.options and state[0] == self.last[0]):
            return False
        here = self.options[self.cursor].widget
        return bool(here) and any(i.widget == here for i in items)

    def handle_keys(self, pressed):
        if not self.options:
            return
        for key in pressed:
            if key in (keys.UP, keys.DOWN, keys.HOME, keys.END):
                n = len(self.options)
                self.cursor = {keys.UP: (self.cursor - 1) % n, keys.DOWN: (self.cursor + 1) % n,
                               keys.HOME: 0, keys.END: n - 1}[key]
                self.pending = None
                self.say(self.option_text())
                self.hover()
            elif key in ACTION_KEYS:
                if key == keys.SPACE and self.options[self.cursor].kind == "edit":
                    continue    # a space typed into the box, not a press
                self.act(ACTION_KEYS[key])

    def hover(self):
        """Put the mouse over the cursor's item, so the game highlights it
        (and plays its hover sound) as it would for a sighted player."""
        item = self.options[self.cursor]
        if self.mouse is not None and item.kind != "text" and item.visible():
            self.mouse.hover(item.x + item.click[0], item.y + item.click[1])

    def act(self, key, tries=0):
        item = self.options[self.cursor]
        action = item.action(key)
        if action is None or self.mouse is None:
            return
        if not item.visible():
            # Scrolled out of view: turn the wheel toward it and try again
            # next tick, once the game has moved the list.
            if tries < MAX_SCROLL_TRIES:
                bottom, top = item.scroll
                notches = -1 if item.y < bottom else 1   # negative = scroll down
                self.mouse.wheel(item.x + item.click[0], (bottom + top) / 2, notches)
                self.pending = (key, tries + 1)
            return
        if action[0] == "click":
            # Menu options get a quick click (see click.click).
            self.mouse.click(*action[1:], hold=0 if item.kind == "option" else 0.08)
        else:
            self.mouse.drag(*action[1:])
