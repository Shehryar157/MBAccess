"""Passive probe: print the nearest wall in each zone around the player, plus the
player's position, stored facing and actual direction of movement (to learn the
facing convention).

    python tools/wall_probe.py [seconds]
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process, walls
from mbaccess.mem import Reader

game = process.try_attach()
r = Reader(game)
mission = walls.mission_address(r, game.profile)
t0 = time.perf_counter()
w = walls.SceneWalls(r, r.u32(mission))
print("loaded %d wall panels, %d capsules, %d spheres in %.2f s" % (w.counts() + (time.perf_counter() - t0,)))

end = time.time() + (float(sys.argv[1]) if len(sys.argv) > 1 else 20)
last = None
while time.time() < end:
    p = walls.find_player(r, mission)
    if p is None:
        print("no player")
    else:
        t0 = time.perf_counter()
        z = walls.zone_distances(w, p)
        ms = (time.perf_counter() - t0) * 1000
        moved = ""
        if last and math.hypot(p[0] - last[0], p[1] - last[1]) > 0.3:
            moved = " moving %.0f deg" % math.degrees(math.atan2(p[1] - last[1], p[0] - last[0]))
        print("pos %.1f %.1f %.1f facing %.0f deg%s%s | %s | %.1f ms" % (
            p[0], p[1], p[2], math.degrees(p[3]), " horse" if p[4] else "", moved,
            "  ".join("%s %.1f" % kv for kv in z.items()), ms))
        last = p
    time.sleep(0.5)
