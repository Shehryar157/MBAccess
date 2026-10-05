"""Clicking a spot in the game window, given in the engine's own coordinates.

The engine lays out its interface on a virtual screen 1.0 wide and 0.75
tall, with y measured UP from the bottom, whatever the real resolution. We
turn that into pixels of the window's client area (the inside, without the
title bar), then into desktop pixels, move the mouse there and click.
"""
import ctypes
import time
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32")
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, MOUSEEVENTF_WHEEL = 0x0002, 0x0004, 0x0800
WHEEL_DELTA = 120  # one notch
SCREEN_HEIGHT = 0.75


def to_pixels(width, height, x, y):
    """Engine coordinates -> client pixels (pure maths, tested)."""
    return round(x * width), round(height - y / SCREEN_HEIGHT * height)


def move(hwnd, x, y):
    rect = wintypes.RECT()
    _user32.GetClientRect(hwnd, ctypes.byref(rect))
    px, py = to_pixels(rect.right, rect.bottom, x, y)
    point = wintypes.POINT(px, py)
    _user32.ClientToScreen(hwnd, ctypes.byref(point))
    _user32.SetCursorPos(point.x, point.y)


def click(hwnd, x, y, hold=0.08):
    """Script-built screens (Custom Battle) miss quick clicks, so by default
    we hover a moment and hold the button like a person would. Game menus
    act as soon as the button goes down and show the next menu at once, so
    a held click would also press whatever appears under the mouse: they
    use a short hold."""
    move(hwnd, x, y)
    time.sleep(0.1 if hold else 0.03)
    _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(hold or 0.03)
    _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def drag(hwnd, from_x, to_x, y, steps=8, to_y=None):
    """Hold the button on a slider's handle and slide it sideways.

    The game ignores clicks on a slider's track; it only follows the handle
    while the button is held, so we move there in small steps.
    """
    move(hwnd, from_x, y)
    time.sleep(0.03)
    _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    for i in range(1, steps + 1):
        time.sleep(0.02)
        move(hwnd, from_x + (to_x - from_x) * i / steps, y + (to_y - y) * i / steps)
    time.sleep(0.03)
    _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def wheel(hwnd, x, y, notches):
    """Turn the mouse wheel over (x, y): positive scrolls up, negative down."""
    move(hwnd, x, y)
    time.sleep(0.03)
    # mouse_event wants the amount as an unsigned 32-bit number, so a
    # negative one is wrapped around (two's complement), like C would.
    _user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, (notches * WHEEL_DELTA) & 0xFFFFFFFF, 0)


class Mouse:
    """The mouse actions, bound to a function that finds the game window."""

    def __init__(self, hwnd_getter):
        self.hwnd_getter = hwnd_getter

    def _do(self, action, *args):
        hwnd = self.hwnd_getter()
        if hwnd:
            action(hwnd, *args)

    def hover(self, x, y):
        self._do(move, x, y)

    def click(self, x, y, hold=0.08):
        self._do(click, x, y, hold)

    def drag(self, from_x, to_x, y, to_y=None):
        self._do(drag, from_x, to_x, y, 8, to_y)

    def wheel(self, x, y, notches):
        self._do(wheel, x, y, notches)