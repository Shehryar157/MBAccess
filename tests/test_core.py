"""Tests against a fake game in memory, so they run without the real game."""
import os
import struct

import pytest

from mbaccess import finder, modfiles, text
from mbaccess.mem import FakeMemory, Reader, pack_rgl_string
from mbaccess.menu_watch import MenuWatcher

GAME = 0x10000000          # where our pretend wb::game object lives
HEAP = 0x20000000          # where long strings live
MENU_TEXT_OFFSET = 0x2000  # pretend positions of the fields we discover
MENU_NO_OFFSET = 0x2400

SAMPLE_MENUS = """menusfile version 1
 2
menu_start 0 Welcome,_adventurer. none 1 2060 1 5 2
 mno_continue  0  Continue...  1 2060 1 7  .  mno_go_back  0  Go_back  0  .
menu_town 0 {s10}^{s11} none 0 1
 mno_tavern  1 31 2 3 0  Visit_the_tavern.  0  .
"""


def make_game(menu_no, menu_text):
    mem = FakeMemory()
    obj = bytearray(0x3000)
    obj[8:8 + 144] = pack_rgl_string(GAME + 8, "save 1")
    obj[160:160 + 144] = pack_rgl_string(GAME + 160, "Native")
    obj[MENU_TEXT_OFFSET:MENU_TEXT_OFFSET + 144] = pack_rgl_string(
        GAME + MENU_TEXT_OFFSET, menu_text, heap_address=HEAP)
    obj[MENU_NO_OFFSET:MENU_NO_OFFSET + 4] = struct.pack("<i", menu_no)
    mem.write(GAME, obj)
    mem.write(HEAP, menu_text.encode() + b"\0")
    # A stray copy of the word elsewhere must not confuse the finder.
    mem.write(0x30000000, b"xxNative\0yy" + b"\0" * 64)
    return mem


def test_parse_sample_menus():
    menus = modfiles.parse_menus(SAMPLE_MENUS)
    assert [m.id for m in menus] == ["menu_start", "menu_town"]
    assert menus[0].text == "Welcome, adventurer."
    assert [i.text for i in menus[0].items] == ["Continue...", "Go back"]
    assert menus[1].items[0].id == "mno_tavern"


NATIVE = os.path.join(os.path.dirname(__file__), "..", "reference", "ms3", "out")


@pytest.mark.skipif(not os.path.exists(os.path.join(NATIVE, "menus.txt")),
                    reason="Native menus.txt not built (see docs/research.md)")
def test_parse_native_menus():
    menus = modfiles.load_menus(NATIVE)
    assert len(menus) == 217
    assert menus[0].id == "menu_start_game_0"


def test_clean_text():
    assert text.clean("You are in {s1}.^^Lord: {s2}") == "You are in .\nLord:"


def test_find_game_ignores_stray_text():
    mem = make_game(1, "x")
    assert list(finder.find_game(mem, "Native")) == [GAME]


def test_discover_menu_fields():
    long_text = "The town of Praven. " * 10  # long, so stored on the heap
    reader = Reader(make_game(1, long_text))
    assert finder.find_string_field(reader, GAME, 0x3000, "The town of Praven") == [MENU_TEXT_OFFSET]
    assert MENU_NO_OFFSET in finder.find_int_field(reader, GAME, 0x3000, 1)


def test_watcher_speaks_once_per_change():
    mem = make_game(1, "You are in Praven.")
    spoken = []
    offsets = {"cur_menu_no": MENU_NO_OFFSET, "cur_menu_text": MENU_TEXT_OFFSET}
    watcher = MenuWatcher(Reader(mem), GAME, offsets, modfiles.parse_menus(SAMPLE_MENUS), spoken.append)
    watcher.poll()
    watcher.poll()
    assert spoken == ["You are in Praven. Options: Visit the tavern."]
    mem.blocks[GAME][MENU_NO_OFFSET:MENU_NO_OFFSET + 4] = struct.pack("<i", 0)
    watcher.poll()
    watcher.poll()
    assert len(spoken) == 2


def test_watcher_off_until_discovered():
    spoken = []
    watcher = MenuWatcher(Reader(make_game(1, "x")), GAME, {"cur_menu_no": None}, [], spoken.append)
    watcher.poll()
    assert spoken == []


# --- menu buttons and keyboard cursor ------------------------------------

from mbaccess import click, keys


class FakeMouse:
    def __init__(self, clicks):
        self.clicks = clicks

    def hover(self, x, y):
        pass

    def click(self, x, y, hold=0.08):
        self.clicks.append((x, y))

WINDOWS = 0x40000000   # pretend game_windows[32] array
OPEN = 0x40001000      # pretend open-window deque header
SCREEN = {"game_windows": WINDOWS, "open_windows": OPEN, "widget_text": 0x100,
          "widget_position": 0x40, "widget_flags": 0x50,
          "windows": {"4": {"name": "Main menu", "buttons": 0x10, "slots": 4, "click": [0.15, 0.012]},
                      "18": {"buttons": 0x10, "slots": 4, "menu_text": True}}}


def add_menu_window(mem, buttons, top=18, number=18):
    """buttons: list of (text, y, hidden). Slots after them are blank and hidden."""
    window = 0x41000000
    slots = [0x42000000 + i * 0x1000 for i in range(4)]
    mem.write(WINDOWS, struct.pack("<32I", *([0] * number + [window] + [0] * (31 - number))))
    mem.write(window, b"\0" * 0x10 + struct.pack("<4I", *slots))
    for i, address in enumerate(slots):
        label, y, hidden = buttons[i] if i < len(buttons) else ("", 0.02, True)
        obj = bytearray(0x200)
        obj[0x40:0x48] = struct.pack("<ff", 0.015, y)
        obj[0x50:0x54] = struct.pack("<I", 1 if hidden else 0)
        obj[0x100:0x100 + 144] = pack_rgl_string(address + 0x100, label)
        mem.write(address, obj)
    # deque<int>: map, map size, first index, count; one block holding `top`
    mem.write(OPEN, struct.pack("<IIII", 0x43000000, 8, 0, 1))
    mem.write(0x43000000, struct.pack("<8I", 0x43001000, *[0] * 7))
    mem.write(0x43001000, struct.pack("<4i", top, 0, 0, 0))


def make_menu_watcher(top=18):
    mem = make_game(0, "Welcome")
    add_menu_window(mem, [("Go back", 0.18, False), ("Continue...", 0.22, False),
                          ("Secret", 0.14, True)], top)
    said, clicks = [], []
    w = MenuWatcher(Reader(mem), GAME, {"cur_menu_no": MENU_NO_OFFSET,
                                        "cur_menu_text": MENU_TEXT_OFFSET},
                    [], lambda t, interrupt=True: said.append(t), screen=SCREEN, mouse=FakeMouse(clicks))
    return w, said, clicks


def test_menu_reads_visible_buttons_top_first():
    w, said, _ = make_menu_watcher()
    w.poll()
    assert said == []       # a new screen waits for a second, matching read
    w.poll()
    assert said == ["Welcome.", "Continue..., 1 of 2"]


def test_new_screen_waits_for_leftover_buttons():
    # "11 of 11" with ten: the first read still had a button from the old screen.
    mem = make_game(0, "Welcome")
    add_menu_window(mem, [("Go back", 0.18, False), ("Continue...", 0.22, False),
                          ("Old", 0.14, False)])
    said = []
    w = MenuWatcher(Reader(mem), GAME, {"cur_menu_no": MENU_NO_OFFSET,
                                        "cur_menu_text": MENU_TEXT_OFFSET},
                    [], lambda t, interrupt=True: said.append(t), screen=SCREEN, mouse=FakeMouse([]))
    w.poll()
    mem.blocks[0x42002000][0x50:0x54] = struct.pack("<I", 1)   # the game hides it
    w.poll()
    w.poll()
    assert said == ["Welcome.", "Continue..., 1 of 2"]


def test_menu_cursor_and_enter_click():
    w, said, clicks = make_menu_watcher()
    w.poll()
    w.poll()
    w.poll([keys.DOWN])
    assert said[-1] == "Go back, 2 of 2"
    w.poll([keys.DOWN])
    assert said[-1] == "Continue..., 1 of 2"   # wraps around
    w.poll([keys.END, keys.RETURN])
    assert clicks == [pytest.approx((0.015 + 0.1, 0.18 + 0.02))]


def test_menu_silent_when_another_window_is_on_top():
    w, said, _ = make_menu_watcher(top=6)   # 6 = the campaign map
    w.poll()
    assert said == []


def test_engine_coordinates_to_pixels():
    assert click.to_pixels(1280, 720, 0.5, 0.75) == (640, 0)
    assert click.to_pixels(1280, 720, 0.0, 0.0) == (0, 720)


def test_letterboxed_picture():
    # 4:3 window on a 16:9 monitor: bars above and below (measured live).
    assert click.picture(426, 320, 16 / 9) == (0, 40.1875, 426, 239.625)
    # Main menu bottoms: Play Tutorial y=0.48 lit up to row 124, Exit y=0.2 to 214.
    assert click.to_pixels(426, 320, 0.05, 0.48, 16 / 9)[1] in range(122, 128)
    assert click.to_pixels(426, 320, 0.05, 0.2, 16 / 9)[1] in range(212, 218)
    # A very wide window: bars left and right instead.
    left, top, w, h = click.picture(1898, 922, 16 / 9)
    assert top == 0 and h == 922 and round(left) == 129
    # Aspect control off: the picture fills the window as before.
    assert click.to_pixels(1280, 720, 0.0, 0.0, None) == (0, 720)


def test_main_menu_without_a_campaign():
    mem = FakeMemory()
    add_menu_window(mem, [("Start a New Game", 0.44, False), ("Play Tutorial", 0.48, False)],
                    top=4, number=4)
    said, clicks = [], []
    w = MenuWatcher(Reader(mem), None, {"cur_menu_no": MENU_NO_OFFSET,
                                        "cur_menu_text": MENU_TEXT_OFFSET},
                    [], lambda t, interrupt=True: said.append(t), screen=SCREEN, mouse=FakeMouse(clicks))
    w.poll()
    w.poll()
    assert said == ["Main menu", "Play Tutorial, 1 of 2"]
    w.poll([keys.DOWN, keys.RETURN])
    assert clicks == [pytest.approx((0.015 + 0.15, 0.44 + 0.012))]


def test_game_menu_waits_for_the_campaign():
    mem = FakeMemory()
    add_menu_window(mem, [("Continue...", 0.22, False)])
    said = []
    w = MenuWatcher(Reader(mem), None, {"cur_menu_no": MENU_NO_OFFSET,
                                        "cur_menu_text": MENU_TEXT_OFFSET},
                    [], lambda t, interrupt=True: said.append(t), screen=SCREEN)
    w.poll()
    assert said == []

def test_spoken_adds_pauses():
    assert text.spoken("Main menu", "Play Tutorial, 1 of 8") == "Main menu: Play Tutorial, 1 of 8."
    assert text.spoken("", "You are in Praven\nThe lord is away.", "Go back") == \
        "You are in Praven. The lord is away. Go back."

def test_form_rows_pair_labels_and_read_columns_in_order():
    from mbaccess.form import Item, rows
    T = lambda words, x, y: Item("text", words, x, y)
    found = [T("Combat AI:", 0.05, 0.25), Item("spinner", "", 0.38, 0.244, value="Poor"),
             T("Character Detail:", 0.05, 0.2), T("Low", 0.378, 0.2),
             Item("slider", "", 0.433, 0.198, value="50%"), T("High", 0.663, 0.2),
             T("Jump", 0.05, 0.1), Item("button", "", 0.23, 0.1, value="Space"),
             T("Group 1!", 0.4, 0.1), Item("button", "", 0.58, 0.1, value="1"),
             T("Kick", 0.05, 0.06), Item("button", "", 0.23, 0.06, value="E")]
    assert [i.spoken() for i in rows(found)] == [
        "Combat AI: Poor, spinner", "Character Detail: 50%, slider",
        "Jump, Space, button", "Kick, E, button", "Group 1!, 1, button"]


def test_messages_spoken_sorted_and_reviewed(monkeypatch):
    from mbaccess import keys, messages
    log, heap = 0x5000, 0x9000
    mem = FakeMemory()
    texts = []

    def set_log(*new):
        texts.extend(new)
        for i, t in enumerate(texts):
            mem.write(heap + i * 0x90, pack_rgl_string(heap + i * 0x90, t))
        end = heap + len(texts) * 0x90
        mem.write(log, struct.pack("<III", heap, end, end))

    said = []
    set_log("Received 7 damage.")
    watch = messages.MessageWatcher(Reader(mem), log, lambda t, interrupt=True: said.append(t))
    watch.poll()
    assert said == []                     # already there at start: kept, not spoken
    set_log("You got 30 denars.", "Something odd.")
    watch.poll()
    assert said == ["You got 30 denars.", "Something odd."]
    monkeypatch.setattr(keys, "is_down", lambda vk: False)
    said.clear()
    watch.handle_keys([keys.COMMA, keys.COMMA, keys.COMMA, keys.RIGHT_BRACKET])
    assert said == ["You got 30 denars.", "Received 7 damage.", "No older messages.",
                    "Combat: Received 7 damage., 1 of 1"]
    said.clear()
    watch.handle_keys([keys.RIGHT_BRACKET, keys.RIGHT_BRACKET, keys.LEFT_BRACKET, keys.LEFT_BRACKET,
                       keys.LEFT_BRACKET, keys.LEFT_BRACKET])
    assert said[:2] == ["Party, empty", "Money and trade: You got 30 denars., 1 of 1"]
    assert said[-1] == "Other: Something odd., 1 of 1"


def test_party_skill_pieces():
    from mbaccess import modfiles, party_skills
    skills = modfiles.parse_skills("2\nskl_trade Trade 19 10 Desc_1\nskl_riding Riding 2 10 Desc_2\n")
    assert [s.name for s in skills] == ["Trade", "Riding"]
    assert skills[0].flags & modfiles.SF_EFFECTS_PARTY and not skills[1].flags & 0x10
    # Skill 1 = 3, skill 8 = 2 (second int, lowest 4 bits).
    assert party_skills.unpack_skills([0x30, 0x2, 0, 0, 0, 0], 10)[1::7] == [3, 2]
    assert [party_skills.leader_bonus(n) for n in (1, 2, 5, 8, 10)] == [0, 1, 2, 3, 4]


def test_inventory_grid_arrows_and_sections():
    """Arrows move by position inside a grid; Tab goes section to section
    and comes back to the cell we left."""
    from mbaccess import keys
    from mbaccess.form import Item
    said = []
    w = MenuWatcher(None, None, {}, [], said.append)
    slot = lambda label, x, y, group: Item("slot", label, x, y, group=group, widget=id(label) + int(x * 1e4 + y * 1e3))
    eq = [slot("Head", 0.451, 0.605, "inv"), slot("Body", 0.451, 0.517, "inv"),
          slot("Hands", 0.363, 0.517, "inv"), slot("Weapon 1", 0.552, 0.605, "inv"),
          slot("Weapon 2", 0.552, 0.517, "inv")]
    inv = [slot(f"Inventory {n + 1}", 0.70 + 0.088 * (n % 3), 0.6 - 0.088 * (n // 3), "int")
           for n in range(9)]
    other = [slot(f"Discard {n + 1}", 0.05 + 0.088 * (n % 3), 0.6 - 0.088 * (n // 3), "nt")
             for n in range(4)]
    done = Item("button", "Done", 0.9, 0.05, widget=1)
    w.options = other + eq + inv + [done]
    w.config = {"layout": {"section_names": {"inv": "Equipment", "int": "Inventory"}}}
    find = lambda label: next(n for n, i in enumerate(w.options) if i.label == label)
    w.cursor = find("Body")
    w.handle_keys([keys.LEFT]);  assert w.options[w.cursor].label == "Hands"
    w.handle_keys([keys.UP]);    assert w.options[w.cursor].label == "Hands"   # top of its column
    w.handle_keys([keys.RIGHT]); assert w.options[w.cursor].label == "Body"
    w.handle_keys([keys.UP]);    assert w.options[w.cursor].label == "Head"
    w.handle_keys([keys.RIGHT]); assert w.options[w.cursor].label == "Weapon 1"
    w.handle_keys([keys.RIGHT]); assert w.options[w.cursor].label == "Weapon 1"   # edge: stays
    w.handle_keys([keys.TAB])
    assert w.options[w.cursor].label == "Inventory 1" and said[-1].startswith("Inventory: ")
    w.handle_keys([keys.DOWN, keys.RIGHT]); assert w.options[w.cursor].label == "Inventory 5"
    w.handle_keys([keys.END]);   assert w.options[w.cursor].label == "Inventory 9"
    w.handle_keys([keys.SHIFT_TAB, keys.TAB])     # away and back: same cell
    assert w.options[w.cursor].label == "Inventory 9"
    w.handle_keys([keys.TAB, keys.TAB])           # Done, then round to Discard
    assert w.options[w.cursor].label == "Discard 1" and said[-1].startswith("Discard: ")
    assert w.has_sections()


def test_equipment_columns_down_and_across():
    """The user's report: Down from Feet went to Weapon 4, then the Horse."""
    from mbaccess import keys
    from mbaccess.form import Item
    w = MenuWatcher(None, None, {}, [], lambda s: None)
    cells = [("Head", 0.451, 0.605), ("Body", 0.451, 0.517), ("Feet", 0.451, 0.429),
             ("Hands", 0.363, 0.517), ("Horse", 0.363, 0.317)] + \
            [(f"Weapon {n + 1}", 0.552, 0.605 - 0.088 * n) for n in range(4)]
    w.options = [Item("slot", l, x, y, group="inv", widget=n + 1) for n, (l, x, y) in enumerate(cells)]
    w.config = {}
    at = lambda: w.options[w.cursor].label
    w.cursor = 0
    w.handle_keys([keys.DOWN]);  assert at() == "Body"
    w.handle_keys([keys.DOWN]);  assert at() == "Feet"
    w.handle_keys([keys.DOWN]);  assert at() == "Feet"          # bottom of the column
    w.handle_keys([keys.LEFT]);  assert at() == "Hands"         # nearest in height
    w.handle_keys([keys.DOWN]);  assert at() == "Horse"
    w.handle_keys([keys.RIGHT]); assert at() == "Feet"
    w.handle_keys([keys.RIGHT]); assert at() == "Weapon 3"
    w.handle_keys([keys.DOWN]);  assert at() == "Weapon 4"


def test_cell_names_drop_only_the_grids_own_name():
    from mbaccess.form import Item
    w = MenuWatcher(None, None, {}, [], lambda s: None)
    w.options = [Item("slot", "Weapon 1", 0.55, 0.6, group="inv", widget=1),
                 Item("slot", "Inventory 5", 0.7, 0.6, group="int", widget=2),
                 Item("text", "Discard", 0.07, 0.71, widget=3),
                 Item("slot", "Discard 2", 0.11, 0.61, group="nt", widget=4)]
    w.config = {"layout": {"section_names": {"inv": "Equipment", "int": "Inventory"}}}
    assert [w.cell_name(i) for i in w.options if i.kind == "slot"] == ["Weapon 1", "5", "2"]
    assert ("list", "details") not in w.sections()     # the heading names its grid


def test_inventory_cells_named_from_memory():
    """A cell's item comes from the troop via the window's widget tables:
    instant names, "empty", the quality word, and None for the Discard pile
    (no screen troop), which falls back to the tooltip."""
    from mbaccess.form import Item
    mem = FakeMemory()
    WIN, TROOPS, KINDS, MODS = 0x30000000, 0x31000000, 0x32000000, 0x33000000
    inv = {"troops": 0x100, "troop_size": 0x1000, "troop_bag": 0x2d0, "troop_equipment": 0xf68,
           "screen_troop": 0x104, "bag_cells": 0x174, "equipment_cells": 0xa80, "per_side": [96, 10],
           "modifiers": MODS, "modifier_size": 0x128, "bag_prices": 0x774, "no_price": 77777}
    window = bytearray(0x1000)
    struct.pack_into("<3I", window, 0x174, 0xA0, 0xA1, 0xA2)        # your bag cells 0-2
    struct.pack_into("<I", window, 0x174 + 96 * 4, 0xB0)              # Discard cell 0
    struct.pack_into("<2i", window, 0x774, 77777, 44)                  # trade prices: none, 44
    struct.pack_into("<3I", window, 0xa80, 0xC0, 0xC1, 0xC2)         # Weapon 1-3
    mem.write(WIN, window)
    game = bytearray(0x200)
    struct.pack_into("<Ii", game, 0x100, TROOPS, -1)                  # no screen troop
    mem.write(GAME, game)
    troop = bytearray(0x1000)
    struct.pack_into("<4i", troop, 0x2d0, -1, 0, 2, 0)                # bag: empty, Fish
    struct.pack_into("<6i", troop, 0xf68, -1, 0, -1, 0, 1, 2 << 24)   # Weapon 3: Rusty Sword
    mem.write(TROOPS, troop)
    mem.write(KINDS - 0x100, struct.pack("<Ii", KINDS, 3) + bytes(0xf8))
    mem.write(KINDS, b"".join(pack_rgl_string(KINDS + 0x90 * n, name)
                              for n, name in enumerate(["INVALID", "Sword", "Smoked Fish"])))
    mem.write(MODS, b"".join(pack_rgl_string(MODS + 0x128 * n, name).ljust(0x128, b"\0")
                             for n, name in enumerate(["Plain %s", "Cracked %s", "Rusty %s"])))
    screen = {"inventory": inv, "item_kinds": KINDS - 0x100, "item_kind_size": 0x90}
    said = []
    w = MenuWatcher(Reader(mem), GAME, {}, [], lambda t, interrupt=True: said.append(t), screen=screen)
    w.top_window, w.window = (lambda: 7), (lambda n: WIN)
    cell = lambda widget, label, group: Item("slot", label, 0.7, 0.5, group=group, widget=widget)
    assert w.cell_contents(cell(0xA0, "Inventory 1", "int")) == ""
    assert w.cell_contents(cell(0xA1, "Inventory 2", "int")) == "Smoked Fish"
    assert w.cell_contents(cell(0xC2, "Weapon 3", "inv")) == "Rusty Sword"
    assert w.cell_contents(cell(0xB0, "Discard 1", "nt")) is None     # nobody's: ask the tooltip
    w.options, w.cursor = [cell(0xC2, "Weapon 3", "inv")], 0
    w.config = {"layout": {"section_names": {"inv": "Equipment", "int": "Inventory"}}}
    w.settings = {"item_details": "Name only"}
    w.name_cell()
    assert said[-1] == "Rusty Sword, Weapon 3, 1 of 1" and w.tip_wait is None  # no waiting at all
    w.options = [cell(0xA1, "Inventory 2", "int")]
    w.settings = {"item_details": "Name and price"}
    w.name_cell()
    assert said[-1] == "Smoked Fish, price 44, 2, 1 of 1"                       # trading: price from the window
    assert w.options[0].action("quick")[0] == "ctrl click"               # Ctrl+Enter


def test_aim_check_learns_a_letterboxed_screen(tmp_path):
    from mbaccess import menu_watch
    from mbaccess.form import Item
    w, said, _ = make_menu_watcher()
    button = 0x44000000
    w.reader = Reader(FakeMemory())
    w.reader.source.write(button, bytes(0x200))

    class BarsMouse:            # the button lights up only when we aim with bars
        letterbox = False
        def hover(self, x, y):
            w.reader.source.blocks[button][menu_watch.HIGHLIGHT] = int(self.letterbox)
    w.mouse = BarsMouse()
    w.learned, w.learned_path = {}, str(tmp_path / "learned.json")
    w.options, w.cursor = [Item("button", "Save", 0.18, 0.3, widget=button)], 0
    w.last, w.config = (5, None, "", ()), {}
    w.hover()
    w.aim_check = (0, button, False)        # pretend the wait is over
    w.check_aim()
    assert w.trial is True and w.mouse.letterbox is True
    w.aim_check = (0, button, True)
    w.check_aim()
    assert w.learned == {"5": True} and w.trial is None
    assert "True" in open(w.learned_path).read() or "true" in open(w.learned_path).read()


def test_scanner_names_and_directions():
    import math
    from mbaccess import scanner
    assert scanner.prop_name("spr_village_house_e") == "village house"
    assert scanner.prop_name("spr_castle_f_stairs_a") == "castle stairs"
    assert scanner.prop_name("spr_torch_night") == "torch"
    # Facing: forward is the stored angle plus a quarter turn, so stored 0 faces +y.
    player = (0.0, 0.0, 0.0, 0.0, False)
    d, a = scanner.relative(player, 0.5, 10)       # mostly ahead, a little right
    assert scanner.quarter(a) == keys.KEY_O and a < 0
    assert scanner.quarter(scanner.relative(player, -5, 1)[1]) == keys.KEY_K
    assert scanner.quarter(scanner.relative(player, 5, 1)[1]) == keys.SEMICOLON
    assert scanner.quarter(scanner.relative(player, 0, -5)[1]) == keys.KEY_L
    assert scanner.describe_angle(20) == "ahead, slightly left"
    assert scanner.describe_angle(-90) == "right"


def test_turning_compass_and_ping():
    import math
    from mbaccess import turning, wall_beeps
    # stored angle 0 faces +y, which is north; a quarter turn left faces west
    assert turning.compass(0.0) == "north"
    assert turning.compass(math.pi / 2) == "west"
    assert turning.wrap(350) == -10
    assert wall_beeps.ping_pitch(30) == 1.0
    assert abs(wall_beeps.ping_pitch(180) - wall_beeps.PING_BEHIND_PITCH) < 1e-9
    assert wall_beeps.ping_interval(1) == wall_beeps.PING_FAST
    assert abs(wall_beeps.ping_interval(100) - wall_beeps.PING_SLOW) < 1e-9


def test_map_f_search_cycles_matches_only():
    """On the map letters are the game's; F starts a search, letters filter by
    a word in the name, Up/Down cycle the matches, Escape ends it."""
    from mbaccess import keys
    from mbaccess.form import Item
    said = []
    w = MenuWatcher(None, None, {}, [], said.append)
    names = ["Jelkala, town, 18 north", "Ibdeles Castle, castle, 12 west", "Ibdeles, village, 3 east",
             "Culmarr Castle, castle, 40 south", "Veluca, town, 30 east"]
    w.options = [Item("button", n, 0.1, 0.9 - k * 0.03, widget=k + 1) for k, n in enumerate(names)]
    w.config = {"type_search": "after_f"}
    assert not w.searching() and w.search_key()
    w.handle_keys([keys.KEY_F]);  assert said[-1] == "search" and w.searching()
    w.handle_keys([0x43, 0x41])   # "ca"
    assert said[-1].startswith("2 found, Ibdeles Castle") and said[-1].endswith("1 of 2")
    w.handle_keys([keys.DOWN]);   assert w.options[w.cursor].label.startswith("Culmarr")
    w.handle_keys([keys.DOWN]);   assert w.options[w.cursor].label.startswith("Ibdeles Castle")
    w.handle_keys([keys.ESCAPE]); assert said[-1] == "search off" and not w.searching()
