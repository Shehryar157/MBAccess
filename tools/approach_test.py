"""Ride or walk up to the nearest person, logging the game's use-object fields (the
"Talk"/"Mount" prompt), then press F once if something is in range. Takes the game to
the front for up to ~40 s.

    python tools/approach_test.py [troop name, default Villager]
"""
import ctypes
import math
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process, scanner, session, walls
from mbaccess.mem import Reader
from mbaccess.menu_watch import MenuWatcher

u = ctypes.WinDLL("user32")
game = process.try_attach()
r = Reader(game)
scan = scanner.Scanner(r, game.profile, lambda s: None)
w10 = r.ptr(game.profile.screen["game_windows"] + 4 * 10)
addr, module = session.locate(game)
mw = MenuWatcher(Reader(game), None, game.profile.game_offsets, [], lambda s: None, screen=game.profile.screen)
mw.set_game(addr, session.load_menus(game, module))
want = sys.argv[1] if len(sys.argv) > 1 else "Villager"
KEYS = {"W": (0x57, 0x11), "A": (0x41, 0x1E), "D": (0x44, 0x20), "S": (0x53, 0x1F), "F": (0x46, 0x21)}
down = set()


def key(name, on):
    vk, sc = KEYS[name]
    if on and name not in down:
        u.keybd_event(vk, sc, 0, 0); down.add(name)
    elif not on and name in down:
        u.keybd_event(vk, sc, 2, 0); down.discard(name)


def use():
    return struct.unpack("<6i", r.read(w10 + 0x408, 24))


hwnd = process.find_window(game.pid)
u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
u.SetForegroundWindow(hwnd)
time.sleep(0.5)
last, t0 = None, time.time()
try:
    while time.time() - t0 < 25:
        if mw.top_window() != 10 or u.GetForegroundWindow() != hwnd:
            print("left the scene or lost focus: stopping"); break
        p, found = scan.things()
        people = [t for t in found if t["name"] == want]
        if not people:
            print("no", want); break
        t = min(people, key=lambda t: math.hypot(t["x"] - p[0], t["y"] - p[1]))
        d, a = scanner.relative(p, t["x"], t["y"])
        u_ = use()
        if int((time.time() - t0) * 2) != int((time.time() - t0 - 0.06) * 2):
            print("   %.1f s  %.1f m  %.0f deg  speed-ish" % (time.time() - t0, d, a))
        if u_ != last:
            print("%5.1f s  use %s  target %s %d at %.1f m, %.0f deg" % (time.time() - t0, u_, t["name"], t["key"][1], d, a))
            last = u_
        if u_[0] != -1 and u_[3]:
            break
        key("A", a > 12); key("D", a < -12)
        key("W", d > 2.0)
        if d <= 2.0:
            key("W", False); key("S", True); time.sleep(0.15); key("S", False)
        time.sleep(0.05)
finally:
    for k in list(down):
        key(k, False)
time.sleep(0.5)
print("final use fields", use(), "top window", mw.top_window())
if use()[0] != -1:
    key("F", True); time.sleep(0.15); key("F", False)
    time.sleep(1.5)
    print("after F: top window", mw.top_window(), "use", use())
