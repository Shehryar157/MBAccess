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
Enter or Space presses, Left/Right change spinners and sliders, Shift+Enter
right-clicks (an item's special action, like reading a book), and we move
the real mouse to do it. Rows scrolled out of view are still readable (the
memory has them); before pressing one, we turn the mouse wheel until it's
in view.
"""
import struct
import time

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
GRID_ROW = 0.02         # cells closer than this in height are on the same row
HEADING_GAP = 0.15      # a text this far above a grid's top row is its headingPICK_MARGIN = 0.01    # a drop-down row lower than this is off the bottom of the screen
PICK_WAIT = 0.3       # seconds for a drop-down list to open
TIP_LINES, TIP_STRIDE = 12, 0x90   # tooltip: rgl::string lines
HOLD_WAIT = 0.4       # seconds for a click on a cell to pick up or put down
TIP_WAIT = 0.4        # seconds to wait for a tooltip before calling a cell empty
# Conversation manager (reference/wse/WarbandLib/conversation.h, verified on
# 1.174): current sentence, number of replies, then two tables of 1024
# options (156 bytes each), a bool, and the partner's line.
CONV_SENTENCE, CONV_NUM_OPTIONS = 28, 36
CONV_SPEAKER_TEXT = 40 + 2 * 1024 * 156 + 4
ACTION_KEYS = {keys.RETURN: "activate", keys.SPACE: "activate",
               keys.LEFT: "left", keys.RIGHT: "right"}


class MenuWatcher:
    def __init__(self, reader, game_address, offsets, menus, say, screen=None, mouse=None,
                 page=None, settings=None, party_skills=None):
        self.reader = reader
        self.party_skills = party_skills   # party_skills.PartySkills, if the profile has it
        self.skills = []                   # the module's skills (modfiles.Skill)
        self.page = page             # the Accessibility tab (access_page.AccessPage), if any
        self.settings = settings
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
        self.tip_wait = None         # (since, tooltip before, widget): waiting to speak a cell
        self.config = {}
        self.hold_check = None       # (since, item held before): after clicking a cell
        self.carried = []            # keys from a tick whose read failed
        self.announce = ""           # a section's name, said before the next item
        self.section_memory = {}     # section key -> widget we were on there
        self.grid_headings = {}      # grid group -> the heading above it

    def set_game(self, address, menus, skills=()):
        """A campaign started or a save was loaded: the game object moved."""
        self.game, self.menus, self.skills = address, menus, list(skills)

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

    def read_conversation(self, number, config):
        """The conversation screen: (sentence number, spoken text, items).

        The words come from the engine's conversation manager (a fixed
        address, screen["conversation"]): the partner's line and how many
        replies there are. The reply buttons sit in the window's button table
        like a game menu's; with no replies the game waits for a click, so we
        offer that as "Continue"."""
        r, s = self.reader, self.screen
        cm = s["conversation"]
        sentence, count = r.i32(cm + CONV_SENTENCE), r.i32(cm + CONV_NUM_OPTIONS)
        window = self.window(number)
        name = text_mod.clean(r.rgl_string(r.ptr(window + config["speaker"]) + s["widget_text"]))
        body = f"{name} {r.rgl_string(cm + CONV_SPEAKER_TEXT)}".strip()
        items = self.read_options(number, dict(config, slots=min(max(count, 0), config["slots"])))
        for item in items:
            item.scroll = tuple(config["scroll"]) if "scroll" in config else None
        if not items:
            label = r.ptr(window + config["continue"])
            if not r.u32(label + s["widget_flags"]) & HIDDEN:
                x, y = struct.unpack("<ff", r.read(label + s["widget_position"], 8))
                items = [Item("option", "Continue", x, y, click=(0.1, 0.01))]
        return sentence, body, items

    def read_state(self):
        number = self.reader.i32(self.game + self.offsets["cur_menu_no"])
        body = self.reader.rgl_string(self.game + self.offsets["cur_menu_text"])
        return number, body

    def read(self):
        """What's showing now: (state, items, window config), or None.

        state is a tuple we compare with last tick's to notice a new screen;
        it leaves out values (a ticked box), which are spoken on their own.
        One cached block: the whole screen comes from one snapshot of memory.
        """
        cached = getattr(self.reader, "cached", None)
        if cached is None:          # a test's stand-in reader
            return self.read_screen()
        with cached():
            return self.read_screen()

    def read_screen(self):
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
        if config.get("conversation"):
            number, body, items = self.read_conversation(top, config)
            return (top, number, body, tuple(i.label for i in items)), items, config
        if config.get("tree"):
            items = self.tree.items(self.root(top), config.get("scroll_top", SCROLL_TOP),
                                    config.get("layout"))
            key = self.tree.key
            for item in items:      # each Options tab is its own window
                if item.kind == "tab" and item.label == config.get("selected_tab"):
                    item.value = "selected"
            if not items:
                return None     # nothing readable (e.g. the 3D scene)
            if config.get("party_skills"):
                items = self.with_party_skills(items)
            if self.page:
                items, key, config = self.with_access_tab(items, key, config)
        else:
            items = self.read_options(top, config)
            key = tuple(i.label for i in items)
        number, body = None, ""
        if config.get("menu_text"):
            if not (self.enabled and self.game):
                return None
            number, body = self.read_state()
        return (top, number, body, key), items, config

    def with_access_tab(self, items, key, config):
        """On an Options screen, add our Accessibility tab after the game's
        tabs. While it's open, list the tabs, our settings, then the game's
        own buttons (Done and so on, which still work). The game tab's
        settings are left out, as switching tabs hides them for a sighted player."""
        tabs = [i for i in items if i.kind == "tab"]
        if not (config.get("selected_tab") and tabs):
            self.page.open = False      # left the Options screens
            return items, key, config
        if not self.page.open:
            last = items.index(tabs[-1])
            return items[:last + 1] + [self.page.tab()] + items[last + 1:], key, config
        for t in tabs:
            t.value = ""                # the game's tab is still selected underneath
        # Buttons outside the scrolling settings list belong to the whole screen.
        buttons = [i for i in items if i.kind == "button" and i.scroll is None]
        items = tabs + [self.page.tab()] + self.page.items() + buttons
        # start: the cursor begins on the first setting, not on a tab.
        return items, ("accessibility",), dict(config, name="Accessibility", start=len(tabs) + 1)

    def with_party_skills(self, items):
        """The party screen draws its party skills without keeping the text,
        so put our rebuilt lines right after its "Party Skills" heading."""
        if not (self.party_skills and self.game and self.skills):
            return items
        heading = next((n for n, i in enumerate(items)
                        if i.kind == "text" and i.label.lower() == "party skills"), None)
        if heading is None:
            return items
        h = items[heading]
        extra = [Item("text", line, h.x, h.y)
                 for line in self.party_skills.lines(self.game, self.skills)]
        return items[:heading + 1] + extra + items[heading + 1:]

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

    def typing(self):
        """On an edit box: keys are letters for it, not our commands."""
        return bool(self.options) and self.options[self.cursor].kind == "edit"

    def on_inventory(self):
        """Is the screen showing item cells? (Picks the help's starting group.)"""
        return any(i.kind == "slot" for i in self.options)

    def option_text(self):
        return self.lead() + self.options[self.cursor].spoken() + self.position_text()

    def lead(self):
        """A section's name, once, in front of the first thing said in it."""
        title, self.announce = self.announce, ""
        return f"{title}: " if title else ""

    # --- the loop --------------------------------------------------------

    def poll(self, pressed=()):
        pressed, self.carried = self.carried + list(pressed), []
        try:
            found = self.read()
        except ReadError:
            # Mid-update or loading: try again next tick, keeping the keys
            # (a few, so a long load doesn't replay a pile of presses).
            self.carried = pressed[-3:]
            return
        if found is None:
            self.last, self.options, self.pending = None, [], None
            return
        state, items, config = found
        self.config = config
        if state != self.last and not self.same_screen(state, items):
            self.last, self.pending = state, None
            self.announce, self.section_memory = "", {}
            self.options, self.cursor = items, min(config.get("start", 0), len(items) - 1)
            if self.has_sections():
                self.open_sections(config)
            else:
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
        if self.tip_wait:
            self.check_tooltip()
        if self.hold_check:
            self.check_held()
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
        if ("accessibility",) in (state[3], self.last[3]):
            return False    # into or out of the Accessibility tab: read the page

        here = self.options[self.cursor].widget
        return bool(here) and any(i.widget == here for i in items)

    # --- sections and grids ----------------------------------------------
    # A screen can have sections: each group of item cells (equipment, your
    # inventory, the other side) is a grid, where all four arrows move by
    # position; on screens laid out in columns (party, character) each
    # column is a list. Tab and Shift+Tab move between sections, and each
    # section remembers where you were. One section = the plain list.

    def section_key(self, item):
        if item.kind == "slot":
            return ("grid", item.group)
        columns = (self.config.get("layout") or {}).get("columns")
        if columns:
            return ("list", next(n for n, x in enumerate(columns + [99]) if item.x < x))
        return ("list", 0)

    def sections(self):
        """{key: [indexes into options]}, in reading order.

        A screen with grids gets the grids first, then one "Details" list
        of everything else (costs, armor, money, buttons). A heading just
        above a grid ("Discard", a merchant's name) names that grid instead
        of standing alone."""
        grids = {}
        for n, item in enumerate(self.options):
            if item.kind == "slot":
                grids.setdefault(item.group, []).append(n)
        if not grids:
            found = {}
            for n, item in enumerate(self.options):
                found.setdefault(self.section_key(item), []).append(n)
            return found
        self.grid_headings = {}
        details = []
        for n, item in enumerate(self.options):
            if item.kind == "slot":
                continue
            group = self.heading_of(item, grids) if item.kind == "text" else None
            if group is not None:
                self.grid_headings.setdefault(group, item.label)
            else:
                details.append(n)
        found = {("grid", g): members for g, members in grids.items()}
        if details:
            found[("list", "details")] = details
        return found

    def heading_of(self, item, grids):
        """The grid a text sits just above (within HEADING_GAP), or None."""
        for group, members in grids.items():
            cells = [self.options[n] for n in members]
            top = max(c.y for c in cells)
            left, right = min(c.x for c in cells), max(c.x for c in cells)
            if 0 < item.y - top <= HEADING_GAP and left - 0.05 <= item.x <= right + 0.1:
                return group
        return None

    def open_sections(self, config):
        """A screen with sections opens on its start section (the profile's
        layout "start_section", e.g. your own inventory) and says the
        screen's name, the section's, then the first item."""
        sections = self.sections()
        start = (config.get("layout") or {}).get("start_section")
        key = next((k for k in sections if k[1] == start), next(iter(sections)))
        title = self.section_title(key, sections[key])
        name = config.get("name", "")
        self.go(sections[key][0], title if title == name or not name else f"{name}, {title}")

    def section_of(self, index, sections):
        """Which section an item is in (a grid's heading: the first section)."""
        return next((k for k, members in sections.items() if index in members),
                    next(iter(sections)))

    def has_sections(self):
        return len(self.sections()) > 1

    def section_title(self, key, members):
        names = (self.config.get("layout") or {}).get("section_names", {})
        if key[1] in names:
            return names[key[1]]
        if key == ("list", "details"):
            return "Details"
        first = self.options[members[0]]
        if key[0] == "grid":
            return (self.grid_headings.get(key[1])
                    or first.label.rstrip("0123456789 ") or "Grid")
        return ""   # a column: its first item is its heading, so no name twice

    def cell_name(self, item):
        """A cell's own name without its grid's: "5" for "Inventory 5",
        "Feet" for the equipment's Feet."""
        key = self.section_key(item)
        sections = self.sections()
        if key[0] != "grid" or key not in sections:
            return item.label
        # Only the grid's own name goes: "Weapon 1" in Equipment stays.
        title = self.section_title(key, sections[key])
        if item.label.startswith(title + " "):
            return item.label[len(title) + 1:]
        return item.label

    def grid_move(self, key, members):
        """The cell next to ours in the arrow's direction, by screen position:
        same row for Left/Right, the nearest one in line for Up/Down."""
        here = self.options[self.cursor]
        best = None
        for n in members:
            c = self.options[n]
            dx, dy = c.x - here.x, c.y - here.y
            if key in (keys.LEFT, keys.RIGHT):
                if abs(dy) > GRID_ROW or (dx < -0.001) != (key == keys.LEFT) or abs(dx) <= 0.001:
                    continue
                score = (abs(dx), 0)
            else:   # y grows upward
                if abs(dy) <= GRID_ROW or (dy > 0) != (key == keys.UP):
                    continue
                score = (round(abs(dy), 2), abs(dx))
            if best is None or score < best[0]:
                best = (score, n)
        return best[1] if best else None

    def go(self, index, title=""):
        """Move the cursor to an item and speak it (after the section's name)."""
        self.cursor = index
        self.pending = None
        self.announce = title
        if self.wants_tooltip():
            self.ask_tooltip()      # spoken once the game shows what's there
        else:
            self.tip_wait = None
            self.say(self.option_text())
            self.hover()

    def position_text(self):
        """", 3 of 8": the place within the section (the whole screen if one)."""
        sections = self.sections()
        members = sections.get(self.section_of(self.cursor, sections), [])
        if self.cursor in members and len(members) < len(self.options):
            return f", {members.index(self.cursor) + 1} of {len(members)}"
        return f", {self.cursor + 1} of {len(self.options)}"

    def switch_section(self, step):
        sections = self.sections()
        keys_ = list(sections)
        here = self.section_of(self.cursor, sections)
        self.section_memory[here] = self.options[self.cursor].widget
        target = keys_[(keys_.index(here) + step) % len(keys_)]
        members = sections[target]
        remembered = self.section_memory.get(target)
        index = next((n for n in members if remembered and self.options[n].widget == remembered),
                     members[0])
        self.go(index, self.section_title(target, members))

    def handle_keys(self, pressed):
        if not self.options:
            return
        for key in pressed:
            if key in (keys.TAB, keys.SHIFT_TAB, keys.CTRL_LEFT, keys.CTRL_RIGHT):
                if self.has_sections():
                    self.switch_section(-1 if key in (keys.SHIFT_TAB, keys.CTRL_LEFT) else 1)
                continue
            sections = self.sections()
            here = self.section_of(self.cursor, sections)
            members = sections[here] if len(sections) > 1 else list(range(len(self.options)))
            arrows = (keys.UP, keys.DOWN, keys.HOME, keys.END)
            if here[0] == "grid" and key in arrows + (keys.LEFT, keys.RIGHT):
                if key in (keys.HOME, keys.END):
                    target = members[0 if key == keys.HOME else -1]
                else:
                    target = self.grid_move(key, members)
                # At the edge we stay put and say where we are again.
                self.go(self.cursor if target is None else target)
            elif key in arrows:
                place = members.index(self.cursor) if self.cursor in members else 0
                n = len(members)
                place = {keys.UP: (place - 1) % n, keys.DOWN: (place + 1) % n,
                         keys.HOME: 0, keys.END: n - 1}[key]
                self.go(members[place])
            elif key == keys.RETURN and keys.is_down(keys.SHIFT):
                self.act("special")
            elif key in ACTION_KEYS:
                if key == keys.SPACE and self.options[self.cursor].kind == "edit":
                    continue    # a space typed into the box, not a press
                self.act(ACTION_KEYS[key])

    def hover(self):
        """Put the mouse over the cursor's item, so the game highlights it
        (and plays its hover sound) as it would for a sighted player."""
        item = self.options[self.cursor]
        if self.mouse is not None and item.kind != "text" and not item.virtual and item.visible():
            self.mouse.hover(item.x + item.click[0], item.y + item.click[1])

    # --- carrying items (inventory) --------------------------------------
    # The game picks an item up on one click and puts it down on the next.
    # The inventory window says whether something is on the mouse (+held)
    # and which item kind (+held+4, -1 for none); names come from the
    # game's item table, one record of item_kind_size bytes per kind.

    def held(self):
        """Item kind number on the mouse, or None."""
        window = self.window(self.top_window())
        offset = self.config["held"]
        if not self.reader.i32(window + offset):
            return None
        return self.reader.i32(window + offset + 4)

    def item_name(self, kind):
        table = self.reader.ptr(self.screen["item_kinds"])
        count = self.reader.i32(self.screen["item_kinds"] + 4)
        if kind is None or not 0 <= kind < count:
            return "something"
        return text_mod.clean(self.reader.rgl_string(table + kind * self.screen["item_kind_size"]))

    def check_held(self):
        started, before = self.hold_check
        now = self.held()
        if now == before and time.time() - started < HOLD_WAIT:
            return
        self.hold_check = None
        if now == before:
            # Still the same: the cell refused it (a fish isn't a helmet),
            # or an empty cell was clicked with nothing held.
            self.say(f"can't put {self.item_name(before)} there" if before is not None
                     else "nothing to pick up")
        elif before is None:
            self.say(f"picked up {self.item_name(now)}")
        elif now is None:
            self.say(f"put down {self.item_name(before)}")
        else:
            self.say(f"put down {self.item_name(before)}, picked up {self.item_name(now)}")

    # --- tooltips (inventory cells) --------------------------------------

    def tooltip(self):
        """The game's one tooltip: up to TIP_LINES rgl::strings, 0x90 bytes
        apart, at a fixed address. All blank when nothing is hovered."""
        base = self.screen["tooltip"]
        lines = (text_mod.clean(self.reader.rgl_string(base + n * TIP_STRIDE))
                 for n in range(TIP_LINES))
        return [line for line in lines if line]

    def wants_tooltip(self):
        item = self.options[self.cursor]
        return (item.kind == "slot" and self.config.get("tooltip") and "tooltip" in self.screen
                and self.mouse is not None)

    def ask_tooltip(self):
        """Hover a cell and wait for its tooltip; poll() speaks it. Cells
        scrolled out of view get the wheel first, like a press would."""
        item = self.options[self.cursor]
        if not item.visible():
            bottom, top = item.scroll
            self.mouse.wheel(item.x + item.click[0], (bottom + top) / 2,
                             item.wheel_notches())
            self.tip_wait = (time.time(), None, item.widget)   # hover once it's in view
            return
        before = self.tooltip()
        # A nudge first: if the mouse is already on this spot, moving "there"
        # isn't a movement, and the game only updates its tooltip on one.
        self.mouse.hover(item.x + item.click[0] + 0.005, item.y + item.click[1] + 0.005)
        self.hover()
        self.tip_wait = (time.time(), before, item.widget)

    def check_tooltip(self):
        started, before, widget = self.tip_wait
        item = self.options[self.cursor]
        if item.widget != widget:
            self.tip_wait = None
            return
        if before is None:              # scrolling: a notch a tick until it's in view
            if item.visible():
                self.ask_tooltip()
            elif time.time() - started > TIP_WAIT * 5:
                self.tip_wait = None        # give up; it won't come into view
            else:
                bottom, top = item.scroll
                self.mouse.wheel(item.x + item.click[0], (bottom + top) / 2,
                                 item.wheel_notches())
            return
        lines = self.tooltip()
        # Leaving an item blanks the tooltip for a frame or two before the
        # next item's text appears, so only new, non-blank text is an answer
        # before the wait is up. After it, blank means an empty cell, and the
        # same text means the same kind of item.
        if (not lines or lines == before) and time.time() - started < TIP_WAIT:
            return
        self.tip_wait = None
        lines = self.detail(lines)
        words = ". ".join(lines) if lines else "empty"
        # The item first (that's what you're looking for), then which cell.
        self.say(f"{self.lead()}{words}, {self.cell_name(item)}")

    def detail(self, lines):
        """Cut a tooltip down to the Accessibility tab's "Item details"
        setting. Line 1 is the item's name; the price line says "price"."""
        level = self.settings.get("item_details") if self.settings else "Full"
        if not lines or level == "Full":
            return lines
        if level == "Name only":
            return lines[:1]
        return lines[:1] + [line for line in lines[1:] if "price" in line.lower()]

    def act(self, key, tries=0):
        item = self.options[self.cursor]
        if item.virtual == "tab":
            if key == "activate":
                self.page.open = True    # poll() reads the page out next tick
            return
        if item.virtual:
            self.page.act(item, key)
            return
        if item.kind == "tab" and self.page and self.page.open and key == "activate":
            self.page.open = False       # back to the game's own tab
        action = item.action(key)
        if action is None or self.mouse is None:
            return
        if not item.visible():
            # Scrolled out of view: turn the wheel toward it and try again
            # next tick, once the game has moved the list.
            if tries < MAX_SCROLL_TRIES:
                bottom, top = item.scroll
                self.mouse.wheel(item.x + item.click[0], (bottom + top) / 2, item.wheel_notches())
                self.pending = (key, tries + 1)
            return
        if action[0] == "pick":
            # Drop-down: open it, then click the choice's row in the list.
            # A list near the bottom of the screen runs off it, so scroll
            # the page up a notch first if the row would be off-screen.
            open_x, open_y, row_x, row_y = action[1:]
            if row_y < PICK_MARGIN:
                if item.scroll and tries < MAX_SCROLL_TRIES:
                    bottom, top = item.scroll
                    self.mouse.wheel(open_x, (bottom + top) / 2, -1)
                    self.pending = (key, tries + 1)
                return
            self.mouse.click(open_x, open_y)
            time.sleep(PICK_WAIT)          # the list takes a moment to open
            self.mouse.click(row_x, row_y)
            return
        if action[0] == "right click":
            self.mouse.click(*action[1:], right=True)
            return
        if action[0] == "click":
            if item.kind == "slot" and "held" in self.config:
                self.hold_check = (time.time(), self.held())
            # Menu options get a quick click (see click.click), and so do
            # screens whose profile says they take one ("quick_click"); a
            # few, like Custom Battle, miss quick clicks, so it's per screen.
            quick = item.kind == "option" or self.config.get("quick_click")
            self.mouse.click(*action[1:], hold=0 if quick else 0.08)
        else:
            self.mouse.drag(*action[1:])
