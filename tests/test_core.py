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
                    [], said.append, screen=SCREEN, mouse=FakeMouse(clicks))
    return w, said, clicks


def test_menu_reads_visible_buttons_top_first():
    w, said, _ = make_menu_watcher()
    w.poll()
    assert said == ["Welcome. Continue..., 1 of 2."]


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


def test_main_menu_without_a_campaign():
    mem = FakeMemory()
    add_menu_window(mem, [("Start a New Game", 0.44, False), ("Play Tutorial", 0.48, False)],
                    top=4, number=4)
    said, clicks = [], []
    w = MenuWatcher(Reader(mem), None, {"cur_menu_no": MENU_NO_OFFSET,
                                        "cur_menu_text": MENU_TEXT_OFFSET},
                    [], said.append, screen=SCREEN, mouse=FakeMouse(clicks))
    w.poll()
    assert said == ["Main menu: Play Tutorial, 1 of 2."]
    w.poll([keys.DOWN, keys.RETURN])
    assert clicks == [pytest.approx((0.015 + 0.15, 0.44 + 0.012))]


def test_game_menu_waits_for_the_campaign():
    mem = FakeMemory()
    add_menu_window(mem, [("Continue...", 0.22, False)])
    said = []
    w = MenuWatcher(Reader(mem), None, {"cur_menu_no": MENU_NO_OFFSET,
                                        "cur_menu_text": MENU_TEXT_OFFSET},
                    [], said.append, screen=SCREEN)
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
    watch.handle_keys([keys.SEMICOLON, keys.SEMICOLON, keys.SEMICOLON, keys.RIGHT_BRACKET])
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


def make_conversation(line, replies, on_screen):
    """A fake conversation manager (found from the skill table after it) and
    conversation window 12 whose tree shows the replies in on_screen."""
    from mbaccess import conversation as conv
    mem = FakeMemory()
    skill_id = 0x50000000                    # skills[0].id, "skl_trade"
    text_at = conv.speaker_text_from_skill_id(skill_id)
    start = text_at + conv.NUM_OPTIONS - 36  # the manager's first field
    data = bytearray(skill_id + 0x90 - start)
    put = lambda at, raw: data.__setitem__(slice(at - start, at - start + len(raw)), raw)
    put(skill_id, pack_rgl_string(skill_id, "skl_trade"))
    put(text_at, pack_rgl_string(text_at, line))
    put(text_at + conv.NUM_OPTIONS, struct.pack("<i", len(replies)))
    put(text_at + conv.PARTNER_TROOP, struct.pack("<i", 1))
    for n, words in enumerate(replies):
        at = text_at + conv.PARTNER_OPTIONS + n * conv.OPTION_SIZE + conv.OPTION_TEXT
        put(at, pack_rgl_string(at, words))
    mem.write(start, data)
    # Troops for the partner's name: troop 1 is "Ramun".
    troops = 0x51000000
    mem.write(GAME, struct.pack("<II", troops, 2))
    mem.write(troops, bytes(0x104) + pack_rgl_string(troops + 0x104, "Ramun"))
    # Window 12: a root widget (class 0x777) with one text widget per reply.
    window, root = 0x52000000, 0x53000000
    kids = [0x54000000 + n * 0x1000 for n in range(len(on_screen))]
    mem.write(WINDOWS, struct.pack("<32I", *([0] * 12 + [window] + [0] * 19)))
    mem.write(window, bytes(0x13c) + struct.pack("<I", root))
    obj = bytearray(0x400)
    obj[0:4] = struct.pack("<I", 0x777)
    obj[0x2d0:0x2d0 + 144] = pack_rgl_string(root + 0x2d0, "conversation")
    obj[0x364:0x370] = struct.pack("<III", 0x55000000, 0x55000000 + 4 * len(kids), 0x55000000 + 64)
    mem.write(root, obj)
    mem.write(0x55000000, struct.pack(f"<{len(kids)}I", *kids) + bytes(64))
    for n, (address, words) in enumerate(zip(kids, on_screen)):
        obj = bytearray(0x400)
        obj[0x40:0x48] = struct.pack("<ff", 0.3, 0.2 - 0.04 * n)
        obj[0x100:0x100 + 144] = pack_rgl_string(address + 0x100, words)
        obj[0x1ac:0x1b4] = struct.pack("<ff", 0.4, 0.03)
        mem.write(address, obj)
    mem.write(OPEN, struct.pack("<IIII", 0x43000000, 8, 0, 1))
    mem.write(0x43000000, struct.pack("<8I", 0x43001000, *[0] * 7))
    mem.write(0x43001000, struct.pack("<4i", 12, 0, 0, 0))
    return mem


def test_conversation_found_read_and_answered():
    from mbaccess import conversation as conv
    replies = ["I want to trade.", "Farewell."]
    mem = make_conversation("Good day, {playername}. ^What brings you here?",
                            replies, ["Good day.", "Farewell.", "I want to trade."])
    text_at = conv.find(mem, "skl_trade", whole_memory=True)
    assert text_at == conv.speaker_text_from_skill_id(0x50000000)
    screen = dict(SCREEN, classes={"0x777": "root"},
                  windows={"12": {"conversation": True}},
                  party_skills={"troops": 0, "troop_size": 0x100})
    said, clicks = [], []
    talk = conv.Conversation(Reader(mem), {"speaker_text": text_at})
    w = MenuWatcher(Reader(mem), GAME, {}, [], said.append, screen=screen,
                    mouse=FakeMouse(clicks), conversation=talk)
    w.poll()
    assert said == ["Ramun: Good day, . What brings you here? I want to trade., 2 of 3."]
    w.poll([keys.UP])
    assert said[-1] == "Ramun: Good day, .\nWhat brings you here?, 1 of 3"
    w.poll([keys.END, keys.RETURN])
    assert clicks == [pytest.approx((0.3 + 0.2, 0.16 + 0.015))]
    assert w.help_group() == "Conversations"
