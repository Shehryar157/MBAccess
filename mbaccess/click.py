"""Clicking a spot in the game window, given in the engine's own coordinates.

The engine lays out its interface on a virtual screen 1.0 wide and 0.75
tall, with y measured UP from the bottom, whatever the real resolution. We
turn that into pixels of the window's client area (the inside, without the
title bar), then into desktop pixels, move the mouse there and click.

Most screens (Load game, Options...) stretch that layout over the whole
window. The MAIN MENU doesn't: with "enable_aspect_ratio_control" on in
rgl_config.txt (the default) it keeps the monitor's shape and is centred,
with black bars above and below (or left and right). Measured 2026-10-06: a
4:3 window 426x320 on a 16:9 monitor shows the main menu in a 426x240 strip
between two 40-pixel bars, while Load game's Cancel lights up down to row 306.
Screens like the main menu say "letterbox": true in the profile; we work out
the picture's rectangle on every move, so a change of resolution, window
size or setting is picked up straight away.
"""
import ctypes
import os
import time
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32")
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, MOUSEEVENTF_WHEEL = 0x0002, 0x0004, 0x0800
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
KEYEVENTF_SCANCODE, KEYEVENTF_KEYUP = 0x0008, 0x0002
CTRL_SCAN = 0x1D   # the game reads keys through DirectInput, which sees scan codes
WHEEL_DELTA = 120  # one notch
SCREEN_HEIGHT = 0.75


def picture(width, height, aspect=None):
    """Where the picture sits in a width x height client area: (left, top,
    picture width, picture height). aspect = the shape it keeps (width /
    height), None = it stretches to fill the window. Pure maths, tested."""
    if not aspect or not width or not height:
        return 0, 0, width, height
    if width / height > aspect:             # window too wide: bars left and right
        w = height * aspect
        return (width - w) / 2, 0, w, height
    h = width / aspect                      # window too tall: bars above and below
    return 0, (height - h) / 2, width, h


def to_pixels(width, height, x, y, aspect=None):
    """Engine coordinates -> client pixels (pure maths, tested)."""
    left, top, w, h = picture(width, height, aspect)
    return round(left + x * w), round(top + h - y / SCREEN_HEIGHT * h)


class AspectSetting:
    """Reads enable_aspect_ratio_control from rgl_config.txt, again only when
    the file changes (the Video options screen rewrites it)."""

    def __init__(self, path=None):
        self.path = path
        self.stamp = None
        self.on = True       # the game's default

    def keep(self):
        try:
            stamp = os.stat(self.path).st_mtime if self.path else None
        except OSError:
            stamp = None
        if stamp != self.stamp:
            self.stamp = stamp
            self.on = True
            if stamp is not None:
                with open(self.path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        name, _, value = line.partition("=")
                        if name.strip() == "enable_aspect_ratio_control":
                            self.on = value.strip() != "0"
        return self.on


def monitor_aspect(hwnd):
    """Width / height of the monitor the window is on."""
    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    monitor = _user32.MonitorFromWindow(hwnd, 2)    # 2 = the nearest monitor
    if not monitor or not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    r = info.rcMonitor
    return (r.right - r.left) / (r.bottom - r.top) if r.bottom > r.top else None


_aspect_setting = AspectSetting()


def use_config(path):
    """Tell the clicks which rgl_config.txt to read (the attached game's)."""
    global _aspect_setting
    _aspect_setting = AspectSetting(path)


def move(hwnd, x, y, letterbox=False):
    rect = wintypes.RECT()
    _user32.GetClientRect(hwnd, ctypes.byref(rect))
    aspect = monitor_aspect(hwnd) if letterbox and _aspect_setting.keep() else None
    px, py = to_pixels(rect.right, rect.bottom, x, y, aspect)
    point = wintypes.POINT(px, py)
    _user32.ClientToScreen(hwnd, ctypes.byref(point))
    _user32.SetCursorPos(point.x, point.y)


def click(hwnd, x, y, hold=0.08, right=False, ctrl=False, letterbox=False):
    """Script-built screens (Custom Battle) miss quick clicks, so by default
    we hover a moment and hold the button like a person would. Game menus
    act as soon as the button goes down and show the next menu at once, so
    a held click would also press whatever appears under the mouse: they
    use a short hold. ctrl: hold Ctrl through the click (quick buy/sell),
    pressed by us, as the player may already have let go of it."""
    down, up = ((MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if right
                else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
    move(hwnd, x, y, letterbox)
    if ctrl:
        _user32.keybd_event(0, CTRL_SCAN, KEYEVENTF_SCANCODE, 0)
    try:
        time.sleep(0.1 if hold else 0.03)
        _user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(hold or 0.03)
        _user32.mouse_event(up, 0, 0, 0, 0)
    finally:
        if ctrl:    # always let go of Ctrl, even if the click failed
            time.sleep(0.03)
            _user32.keybd_event(0, CTRL_SCAN, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)


def drag(hwnd, from_x, to_x, y, steps=None, letterbox=False):
    """Hold the button on a slider's handle and slide it sideways.

    The game ignores clicks on a slider's track; it only follows the handle
    while the button is held, so we move there in small steps: about one
    per 1% of the screen (a 5% nudge on a slider = 2 steps), at most 8.
    """
    if steps is None:
        steps = max(2, min(8, round(abs(to_x - from_x) / 0.01)))
    move(hwnd, from_x, y, letterbox)
    time.sleep(0.03)
    _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    for i in range(1, steps + 1):
        time.sleep(0.02)
        move(hwnd, from_x + (to_x - from_x) * i / steps, y, letterbox)
    time.sleep(0.03)
    _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def wheel(hwnd, x, y, notches, letterbox=False):
    """Turn the mouse wheel over (x, y): positive scrolls up, negative down."""
    move(hwnd, x, y, letterbox)
    time.sleep(0.03)
    # mouse_event wants the amount as an unsigned 32-bit number, so a
    # negative one is wrapped around (two's complement), like C would.
    _user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, (notches * WHEEL_DELTA) & 0xFFFFFFFF, 0)


class Mouse:
    """The mouse actions, bound to a function that finds the game window."""

    def __init__(self, hwnd_getter):
        self.hwnd_getter = hwnd_getter
        self.letterbox = False      # set per screen by the menu watcher

    def _do(self, action, *args):
        hwnd = self.hwnd_getter()
        if hwnd:
            action(hwnd, *args, letterbox=self.letterbox)

    def hover(self, x, y):
        self._do(move, x, y)

    def click(self, x, y, hold=0.08, right=False, ctrl=False):
        self._do(click, x, y, hold, right, ctrl)

    def drag(self, from_x, to_x, y):
        self._do(drag, from_x, to_x, y)

    def wheel(self, x, y, notches):
        self._do(wheel, x, y, notches)