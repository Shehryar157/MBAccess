"""The keyboard hook's decisions, fed made-up key messages (no real hook installed)."""
import ctypes
import queue

from mbaccess import keys

GAME = 1234
W = 0x57
PASSED, HIDDEN = "passed", "hidden"


def hook(in_scene):
    h = keys.HookKeyWatcher.__new__(keys.HookKeyWatcher)   # skip installing a real hook
    h.keys, h.held, h.events = set(), set(), queue.Queue()
    h.swallow, h.swallow_shifted, h.swallow_ctrl = frozenset(), frozenset(), frozenset()
    h.hidden_down, h.passed_down = set(), set()
    h.game_hwnd, h.quiet_repeats = GAME, in_scene
    return h


def send(h, message, vk=W):
    info = keys.KBDLLHOOKSTRUCT(vk, 0, 0, 0, 0)
    result = h._on_key(0, message, ctypes.addressof(info))
    return HIDDEN if result == 1 else PASSED


def test_walking_hides_auto_repeats_but_not_the_press_or_release(monkeypatch):
    monkeypatch.setattr(keys._user32, "GetForegroundWindow", lambda: GAME)
    h = hook(in_scene=True)
    assert send(h, keys.WM_KEYDOWN) == PASSED       # the game starts walking
    assert send(h, keys.WM_KEYDOWN) == HIDDEN       # repeats: NVDA keeps talking
    assert send(h, keys.WM_KEYDOWN) == HIDDEN
    assert send(h, keys.WM_KEYUP) == PASSED         # the game stops walking
    assert send(h, keys.WM_KEYDOWN) == PASSED       # a new press is a press again


def test_repeats_pass_outside_scenes(monkeypatch):
    monkeypatch.setattr(keys._user32, "GetForegroundWindow", lambda: GAME)
    h = hook(in_scene=False)                        # typing a name: wwww must work
    assert send(h, keys.WM_KEYDOWN) == PASSED
    assert send(h, keys.WM_KEYDOWN) == PASSED


def test_repeats_pass_when_another_program_is_in_front(monkeypatch):
    monkeypatch.setattr(keys._user32, "GetForegroundWindow", lambda: 99)
    h = hook(in_scene=True)
    assert send(h, keys.WM_KEYDOWN) == PASSED
    assert send(h, keys.WM_KEYDOWN) == PASSED
