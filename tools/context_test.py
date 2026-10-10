"""Live test of the map's right-click menu (DRIVES THE MOUSE: ask the user first).

    python tools/context_test.py                       where the nearest places are drawn (reads only)
    python tools/context_test.py "Ibdeles Castle"      open its menu, point at each row, close it
    python tools/context_test.py "Ibdeles Castle" 1    open its menu and click row 1 (the second)

The map must be on top. It uses the mod's own code (world_map.WorldMap), so what works
here works on Shift+Enter in the map list.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, r"E:\code\mods\CFCAccess\tools")
from mbaccess import click, process, session
from mbaccess.form import Item
from mbaccess.mem import Reader
from mbaccess.world_map import MAP_WINDOW, WorldMap


def main():
    game = process.try_attach()
    found, _ = session.locate(game)
    reader = Reader(game)
    o = game.profile.screen["map"]
    atlas = WorldMap(reader, o)
    atlas.refresh(found)
    window = reader.u32(game.profile.screen["game_windows"] + 4 * MAP_WINDOW)
    if len(sys.argv) < 2:
        for spot in atlas.spots[:12]:
            where = atlas.project(window, atlas.live(spot.address + o["position"], "<3f"))
            print(spot.number, spot.name, "behind the camera" if where is None else "x %.3f y %.3f" % where)
        return

    spot = next(s for s in atlas.spots if s.name.lower() == sys.argv[1].lower())
    hwnd = process.find_window(game.pid)
    click.use_config(game.profile.config_file)
    mouse = click.Mouse(lambda: hwnd)
    import win
    win.focus(hwnd)
    time.sleep(0.4)
    start = time.perf_counter()
    rows = atlas.open_menu(found, window, mouse, Item("place", spot.name, 0.0, 0.0, widget=spot.address, virtual="map"))
    print(f"{spot.name} (party {spot.number}): rows {rows} in {time.perf_counter() - start:.2f} s, "
          f"clicked at {atlas.menu_at}")
    if not rows:
        return
    if len(sys.argv) > 2:
        row = int(sys.argv[2])
        print(f"clicking row {row}:", atlas.choose_row(found, window, mouse, row))
        return
    for row in range(len(rows)):
        print(f"  row {row} {rows[row][0]!r}: mouse lands at height {atlas.point_at_row(found, mouse, row)}")
    atlas.close_menu(window, mouse)
    print("closed:", atlas.menu_party(window) is None)


if __name__ == "__main__":
    main()
