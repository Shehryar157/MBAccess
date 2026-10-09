"""Does the game take keys the mod sends? Tap W (does the horse move?), wait for it to
stop, then hold F (does the player dismount?). Takes the game to the front.

    python tools/key_test.py
"""
import ctypes
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process, walls
from mbaccess.mem import Reader

u = ctypes.WinDLL("user32")
game = process.try_attach()
r = Reader(game)
player = lambda: walls.find_player(r, walls.mission_address(r, game.profile))


def press(vk, scan, hold):
    u.keybd_event(vk, scan, 0, 0)
    time.sleep(hold)
    u.keybd_event(vk, scan, 2, 0)


def wait_still(limit=20):
    last, t = player(), time.time()
    while time.time() - t < limit:
        time.sleep(0.5)
        p = player()
        if math.hypot(p[0] - last[0], p[1] - last[1]) < 0.02:
            return p
        last = p
    return last


hwnd = process.find_window(game.pid)
u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
u.SetForegroundWindow(hwnd)
time.sleep(0.5)
print("game in front:", u.GetForegroundWindow() == hwnd)
p0 = player()
press(0x57, 0x11, 0.25)                      # W
time.sleep(1.0)
p1 = player()
print("W: moved %.2f m" % math.hypot(p1[0] - p0[0], p1[1] - p0[1]))
p = wait_still()
print("still again; mounted:", p[4])
press(0x46, 0x21, 0.35)                      # F, held
for _ in range(30):
    time.sleep(0.1)
    q = player()
    if q[4] != p[4]:
        print("F: CHANGED, now", "mounted" if q[4] else "on foot")
        break
else:
    print("F: no change, still", "mounted" if q[4] else "on foot")
