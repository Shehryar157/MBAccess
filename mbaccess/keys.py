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
# Screen reader modifier keys (NVDA's Insert, or Caps Lock if set so): while one
# is held, keys belong to the screen reader.
NVDA_KEYS = {0x2D, 0x14}
LETTERS = tuple(range(0x30, 0x3A)) + tuple(range(0x41, 0x5B))
KEY_J, KEY_K, KEY_L, KEY_O = 0x4A, 0x4B, 0x4C, 0x4F   # the scene scanner
KEY_A, KEY_D, KEY_S = 0x41, 0x44, 0x53   # Shift+A/D/S: turn in a scene; Ctrl+A/D: face the nearest thing
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
        self.swallow_shifted = self.swallow_ctrl = frozenset()

    def wait(self, seconds):
        time.sleep(seconds)     # polling can't be woken by a key

    def is_held(self, vk):
        return is_down(vk)

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
        self.swallow_ctrl = frozenset()     # hidden only while Ctrl is held
        self.hidden_down = set()        # keys whose press we hid: hide their release too
        self.passed_down = set()        # keys whose press the game got: so will the release
        self.quiet_repeats = False      # set by run.py while walking in a scene
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
            if NVDA_KEYS & self.held and vk not in NVDA_KEYS:
                # A screen reader command (NVDA+T reads the title): not ours,
                # and never swallowed. A release still clears our state.
                if wparam in (WM_KEYUP, WM_SYSKEYUP):
                    self.held.discard(vk)
                    self.passed_down.discard(vk)
                    if vk in self.hidden_down:
                        self.hidden_down.discard(vk)
                        return 1
                return _user32.CallNextHookEx(None, code, wparam, lparam)
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
                if vk in self.passed_down and self._quiet_repeats() and front and front == self._game():
                    # An auto-repeat of a key the game already holds (walking with W).
                    # NVDA stops speaking on every key down, repeats too, so "crude
                    # fence" was cut off while walking. The game only checks whether
                    # the key is down, which it still is, so it loses nothing. We sit
                    # before NVDA in the hook chain (installed later), so it never
                    # sees the repeat either.
                    return 1
                if vk not in self.passed_down:
                    if self._owns(vk) and front and front == self._game():
                        self.hidden_down.add(vk)
                        return 1
                    self.passed_down.add(vk)
            elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                self.passed_down.discard(vk)
                if vk in self.hidden_down:
                    self.hidden_down.discard(vk)
                    return 1
        return _user32.CallNextHookEx(None, code, wparam, lparam)

    def _owns(self, vk):
        """Does the mod take this key from the game right now?"""
        return (vk in self.swallow or (vk in self.swallow_shifted and SHIFT in self.held)
                or (vk in self.swallow_ctrl and CONTROL in self.held))

    def _game(self):
        return self.game_hwnd

    def _quiet_repeats(self):
        """Hide auto-repeats from the game and NVDA right now? (Walking in a scene.)"""
        return self.quiet_repeats

    def is_held(self, vk):
        """Is the key down now? Works for keys we hide from the game, which Windows'
        own key state never sees."""
        return vk in self.held

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


# --- the hook in its own process ----------------------------------------------
#
# Windows holds every key press back from the game until our hook function returns.
# Python runs one thread at a time (the GIL), so a hook in the mod's own process waits
# whenever the wall beeps, the scanner or speech are running: walking felt sluggish.
# In its own process the hook has Python to itself and answers in microseconds.
# The two processes share a table of which keys the mod owns (bit 1: always,
# bit 2: only with Shift held, bit 4: only with Ctrl held) and the game's window; presses come back on a queue.

OWN, OWN_SHIFTED, OWN_CTRL = 1, 2, 4


class _SharedHook(HookKeyWatcher):
    """The hook as it runs inside the hook process."""

    def __init__(self, flags, hwnd, events, held, quiet):
        self.flags, self.hwnd, self.held_flags, self.quiet = flags, hwnd, held, quiet
        super().__init__(None)
        self.events = events

    def _on_key(self, code, wparam, lparam):
        if code == 0:
            info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = SIDES.get(info.vkCode, info.vkCode)
            if vk < len(self.held_flags) and not info.flags & LLKHF_INJECTED:
                self.held_flags[vk] = 1 if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN) else 0
        return super()._on_key(code, wparam, lparam)

    def _owns(self, vk):
        bits = self.flags[vk] if vk < len(self.flags) else 0
        return bool(bits & OWN or (bits & OWN_SHIFTED and SHIFT in self.held)
                    or (bits & OWN_CTRL and CONTROL in self.held))

    def _game(self):
        return self.hwnd.value

    def _quiet_repeats(self):
        return bool(self.quiet.value)


def _hook_process(flags, hwnd, events, held, quiet, ready):
    import multiprocessing
    # Every key on the computer waits for this hook, so let Windows run it ahead of
    # ordinary programs (its work takes microseconds, so nothing else suffers).
    HIGH_PRIORITY_CLASS = 0x80
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), HIGH_PRIORITY_CLASS)
    ctypes.WinDLL("winmm").timeBeginPeriod(1)
    hook = _SharedHook(flags, hwnd, events, held, quiet)
    ready.put(hook.ok)
    parent = multiprocessing.parent_process()
    # Leave with the mod: a hook nobody reads would keep swallowing keys.
    while parent is None or parent.is_alive():
        time.sleep(0.5)


class ProcessKeyWatcher:
    """Same methods as HookKeyWatcher; the hook itself runs in a child process."""

    def __init__(self, hwnd_getter):
        import multiprocessing
        ctx = multiprocessing.get_context("spawn")
        self.hwnd_getter = hwnd_getter
        self.flags = ctx.Array("B", 0x200, lock=False)
        self.hwnd = ctx.Value("q", 0, lock=False)
        self.events = ctx.Queue()
        self.held = ctx.Array("B", 0x200, lock=False)     # 1 while a key is down
        self.quiet = ctx.Value("b", 0, lock=False)        # 1: hide auto-repeats (walking)
        self.early = []         # events wait() took off the queue: pressed() returns them
        self._swallow, self._shifted, self._ctrl = frozenset(), frozenset(), frozenset()
        ready = ctx.Queue()
        self.process = ctx.Process(target=_hook_process,
                                   args=(self.flags, self.hwnd, self.events, self.held, self.quiet, ready),
                                   daemon=True, name="MB Access keys")
        self.process.start()
        try:
            self.ok = ready.get(timeout=10)
        except queue.Empty:
            self.ok = False
        if not self.ok:
            self.process.terminate()

    def _set(self, old, new, bit):
        for vk in old - new:
            self.flags[vk] &= ~bit
        for vk in new - old:
            self.flags[vk] |= bit

    @property
    def swallow(self):
        return self._swallow

    @swallow.setter
    def swallow(self, keys):
        keys = frozenset(keys)
        if keys != self._swallow:
            self._set(self._swallow, keys, OWN)
            self._swallow = keys

    @property
    def swallow_shifted(self):
        return self._shifted

    @swallow_shifted.setter
    def swallow_shifted(self, keys):
        keys = frozenset(keys)
        if keys != self._shifted:
            self._set(self._shifted, keys, OWN_SHIFTED)
            self._shifted = keys

    @property
    def swallow_ctrl(self):
        return self._ctrl

    @swallow_ctrl.setter
    def swallow_ctrl(self, keys):
        keys = frozenset(keys)
        if keys != self._ctrl:
            self._set(self._ctrl, keys, OWN_CTRL)
            self._ctrl = keys

    @property
    def quiet_repeats(self):
        return bool(self.quiet.value)

    @quiet_repeats.setter
    def quiet_repeats(self, on):
        if bool(self.quiet.value) != bool(on):
            self.quiet.value = 1 if on else 0

    def is_held(self, vk):
        return bool(self.held[vk]) if vk < len(self.held) else False

    def wait(self, seconds):
        """Sleep until a key arrives or the time is up."""
        if not self.early:
            try:
                self.early.append(self.events.get(timeout=seconds))
            except queue.Empty:
                pass

    def pressed(self):
        hwnd = self.hwnd_getter() or 0
        self.hwnd.value = hwnd
        got, self.early = self.early, []
        while True:
            try:
                got.append(self.events.get_nowait())
            except queue.Empty:
                break
        new = []
        for vk, front, repeat in got:
            if hwnd and front == hwnd and not (repeat and vk in new):
                new.append(vk)
        return new


def watcher(hwnd_getter):
    """The hook in its own process if possible, else in ours, else polling."""
    try:
        separate = ProcessKeyWatcher(hwnd_getter)
        if separate.ok:
            return separate
    except Exception as e:
        print("key hook process failed:", e)
    hooked = HookKeyWatcher(hwnd_getter)
    return hooked if hooked.ok else KeyWatcher(hwnd_getter)
