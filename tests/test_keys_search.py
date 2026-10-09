"""Escape (the screen's way back) and type search, on a made-up list."""
from mbaccess import menu_watch
from mbaccess.form import Item
from mbaccess.menu_watch import MenuWatcher


def watcher(*labels, config=None):
    said = []
    w = MenuWatcher(None, None, {}, [], said.append)
    w.options = [Item("option", label, 0.0, 0.0, widget=n + 1) for n, label in enumerate(labels)]
    w.config = config or {}
    return w, said


def test_escape_finds_the_last_way_back():
    w, _ = watcher("Go to the village center.", "Leave the kingdom", "Leave...")
    assert w.back_item() == 2
    w, _ = watcher("Wait here for some time.", "Resume travelling.")
    assert w.back_item() == 1
    w, _ = watcher("Camp", "Reports", "Party")
    assert w.back_item() is None            # the game keeps Escape (pause menu)
    w, _ = watcher("Go back", config={"escape": False})
    assert w.back_item() is None


def test_type_search_builds_words_and_repeats(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(menu_watch.time, "monotonic", lambda: clock[0])
    w, said = watcher("Ibdeles", "Jamiche", "Jelkala", "Jamiche Castle", "Veluca")
    w.type_search("j")
    assert w.cursor == 1
    w.type_search("e")                      # quickly after: "je"
    assert w.cursor == 2
    clock[0] += 2                           # a pause starts a new search
    w.type_search("j")
    assert w.cursor == 3
    w.type_search("j")                      # the same letter again: next one
    assert w.cursor == 1
    clock[0] += 2
    w.type_search("x")
    assert w.cursor == 1 and said[-1] == "No x"


def test_shift_enter_says_when_nothing_happens():
    import time
    w, said = watcher("Inventory 1")
    w.special_check = (time.time(), "Smoked Fish")
    w.check_special()
    assert said == []                       # still waiting for a question to open
    w.special_check = (time.time() - 1, "Smoked Fish")
    w.check_special()
    assert said == ["nothing to do with Smoked Fish"] and w.special_check is None
