"""Passive probe: print the map list the mod would offer, nearest first.

    python tools/probe_map.py [how_many]

Reads only (no travel order), so it's safe anywhere in a campaign.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process, session
from mbaccess.mem import Reader
from mbaccess.world_map import WorldMap

game = process.try_attach()
found, _ = session.locate(game)
atlas = WorldMap(Reader(game), game.profile.screen["map"])
start = time.perf_counter()
items = atlas.items(found)
print(f"{len(items)} items in {1000 * (time.perf_counter() - start):.0f} ms; "
      f"player at {atlas.here[0]:.1f}, {atlas.here[1]:.1f}")
for item in items[:int(sys.argv[1]) if len(sys.argv) > 1 else 20]:
    print(" ", item.label)
