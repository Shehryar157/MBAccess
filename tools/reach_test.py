"""Measure the game's use reach: face a target (default: the nearest horse), back off,
then walk toward it in short steps, logging distance, use_object fields and in_range.
Takes the game's keyboard for ~30 s. On foot only.

    python tools/reach_test.py [People|Animals] [name start, e.g. "Lady Anais"]
"""
import ctypes
import math
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process, scanner, turning, walls
from mbaccess.mem import Reader

u = ctypes.WinDLL("user32")
game = process.try_attach()
r = Reader(game)
scan = scanner.Scanner(r, game.profile, lambda s: None)
turner = turning.Turner(game, lambda s: None)
w10 = r.ptr(game.profile.screen["game_windows"] + 4 * 10)
want = sys.argv[1] if len(sys.argv) > 1 else "Animals"
named = sys.argv[2].lower() if len(sys.argv) > 2 else ""


def use():
    k, n, _, inr = struct.unpack("<4i", r.read(w10 + 0x408, 16))
    return k, n, inr


def target():
    p, found = scan.things()
    ts = [t for t in found if t["category"] == want and t["name"].lower().startswith(named)]
    t = min(ts, key=lambda t: math.hypot(t["x"] - p[0], t["y"] - p[1]))
    d, a = scanner.relative(p, t["x"], t["y"])
    return p, t, d, a


def key(scan_code, hold):
    u.keybd_event(0, scan_code, 8, 0)
    time.sleep(hold)
    u.keybd_event(0, scan_code, 8 | 2, 0)


def face():
    p, t, d, a = target()
    turner._mouse(math.degrees(p[3]) + a)
    return target()


hwnd = process.find_window(game.pid)
u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
u.SetForegroundWindow(hwnd)
time.sleep(0.5)
p, t, d, a = target()
print("target", t["name"], t["key"], "%.1f m" % d, "on horse" if p[4] else "on foot")
if p[4]:
    sys.exit("on horseback: stopping")
face()
for _ in range(60):                         # far away: stride up to ~5 m first
    p, t, d, a = target()
    if d <= 5.5:
        break
    face()
    key(0x11, 0.5)                          # W
    time.sleep(0.2)
    if target()[2] > d - 0.3:
        sys.exit("blocked on the way: %.1f m from %s" % (d, t["name"]))
face()
for _ in range(20):                         # back off to ~5 m
    p, t, d, a = target()
    if d >= 5:
        break
    key(0x1F, 0.25)                         # S
    time.sleep(0.15)
face()
rows = []
for _ in range(160):
    p, t, d, a = target()
    k, n, inr = use()
    rows.append((d, a, k, n, inr))
    print("%.2f m  %+.0f deg  type %d no %d in_range %d" % (d, a, k, n, inr))
    if d < 0.9:
        break
    if abs(a) > 8:
        face()
    key(0x11, 0.08)                         # W, a short step
    time.sleep(0.25)
on = [x for x in rows if x[4]]
print("REACH: in range from %.2f m" % max(x[0] for x in on) if on else "never in range")
seen = [x for x in rows if x[3] == t["key"][1]]
print("looked-at from %.2f m" % max(x[0] for x in seen) if seen else "never looked-at")
