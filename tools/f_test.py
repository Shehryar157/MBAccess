"""Press the Action key (F) once in a scene and report whether the player dismounts.
Checks first: scene window on top, horse standing still. Takes the game to the front.

    python tools/f_test.py
"""
import ctypes
import math
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process, walls
from mbaccess.mem import Reader

u = ctypes.WinDLL("user32")
game = process.try_attach()
r = Reader(game)
gw = game.profile.screen["game_windows"]


def top():
    d = game.profile.screen.get("open_windows")
    return d


def player():
    return walls.find_player(r, walls.mission_address(r, game.profile))


w10 = r.ptr(gw + 4 * 10)
p1 = player(); time.sleep(0.5); p2 = player()
moving = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / 0.5
print("mounted" if p2[4] else "on foot", "speed %.2f m/s" % moving)
if moving > 0.05:
    sys.exit("horse still moving: not pressing")
hwnd = process.find_window(game.pid)
u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)     # Alt tap: lets us take focus
u.SetForegroundWindow(hwnd)
time.sleep(0.4)
print("game in front:", u.GetForegroundWindow() == hwnd)
u.keybd_event(0x46, 0x21, 0, 0)          # F down (key code and scan code)
time.sleep(0.08)
u.keybd_event(0x46, 0x21, 2, 0)          # F up
for _ in range(30):
    time.sleep(0.1)
    p = player()
    use = struct.unpack("<2i", r.read(w10 + 0x408, 8))
    if p and p[4] != p2[4]:
        print("CHANGED: now", "mounted" if p[4] else "on foot")
        break
else:
    print("no change after 3 s; still", "mounted" if p[4] else "on foot", "use fields", use)
