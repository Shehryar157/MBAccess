"""The game's launcher window: speak its unlabelled buttons.

The launcher is an ordinary Windows dialog, so Tab and Enter already work,
but its buttons are pictures with no text, so NVDA can only say "button".
We ask Windows which control has keyboard focus in the launcher's thread
(GetGUIThreadInfo) and speak our own label for it whenever it changes.

Control IDs found in Warband 1.174 (see docs/findings.md).
"""
import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32")

TITLES = ("Mount&Blade Warband", "Mount&Blade With Fire and Sword")
LABELS = {1029: "Play", 1055: "Configure", 1131: "Cancel", 1056: "Module", 1202: "Delete module"}


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


def find():
    """The launcher dialog's window handle, or None."""
    for title in TITLES:
        hwnd = _user32.FindWindowW("#32770", title)
        if hwnd:
            return hwnd
    return None


class LauncherWatcher:
    """Speaks the launcher's focused control each time focus moves."""

    def __init__(self, say):
        self.say = say
        self.hwnd = None
        self.last_focus = None

    def poll(self):
        hwnd = find()
        if hwnd != self.hwnd:
            self.hwnd, self.last_focus = hwnd, None
            if hwnd:
                self.say("Launcher. Tab between Play, Configure and Cancel; Enter presses.")
        if not hwnd:
            return
        info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
        thread = _user32.GetWindowThreadProcessId(hwnd, None)
        if not _user32.GetGUIThreadInfo(thread, ctypes.byref(info)) or not info.hwndFocus:
            return
        control = info.hwndFocus
        label = LABELS.get(_user32.GetDlgCtrlID(control))
        if label is None:  # the combo box's inner edit field
            label = LABELS.get(_user32.GetDlgCtrlID(_user32.GetParent(control)))
        if (control, label) == self.last_focus:
            return
        self.last_focus = (control, label)
        # The module box is a real combo box that NVDA reads by itself; speaking
        # over it (we interrupt) would cut NVDA's "combo box" announcement off.
        if label and label != "Module":
            self.say(label)
