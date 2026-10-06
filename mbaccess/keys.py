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
ALL = (UP, DOWN, RETURN, HOME, END, LEFT, RIGHT, SPACE, F9, ESCAPE,
       LEFT_BRACKET, RIGHT_BRACKET, SEMICOLON, QUOTE, CONTROL)


def is_down(vk):
    """Is this key held right now? For modifiers: Shift+Enter is an Enter
    that went down while is_down(SHIFT) is true."""
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


class KeyWatcher:
    def __init__(self, hwnd_getter, keys=ALL):
        self.hwnd_getter = hwnd_getter  # function returning the game window
        self.keys = keys
        self.down = set()

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
            vk = SIDES.get(info.vkCode, info.vkCode)
            if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                if vk in self.keys and (vk not in self.held or vk in REPEATS):
                    self.events.put((vk, _user32.GetForegroundWindow(), vk in self.held))
                    self.arrived.set()
                self.held.add(vk)
            elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                self.held.discard(vk)
        return _user32.CallNextHookEx(None, code, wparam, lparam)

    def wait(self, seconds):
        """Sleep until a key arrives or the time is up, whichever is first."""
        self.arrived.wait(seconds)

    def pressed(self):
        """Keys that went down since the last call, in order, while the game was in front."""
        self.arrived.clear()
        hwnd = self.hwnd_getter()
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
