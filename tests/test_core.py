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
    assert spoken == ["You are in Praven.\nOptions: Visit the tavern."]
    mem.blocks[GAME][MENU_NO_OFFSET:MENU_NO_OFFSET + 4] = struct.pack("<i", 0)
    watcher.poll()
    assert len(spoken) == 2


def test_watcher_off_until_discovered():
    spoken = []
    watcher = MenuWatcher(Reader(make_game(1, "x")), GAME, {"cur_menu_no": None}, [], spoken.append)
    watcher.poll()
    assert spoken == []


# --- menu buttons and keyboard cursor ------------------------------------

from mbaccess import click, keys

WINDOWS = 0x40000000   # pretend game_windows[32] array
OPEN = 0x40001000      # pretend open-window deque header
SCREEN = {"game_windows": WINDOWS, "open_windows": OPEN, "menu_buttons": 0x10,
          "menu_button_slots": 4, "widget_text": 0x100, "widget_position": 0x40,
          "widget_flags": 0x50}


def add_menu_window(mem, buttons, top=18):
    """buttons: list of (text, y, hidden). Slots after them are blank and hidden."""
    window = 0x41000000
    slots = [0x42000000 + i * 0x1000 for i in range(4)]
    mem.write(WINDOWS, struct.pack("<32I", *([0] * 18 + [window] + [0] * 13)))
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
                    [], said.append, screen=SCREEN, clicker=lambda x, y: clicks.append((x, y)))
    return w, said, clicks


def test_menu_reads_visible_buttons_top_first():
    w, said, _ = make_menu_watcher()
    w.poll()
    assert said == ["Welcome\nContinue..., 1 of 2"]


def test_menu_cursor_and_enter_click():
    w, said, clicks = make_menu_watcher()
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
