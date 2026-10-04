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
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
SCREEN_HEIGHT = 0.75


def to_pixels(width, height, x, y):
    """Engine coordinates -> client pixels (pure maths, tested)."""
    return round(x * width), round(height - y / SCREEN_HEIGHT * height)


def click(hwnd, x, y):
    rect = wintypes.RECT()
    _user32.GetClientRect(hwnd, ctypes.byref(rect))
    px, py = to_pixels(rect.right, rect.bottom, x, y)
    point = wintypes.POINT(px, py)
    _user32.ClientToScreen(hwnd, ctypes.byref(point))
    _user32.SetCursorPos(point.x, point.y)
    time.sleep(0.03)  # let the game see the mouse arrive (hover) first
    _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.03)
    _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
