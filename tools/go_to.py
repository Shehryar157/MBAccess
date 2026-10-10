"""Send the party to a place on the map and wait until it gets there (DRIVES THE GAME).

    python tools/go_to.py Buvran [seconds]

Gives the mod's own travel order (world_map.travel), brings the game to the front so
time runs, and stops when a screen other than the map comes on top or the time is up.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, r"E:\code\mods\CFCAccess\tools")
import win
from mbaccess import process, session
from mbaccess.form import Item
from mbaccess.mem import Reader
from mbaccess.menu_watch import MenuWatcher
from mbaccess.world_map import MAP_WINDOW, WorldMap

game = process.try_attach()
found, _ = session.locate(game)
atlas = WorldMap(Reader(game), game.profile.screen["map"], print)
atlas.refresh(found)
spot = next(s for s in atlas.spots if s.name.lower() == sys.argv[1].lower())
watcher = MenuWatcher(Reader(game), None, game.profile.game_offsets, [], lambda *a, **k: None,
                      screen=game.profile.screen)
win.focus(process.find_window(game.pid))
atlas.travel(found, Item("place", spot.name, 0.0, 0.0, widget=spot.address, virtual="map"))
until = time.time() + (float(sys.argv[2]) if len(sys.argv) > 2 else 90)
while time.time() < until:
    time.sleep(0.5)
    top = watcher.top_window()
    if top != MAP_WINDOW:
        print("a screen came up: window", top)
        break
    atlas.refresh(found)
    atlas.check_arrival(found)
    if atlas.target is None:
        break
atlas.refresh(found)
print("party at %.1f, %.1f; %s at %.1f, %.1f" % (*atlas.here, spot.name, spot.x, spot.y))
