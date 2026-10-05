"""Noticing our hotkeys while the game window is in front.

GetAsyncKeyState(vk) asks Windows "is this key down right now?". We call it
every tick and remember the previous answer, so we react once when a key
goes down (an "edge"), not 20 times a second while it's held.
We only look when the game is the foreground window, so keys typed into
other programs are ignored.
"""
import ctypes

_user32 = ctypes.WinDLL("user32")

UP, DOWN, RETURN, HOME, END = 0x26, 0x28, 0x0D, 0x24, 0x23
LEFT, RIGHT, SPACE = 0x25, 0x27, 0x20
F1, ESCAPE = 0x70, 0x1B
SHIFT, CONTROL = 0x10, 0x11   # either side's key
ALL = (UP, DOWN, RETURN, HOME, END, LEFT, RIGHT, SPACE, F1, ESCAPE)


def is_down(vk):
    """Is this key held right now? For modifiers: Shift+Enter is an Enter
    that went down while is_down(SHIFT) is true."""
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


class KeyWatcher:
    def __init__(self, hwnd_getter, keys=ALL):
        self.hwnd_getter = hwnd_getter  # function returning the game window
        self.keys = keys
        self.down = set()

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
