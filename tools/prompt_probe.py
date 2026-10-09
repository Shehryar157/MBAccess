"""Passive recorder: what the player is looking at (the game's "Talk" / "Mount" / "Open"
prompt), whether they're mounted, and their speed. Logs only changes.

    python tools/prompt_probe.py [seconds, default 120] > out/prompts.log

Scene window (10) fields, WSE tactical_window order, counted from camera_agent_no +0x3e8:
use_object_type +0x408, use_object_no +0x40c, use_object_in_range +0x414.
"""
import math
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process, scanner, walls
from mbaccess.mem import Reader, ReadError

game = process.try_attach()
r = Reader(game)
scan = scanner.Scanner(r, game.profile, lambda s: None)
window = r.ptr(game.profile.screen["game_windows"] + 4 * 10)


def names(no):
    """What number `no` would be as an agent and as a mission object."""
    out = []
    try:
        _, found = scan.things()
        for t in found:
            if t["key"][1] == no:
                out.append("%s %s (%s)" % (t["key"][0], t["name"], t["category"]))
    except ReadError:
        pass
    return "; ".join(out) or "?"


end = time.time() + (float(sys.argv[1]) if len(sys.argv) > 1 else 120)
last, last_horse, last_pos, speed = None, None, None, 0.0
t0 = time.time()
while time.time() < end:
    try:
        typ, no, _, in_range, _, leave = struct.unpack("<6i", r.read(window + 0x408, 24))
        p = walls.find_player(r, walls.mission_address(r, game.profile))
    except ReadError:
        time.sleep(0.2)
        continue
    now = time.time()
    if p and last_pos:
        v = math.hypot(p[0] - last_pos[0], p[1] - last_pos[1]) / max(now - last_pos[2], 1e-3)
        speed += 0.3 * (v - speed)
    last_pos = (p[0], p[1], now) if p else None
    state = (typ, no, in_range, leave)
    horse = p[4] if p else None
    if state != last or horse != last_horse:
        print("%6.1f s  type %d no %d in_range %d leave %d | %s | speed %.1f m/s | %s" % (
            now - t0, typ, no, in_range, leave, "mounted" if horse else "on foot", speed,
            names(no) if no >= 0 else "-"), flush=True)
        last, last_horse = state, horse
    time.sleep(0.05)
