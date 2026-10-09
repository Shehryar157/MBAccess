"""Noticing our hotkeys while the game window is in front.

Two ways, with the same pressed() method:
- HookKeyWatcher (used): a low-level keyboard hook. Windows calls our
  function on every key press, like an event handler; it drops the key
  into a queue and the main loop empties the queue each tick. No press is
  lost, even while the mod is busy clicking.
- KeyWatcher (fallback): GetAsyncKeyState(vk) asks "is this key down right
  now?" every tick. A quick press between two looks is missed.
Either way we react once when a key goes down, not while it's held, and
only when the game is the foreground window.
"""
import ctypes
import queue
import threading
import time
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32")

UP, DOWN, RETURN, HOME, END = 0x26, 0x28, 0x0D, 0x24, 0x23
LEFT, RIGHT, SPACE = 0x25, 0x27, 0x20
F9, ESCAPE = 0x78, 0x1B   # F9: our help (F1-F4 are the game's battle orders)
SHIFT, CONTROL = 0x10, 0x11   # either side's key
# The message keys, by where they are on a US keyboard ("OEM" keys move
# about on other layouts).
LEFT_BRACKET, RIGHT_BRACKET, SEMICOLON, QUOTE = 0xDB, 0xDD, 0xBA, 0xDE
COMMA, PERIOD = 0xBC, 0xBE
TAB = 0x09
# Not real key codes: the hook reports these key combinations as their own.
SHIFT_TAB, CTRL_LEFT, CTRL_RIGHT = 0x109, 0x125, 0x127
ALT = 0x12
# Type search: a letter or digit's key code is its capital character (VK_A = "A").
LETTERS = tuple(range(0x30, 0x3A)) + tuple(range(0x41, 0x5B))
KEY_J, KEY_K, KEY_L, KEY_O = 0x4A, 0x4B, 0x4C, 0x4F   # the scene scanner
KEY_A, KEY_D = 0x41, 0x44         # Shift+A / Shift+D: turn in a scene
ALL = (UP, DOWN, RETURN, HOME, END, LEFT, RIGHT, SPACE, F9, ESCAPE,
       LEFT_BRACKET, RIGHT_BRACKET, SEMICOLON, QUOTE, COMMA, PERIOD, CONTROL, TAB) + LETTERS


def is_down(vk):
    """Is this key held right now? For modifiers: Shift+Enter is an Enter
    that went down while is_down(SHIFT) is true."""
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


class KeyWatcher:
    def __init__(self, hwnd_getter, keys=ALL):
        self.hwnd_getter = hwnd_getter  # function returning the game window
        self.keys = keys
        self.down = set()
        self.swallow, self.game_hwnd = frozenset(), None    # polling can't hide keys
        self.swallow_shifted = frozenset()

    def wait(self, seconds):
        time.sleep(seconds)     # polling can't be woken by a key

    def pressed(self):
        """Keys that went down since the last call (empty if game not in front)."""
        hwnd = self.hwnd_getter()
        if not hwnd or _user32.GetForegroundWindow() != hwnd:
            self.down.clear()
            return []
        now = {k for k in self.keys if is_down(k)}
        new = [k for k in self.keys if k in now and k not in self.down]
        self.down = now
        return new


# --- the keyboard hook -----------------------------------------------------

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
LLKHF_INJECTED = 0x10
# The hook sees which side's Shift or Ctrl it was; we only care that it was one.
SIDES = {0xA0: SHIFT, 0xA1: SHIFT, 0xA2: CONTROL, 0xA3: CONTROL}
# Held down, these repeat at the Windows keyboard repeat rate, as in any list.
REPEATS = {UP, DOWN, LEFT, RIGHT}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
# Our Python is 64-bit: without argtypes, ctypes would cut handles to 32 bits.
_user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_user32.CallNextHookEx.restype = LRESULT
_user32.GetForegroundWindow.restype = wintypes.HWND


class HookKeyWatcher:
    def __init__(self, hwnd_getter, keys=ALL):
        self.hwnd_getter = hwnd_getter
        self.keys = set(keys)
        self.events = queue.Queue()     # (key, window in front, is it a repeat)
        self.held = set()               # to skip the auto-repeat of a held key
        self.arrived = threading.Event()   # set by the hook: wakes wait() at once
        self.swallow = frozenset()      # keys to hide from the game (set by run.py)
        self.swallow_shifted = frozenset()  # hidden only while Shift is held
        self.hidden_down = set()        # keys whose press we hid: hide their release too
        self.passed_down = set()        # keys whose press the game got: so will the release
        self.game_hwnd = None           # remembered here: the hook must not search for it
        self._proc = HOOKPROC(self._on_key)   # keep a reference, or it's freed
        ready = threading.Event()
        self.ok = False

        def run():
            # A hook belongs to the thread that set it, and that thread
            # must keep pumping messages for Windows to call it.
            hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
            self.ok = bool(hook)
            ready.set()
            if not hook:
                return
            msg = wintypes.MSG()
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))

        threading.Thread(target=run, daemon=True, name="key hook").start()
        ready.wait(2)

    def _on_key(self, code, wparam, lparam):
        # Keep this quick: every key press on the computer waits for it.
        if code == 0:
            info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if info.flags & LLKHF_INJECTED:
                # Our own simulated keys (holding D to turn the horse) go straight
                # to the game: never swallowed, never reported back to us.
                return _user32.CallNextHookEx(None, code, wparam, lparam)
            vk = SIDES.get(info.vkCode, info.vkCode)
            front = _user32.GetForegroundWindow()
            if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                if vk in self.keys and (vk not in self.held or vk in REPEATS):
                    reported = vk
                    if vk == TAB and SHIFT in self.held:
                        reported = SHIFT_TAB
                    elif vk in (LEFT, RIGHT) and CONTROL in self.held:
                        reported = CTRL_LEFT if vk == LEFT else CTRL_RIGHT
                    self.events.put((reported, front, vk in self.held))
                    self.arrived.set()
                self.held.add(vk)
            elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                self.held.discard(vk)
            # Keys the mod owns on this screen never reach the game. Not with
            # Alt held (WM_SYSKEY...), so Alt+Tab still switches programs.
            # A release follows its press: if the game got the press it must get
            # the release, even if the screen (and so self.swallow) changed in
            # between, or the game thinks the key is still held (a horse kept
            # turning after D was let go, 2026-10-10).
            # Decided on the first press; auto-repeats and the release follow it.
            if wparam == WM_KEYDOWN:
                if vk in self.hidden_down:
                    return 1
                if vk not in self.passed_down:
                    ours = vk in self.swallow or (vk in self.swallow_shifted and SHIFT in self.held)
                    if ours and front and front == self.game_hwnd:
                        self.hidden_down.add(vk)
                        return 1
                    self.passed_down.add(vk)
            elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                self.passed_down.discard(vk)
                if vk in self.hidden_down:
                    self.hidden_down.discard(vk)
                    return 1
        return _user32.CallNextHookEx(None, code, wparam, lparam)

    def wait(self, seconds):
        """Sleep until a key arrives or the time is up, whichever is first."""
        self.arrived.wait(seconds)

    def pressed(self):
        """Keys that went down since the last call, in order, while the game was in front."""
        self.arrived.clear()
        hwnd = self.game_hwnd = self.hwnd_getter()
        new = []
        while True:
            try:
                vk, front, repeat = self.events.get_nowait()
            except queue.Empty:
                return new
            # Repeats that piled up while we were busy count once, so a
            # held arrow doesn't keep going after it's let go.
            if hwnd and front == hwnd and not (repeat and vk in new):
                new.append(vk)


def watcher(hwnd_getter):
    """The hook if Windows lets us set one, else the polling watcher."""
    hooked = HookKeyWatcher(hwnd_getter)
    return hooked if hooked.ok else KeyWatcher(hwnd_getter)
