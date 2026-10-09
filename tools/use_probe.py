"""Passive probe: find what the scene window stores about the thing you're facing
(the "Talk" / "Mount" / "Door to ..." prompt). Watches window 10's whole body and
prints changes to whole-number fields, ignoring ones that tick constantly (timers,
camera). Stand still for the first 3 seconds while it learns which those are.

    python tools/use_probe.py [seconds, default 90]
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process
from mbaccess.mem import Reader

START, SIZE = 0x200, 0x800
game = process.try_attach()
r = Reader(game)
w = r.ptr(game.profile.screen["game_windows"] + 4 * 10)
read = lambda: struct.unpack("<%di" % (SIZE // 4), r.read(w + START, SIZE))
noisy, first = set(), read()
t_end = time.time() + 3
while time.time() < t_end:              # learn the constantly changing fields
    v = read()
    noisy |= {i for i in range(len(v)) if v[i] != first[i]}
    time.sleep(0.05)
print("ignoring %d ticking fields; now look at things" % len(noisy), flush=True)
last, t0 = read(), time.time()
end = t0 + (float(sys.argv[1]) if len(sys.argv) > 1 else 90)
while time.time() < end:
    v = read()
    changes = ["+%x: %d -> %d" % (START + 4 * i, last[i], v[i]) for i in range(len(v))
               if v[i] != last[i] and i not in noisy and -10 <= v[i] <= 100000]
    if changes:
        print("%5.1fs  %s" % (time.time() - t0, "   ".join(changes)), flush=True)
    last = v
    time.sleep(0.05)
