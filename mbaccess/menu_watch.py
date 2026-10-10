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
right-clicks (an item's special action: slaughtering a horse), and we move
the real mouse to do it. Rows scrolled out of view are still readable (the
memory has them); before pressing one, we turn the mouse wheel until it's
in view.
"""
import json
import os
import re
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
HEADING_GAP = 0.15      # a text this far above a grid's top row is its heading
PICK_MARGIN = 0.01    # a drop-down row lower than this is off the bottom of the screen
PICK_WAIT = 0.3       # seconds for a drop-down list to open
TIP_LINES, TIP_STRIDE = 12, 0x90   # tooltip: rgl::string lines
HOLD_WAIT = 0.4       # seconds for a click on a cell to pick up or put down
TIP_WAIT = 0.4        # seconds to wait for a tooltip before calling a cell empty
SPECIAL_WAIT = 0.6    # seconds for a right click's question (slaughter) to open
# Conversation manager (reference/wse/WarbandLib/conversation.h, verified on
# 1.174): current sentence, number of replies, then two tables of 1024
# options (156 bytes each), a bool, and the partner's line.
CONV_SENTENCE, CONV_NUM_OPTIONS = 28, 36
CONV_SPEAKER_TEXT = 40 + 2 * 1024 * 156 + 4
HIGHLIGHT = 0x1f2       # widget byte: non-zero while the mouse is over it
AIM_WAIT = 0.15         # seconds for the game to light up a hovered button
# Screens whose picture we found out by hovering (window number -> letterbox),
# kept between runs so each screen is learned once.
LEARNED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "learned.json")
ACTION_KEYS = {keys.RETURN: "activate", keys.SPACE: "activate",
               keys.LEFT: "left", keys.RIGHT: "right"}
# Escape presses the screen's own way back: an option or button starting
# with one of these ("Go back", "Leave...", "Resume travelling", "Done").
BACK = re.compile(r"(go back|back|leave|return|cancel|never ?mind|forget it|done|close)\b"
                  r"|resume travel", re.IGNORECASE)
SEARCH_PAUSE = 1.0      # seconds between letters before type search starts over


class MenuWatcher:
    def __init__(self, reader, game_address, offsets, menus, say, screen=None, mouse=None,
                 page=None, settings=None, party_skills=None, world_map=None):
        self.reader = reader
        self.party_skills = party_skills   # party_skills.PartySkills, if the profile has it
        self.world_map = world_map         # world_map.WorldMap: places on the map screen
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
        self.move_check = None       # (since, cell widget, its item before): after Ctrl+Enter
        self.special_check = None    # (since, the cell's item): after Shift+Enter
        self.tip_nudged = False      # moved the mouse again for a slow tooltip
        self.carried = []            # keys from a tick whose read failed
        self.settling = None         # a new screen seen once, waiting for a second read
        self.aim_check = None        # (since, widget, tried the other picture): after a hover
        self.trial = None            # letterbox being tried on this screen, or None
        self.learned_path = LEARNED
        try:
            with open(LEARNED, encoding="utf-8") as f:
                self.learned = json.load(f)
        except (OSError, ValueError):
            self.learned = {}
        self.announce = ""           # a section's name, said before the next item
        self.section_memory = {}     # section key -> widget we were on there
        self.grid_headings = {}      # grid group -> the heading above it
        self.search, self.search_at = "", 0.0   # type search: letters so far, last one's time

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
            if config.get("saves"):
                items = self.save_tiles(top, config["saves"]) + items
            if config.get("map") and self.world_map and self.game:
                # The places come first: the map opens on them.
                items = self.world_map.items(self.game) + items
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

    def save_tiles(self, window, saves):
        """Load game draws each save as a picture tile with no text; the name
        and day ("Day 4 (7:10)") live in records inside the window object
        (findings/screens.md). Pair the records that hold a save with the
        textless tiles, top-left first, and make each a button: Enter clicks
        the tile, which selects it, as for a sighted player."""
        r, base = self.reader, self.window(window)
        records = []
        for n in range(saves["count"]):
            record = base + saves["first"] + n * saves["stride"]
            if r.i32(record + saves["exists"]) == 1:
                name = text_mod.clean(r.rgl_string(record))
                day = text_mod.clean(r.rgl_string(record + saves["day"]))
                records.append((n, ", ".join(p for p in (name, day) if p)))
        _, kids = self.tree.children(self.root(window))
        tiles = [k for k in kids
                 if self.tree.kind(k) == "image" and not self.tree.hidden(k) and not self.tree.text(k)]
        tiles.sort(key=lambda k: (-round(self.tree.position(k)[1], 2), self.tree.position(k)[0]))
        if len(tiles) != len(records):
            # Self-check: the layout isn't what we found. Better no names
            # than the wrong save's name on a tile.
            records = [(None, f"Save {n}") for n in range(1, len(tiles) + 1)]
        chosen = r.i32(base + saves["selected"])
        items = []
        for (n, words), tile in zip(records, tiles):
            x, y = self.tree.position(tile)
            items.append(Item("button", words, x, y, value="selected" if n == chosen else "",
                              click=self.tree.middle(tile), widget=tile))
        return items

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
        """The screen's words; with live buttons, a list of two lines (the
        words, then the item under the cursor) so a reply in a conversation
        isn't run into what the other person said."""
        parts = [text_mod.clean(body)]
        if self.reads_buttons:
            if self.options:
                return [text_mod.spoken(config.get("name", ""), *parts), self.option_text()]
        elif number is not None and 0 <= number < len(self.menus):
            # Without the button addresses, list every option the menu could
            # show (some may be hidden in-game).
            options = [text_mod.clean(i.text) for i in self.menus[number].items]
            if options:
                parts.append("Options: " + "; ".join(o for o in options if o))
        return text_mod.spoken(config.get("name", ""), *parts)

    def say_lines(self, text):
        """Speak one line, or several, each its own utterance (the later
        ones queued), so NVDA's speech history shows them as separate lines."""
        lines = [text] if isinstance(text, str) else [t for t in text if t]
        for n, line in enumerate(lines):
            self.say(line) if n == 0 else self.say(line, interrupt=False)

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
        if self.mouse:      # only some screens keep the monitor's shape (click.py)
            self.mouse.letterbox = self.letterboxed(state[0], config)
        if state != self.last and not self.same_screen(state, items):
            # The game builds a screen over a frame or two: a first read can
            # still hold a button from the old one ("11 of 11" with ten).
            # Speak it only once two reads in a row agree (one tick, 50 ms).
            look = (state, [(i.label, i.widget) for i in items])
            if look != self.settling:
                self.settling, self.carried = look, pressed[-3:]
                return
            self.settling, self.aim_check, self.trial = None, None, None
            self.special_check = None     # a question opened (slaughter): it's read out
            self.last, self.pending = state, None
            self.announce, self.section_memory = "", {}
            self.options, self.cursor = items, min(config.get("start", 0), len(items) - 1)
            if self.has_sections():
                self.open_sections(config)
            else:
                self.say_lines(self.describe(state[1], state[2], config))
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
        if self.aim_check:
            self.check_aim()
        if self.hold_check:
            self.check_held()
        if self.move_check:
            self.check_moved()
        if self.special_check:
            self.check_special()
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
        if item.virtual == "map":
            return ("list", "places")
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
        if self.config.get("map"):
            return "Places" if key[1] == "places" else "Map buttons"
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
        Up/Down stay in the column (the end of it is an edge); Left/Right go to the
        nearest column on that side, to its cell closest in height. The equipment
        cells are three uneven columns (Head/Body/Feet, Hands/Horse, four weapons):
        Down from Feet used to jump to Weapon 4, then the Horse."""
        here = self.options[self.cursor]
        best = None
        for n in members:
            c = self.options[n]
            dx, dy = c.x - here.x, c.y - here.y
            if key in (keys.LEFT, keys.RIGHT):
                if (dx < -0.001) != (key == keys.LEFT) or abs(dx) <= GRID_ROW:
                    continue
                score = (round(abs(dx), 2), abs(dy))
            else:   # y grows upward
                if abs(dx) > GRID_ROW or abs(dy) <= GRID_ROW or (dy > 0) != (key == keys.UP):
                    continue
                score = (abs(dy), 0)
            if best is None or score < best[0]:
                best = (score, n)
        return best[1] if best else None

    def go(self, index, title=""):
        """Move the cursor to an item and speak it (after the section's name)."""
        self.cursor = index
        self.pending = None
        self.announce = title
        if self.wants_tooltip():
            self.name_cell()        # from memory, or once the game's tooltip shows
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
            if key in keys.LETTERS:
                if self.searching():
                    self.type_search(chr(key).lower())
                continue
            if key == keys.ESCAPE:
                back = self.back_item()
                if back is not None:
                    self.cursor = back
                    self.say(self.options[back].label)
                    self.act("activate")
                continue    # with no way back, the game gets the Escape
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
            elif key == keys.RETURN and keys.is_down(keys.CONTROL):
                self.act("quick")
            elif key in ACTION_KEYS:
                if key == keys.SPACE and self.options[self.cursor].kind == "edit":
                    continue    # a space typed into the box, not a press
                self.act(ACTION_KEYS[key])

    # --- Escape and type search ---------------------------------------------

    def back_item(self):
        """Index of the screen's way back (the last one, as menus put "Go
        back" and "Leave" at the bottom), or None. Not where Escape already
        means something in the game: a screen's profile can say "escape": false."""
        if not self.options or self.config.get("escape") is False:
            return None
        found = [n for n, i in enumerate(self.options)
                 if i.kind in ("option", "button") and not i.virtual and not i.disabled
                 and BACK.match(i.label)]
        return found[-1] if found else None

    def searching(self):
        """Do letters search this screen? Not in a name box (they're typed),
        and not where the profile says the game needs them ("type_search": false)."""
        return bool(self.options) and not self.typing() \
            and self.config.get("type_search", True) \
            and not (keys.is_down(keys.CONTROL) or keys.is_down(keys.ALT))

    def type_search(self, letter):
        """Jump to the next item starting with the letters typed so far.
        Letters close together build a word ("j", "je", "jel"); the same
        letter again and again steps through the items starting with it."""
        now = time.monotonic()
        if now - self.search_at > SEARCH_PAUSE:
            self.search = ""
        self.search_at = now
        self.search += letter
        word = self.search
        repeat = len(word) > 1 and word == letter * len(word)
        if repeat:
            word = letter
        # A new word may match the item we're on; a single letter or a
        # repeat moves on to the next one.
        first = 1 if len(word) == 1 else 0
        n = len(self.options)
        for step in range(first, n + first):
            index = (self.cursor + step) % n
            item = self.options[index]
            if item.kind != "slot" and item.label.lower().startswith(word):
                sections = self.sections()
                before = self.section_of(self.cursor, sections)
                after = self.section_of(index, sections)
                title = self.section_title(after, sections[after]) if after != before else ""
                self.go(index, title)
                return
        self.say(f"No {self.search}")

    def hover(self):
        """Put the mouse over the cursor's item, so the game highlights it
        (and plays its hover sound) as it would for a sighted player."""
        item = self.options[self.cursor]
        if self.mouse is not None and item.kind != "text" and not item.virtual and item.visible():
            self.mouse.hover(item.x + item.click[0], item.y + item.click[1])
            if item.kind == "button" and item.widget and not item.disabled:
                self.aim_check = (time.monotonic(), item.widget, self.trial is not None)

    # --- checking our aim --------------------------------------------------
    # Some screens keep the monitor's shape (black bars, click.py); the game
    # doesn't say which. After a hover we look at the button's highlight: if
    # it didn't light up, we try the other picture once, and if that works we
    # remember it for this window. If neither works (the player moved the
    # mouse), we put things back.

    def letterboxed(self, window, config):
        if self.trial is not None:
            return self.trial
        return self.learned.get(str(window), bool(config.get("letterbox")))

    def check_aim(self):
        since, widget, retried = self.aim_check
        if time.monotonic() - since < AIM_WAIT:
            return
        self.aim_check = None
        item = self.options[self.cursor]
        if item.widget != widget:
            return              # moved on already
        try:
            lit = self.reader.read(widget + HIGHLIGHT, 1)[0]
        except ReadError:
            return
        window = str(self.last[0])
        if lit:
            if retried and self.trial is not None:
                self.learned[window] = self.trial
                self.trial = None
                try:
                    with open(self.learned_path, "w", encoding="utf-8") as f:
                        json.dump(self.learned, f, indent=2)
                except OSError:
                    pass
            return
        if retried:
            self.trial = None   # neither picture worked: not our aim
            return
        self.trial = not self.letterboxed(self.last[0], self.config)
        self.mouse.letterbox = self.trial
        self.hover()

    # --- carrying items (inventory) --------------------------------------
    # The game picks an item up on one click and puts it down on the next.
    # The inventory window says whether something is on the mouse (+held)
    # and which item (+held+4: kind, -1 for none; +held+8: its flags); names
    # come from the game's item table, one record of item_kind_size bytes
    # per kind, with the quality word ("Rusty %s") from the modifier table.

    def held(self):
        """(item kind, flags) on the mouse, or None."""
        window = self.window(self.top_window())
        offset = self.config["held"]
        if not self.reader.i32(window + offset):
            return None
        return struct.unpack("<iI", self.reader.read(window + offset + 4, 8))

    def item_name(self, kind, flags=0):
        """"Rusty Sword": the kind's name inside its modifier's pattern
        (the flags' top byte; 0 = plain, which the game shows bare)."""
        table = self.reader.ptr(self.screen["item_kinds"])
        count = self.reader.i32(self.screen["item_kinds"] + 4)
        if kind is None or not 0 <= kind < count:
            return "something"
        name = text_mod.clean(self.reader.rgl_string(table + kind * self.screen["item_kind_size"]))
        inv = self.screen.get("inventory", {})
        modifier = flags >> 24
        if modifier and "modifiers" in inv:
            pattern = self.reader.rgl_string(inv["modifiers"] + modifier * inv["modifier_size"])
            if pattern.count("%s") == 1:
                name = pattern.replace("%s", name)
        return name

    def check_held(self):
        started, before = self.hold_check
        now = self.held()
        if now == before and time.time() - started < HOLD_WAIT:
            return
        self.hold_check = None
        if now == before:
            # Still the same: the cell refused it (a fish isn't a helmet),
            # or an empty cell was clicked with nothing held.
            self.say(f"can't put {self.item_name(*before)} there" if before is not None
                     else "nothing to pick up")
        elif before is None:
            self.say(f"picked up {self.item_name(*now)}")
        elif now is None:
            self.say(f"put down {self.item_name(*before)}")
        else:
            self.say(f"put down {self.item_name(*before)}, picked up {self.item_name(*now)}")

    def check_moved(self):
        """After a Ctrl+click: did the cell's item go (bought, sold, moved
        across)? Cells memory can't read (the Discard pile) get no answer."""
        started, widget, before = self.move_check
        cell = next((i for i in self.options if i.widget == widget), None)
        now = self.cell_contents(cell) if cell else None
        if now == before and time.time() - started < HOLD_WAIT:
            return
        self.move_check = None
        if before is None or now is None:
            return
        if not before:
            self.say("nothing there")
        elif now == before:
            self.say(f"{before} stayed")       # refused: no money, no room
        else:
            self.say(f"{before} moved")

    def check_special(self):
        """After a right click: the game asks a question (a new screen, read out as
        usual) or does nothing, which we say once the wait is over."""
        started, before = self.special_check
        if time.time() - started < SPECIAL_WAIT:
            return
        self.special_check = None
        if before is None:
            self.say("nothing happens")
        else:
            self.say(f"nothing to do with {before}" if before else "nothing there")

    # --- what's in a cell, straight from memory --------------------------
    # The inventory window keeps, per side (0 = you, 1 = the other side), a
    # table of cell widgets in slot order: 96 bag cells, then 10 equipment
    # cells. The items themselves are in the troop: a bag of 96 (kind,
    # flags) pairs and a separate list of 10 equipped ones. Side 1 is the
    # game's "screen troop" (a merchant, a companion, loot); with none (the
    # Discard pile) we can't tell, and the tooltip answers instead.

    def cell_slot(self, item):
        """(side, "bag" or "equipment", slot number) of a cell, or None."""
        inv = self.screen.get("inventory")
        if not inv or not item.widget:
            return None
        window = self.window(self.top_window())
        for part, size in zip(("bag", "equipment"), inv["per_side"]):
            table = struct.unpack(f"<{2 * size}I",
                                  self.reader.read(window + inv[part + "_cells"], 8 * size))
            if item.widget in table:
                n = table.index(item.widget)
                return n // size, part, n % size
        return None

    def cell_price(self, item):
        """A bag cell's trade price from the window's table, or None when
        not trading (the table then holds the "no price" number)."""
        inv = self.screen.get("inventory", {})
        if "bag_prices" not in inv:
            return None
        try:
            where = self.cell_slot(item)
            if where is None or where[1] != "bag":
                return None
            side, _, slot = where
            window = self.window(self.top_window())
            price = self.reader.i32(window + inv["bag_prices"] + 4 * (side * inv["per_side"][0] + slot))
        except ReadError:
            return None
        return price if 0 <= price != inv["no_price"] else None

    def cell_contents(self, item):
        """A cell's item name, "" when it's empty, None when we can't tell."""
        inv = self.screen.get("inventory")
        try:
            where = self.cell_slot(item)
            if where is None or self.game is None:
                return None
            side, part, slot = where
            troop_no = 0 if side == 0 else self.reader.i32(self.game + inv["screen_troop"])
            if troop_no < 0 and "temp_troop" in inv:
                # No merchant or loot: the other side is the Discard pile,
                # which is the game's scratch troop.
                troop_no = self.reader.i32(self.game + inv["temp_troop"])
            if troop_no < 0:
                return None
            troop = self.reader.ptr(self.game + inv["troops"]) + troop_no * inv["troop_size"]
            kind, flags = struct.unpack("<iI", self.reader.read(troop + inv["troop_" + part] + 8 * slot, 8))
            return self.item_name(kind, flags) if kind > 0 else ""
        except ReadError:
            return None

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

    def name_cell(self):
        """Speak the cursor's cell. Memory names its item at once ("Smoked
        Fish, 8"); the game's tooltip is then asked only for the details
        (price, stats), which follow without cutting the name off. Cells
        memory can't name (the Discard pile) wait for the tooltip instead."""
        item = self.options[self.cursor]
        known = self.cell_contents(item)
        if known is None:
            self.ask_tooltip(None)
            return
        price = self.cell_price(item) if known and self.detail_level() == "Name and price" else None
        if price is not None:
            # Trading: the window's own price table answers, no tooltip needed.
            self.tip_wait = None
            self.say(f"{self.lead()}{known}, price {price}, {self.cell_name(item)}{self.position_text()}")
            self.hover()
            return
        self.say(f"{self.lead()}{known or 'empty slot'}, {self.cell_name(item)}{self.position_text()}")
        if known and self.detail_level() != "Name only":
            self.ask_tooltip(known)
        else:
            self.tip_wait = None
            self.hover()

    def ask_tooltip(self, known):
        """Hover a cell and wait for its tooltip; poll() speaks it. Cells
        scrolled out of view get the wheel first, like a press would.
        known: the item's name if already spoken, else None."""
        item = self.options[self.cursor]
        if not item.visible():
            bottom, top = item.scroll
            self.mouse.wheel(item.x + item.click[0], (bottom + top) / 2,
                             item.wheel_notches())
            self.tip_wait = (time.time(), None, item.widget, known)   # hover once it's in view
            return
        before = self.tooltip()
        self.tip_nudged = False
        # A nudge first: if the mouse is already on this spot, moving "there"
        # isn't a movement, and the game only updates its tooltip on one.
        self.mouse.hover(item.x + item.click[0] + 0.005, item.y + item.click[1] + 0.005)
        self.hover()
        self.tip_wait = (time.time(), before, item.widget, known)

    def check_tooltip(self):
        started, before, widget, known = self.tip_wait
        item = self.options[self.cursor]
        if item.widget != widget:
            self.tip_wait = None
            return
        if before is None:              # scrolling: a notch a tick until it's in view
            if item.visible():
                self.ask_tooltip(known)
            elif time.time() - started > TIP_WAIT * 5:
                self.tip_wait = None        # give up; it won't come into view
            else:
                bottom, top = item.scroll
                self.mouse.wheel(item.x + item.click[0], (bottom + top) / 2,
                                 item.wheel_notches())
            return
        lines = self.tooltip()
        if known is not None:
            # The name is already spoken: only a tooltip about this item counts
            # (a leftover one from another item is never read as this one's).
            waited = time.time() - started
            if lines and lines[0] == known:
                self.tip_wait = None
                extra = self.detail(lines)[1:]
                if extra:
                    self.say(". ".join(extra), interrupt=False)
            elif waited > 3 * TIP_WAIT:
                self.tip_wait = None        # no details this time; the name was said
            elif waited > TIP_WAIT / 2 and not self.tip_nudged:
                # The game sometimes misses a hover after quick moves:
                # one more real movement usually brings the tooltip.
                self.tip_nudged = True
                self.mouse.hover(item.x + item.click[0] - 0.005, item.y + item.click[1] - 0.005)
                self.hover()
            return
        # Leaving an item blanks the tooltip for a frame or two before the
        # next item's text appears, so only new, non-blank text is an answer
        # before the wait is up. After it, blank means an empty cell, and the
        # same text means the same kind of item.
        if (not lines or lines == before) and time.time() - started < TIP_WAIT:
            return
        self.tip_wait = None
        lines = self.detail(lines)
        words = ". ".join(lines) if lines else "empty slot"
        # The item first (that's what you're looking for), then which cell.
        self.say(f"{self.lead()}{words}, {self.cell_name(item)}{self.position_text()}")

    def detail_level(self):
        return self.settings.get("item_details") if self.settings else "Full"

    def detail(self, lines):
        """Cut a tooltip down to the Accessibility tab's "Item details"
        setting. Line 1 is the item's name; the price line says "price"."""
        level = self.detail_level()
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
        if item.virtual == "map":
            if key == "activate":
                self.world_map.travel(self.game, item)
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
            # Only animals have one ("Slaughter this Saddle Horse and eat it?").
            # If no question opens, say so rather than leave the player guessing.
            self.special_check = (time.time(), self.cell_contents(item))
            self.mouse.click(*action[1:], right=True)
            return
        if action[0] == "ctrl click":
            # The item moves without being carried: say where it went by
            # comparing the cell before and after (see check_moved).
            self.move_check = (time.time(), item.widget, self.cell_contents(item))
            self.mouse.click(*action[1:], ctrl=True)
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
