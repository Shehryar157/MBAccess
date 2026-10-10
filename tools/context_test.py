"""Live test of the map's right-click menu (DRIVES THE MOUSE: ask the user first).

    python tools/context_test.py              print where the nearest places are drawn (reads only)
    python tools/context_test.py Buvran       right-click that place, print what memory shows,
                                              then slide the mouse down its rows; chooses nothing

The map must be on top. What it prints is what docs/findings/map.md needs: the menu's
rows, which map window fields change, and where each row sits under the mouse.
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, r"E:\code\mods\CFCAccess\tools")
from mbaccess import click, process, session
from mbaccess.mem import RGL_STRING_SIZE, Reader
from mbaccess.world_map import WorldMap
from probe_context import ROWS, find_rows

MAP_WINDOW = 6
CAMERA = 0x374          # rgl::camera's matrix in the map window (1.174)
FIELDS = (0x3d4, 0x60)  # from camera_origin on: the fields that might hold the menu's party


def project(reader, window, point):
    """Map position -> engine screen coordinates (x 0-1, y 0-0.75 from the bottom), and
    the distance in front of the camera. The matrix rows are right, up and backward."""
    m = struct.unpack("<16f", reader.read(window + CAMERA, 64))
    left, right, up, down, near = struct.unpack("<5f", reader.read(window + CAMERA + 64, 20))
    v = [point[n] - m[12 + n] for n in range(3)]
    side, rise, back = (sum(v[n] * m[row * 4 + n] for n in range(3)) for row in range(3))
    depth = -back
    if depth <= near:
        return None
    x = 0.5 + side * near / depth / (right - left)
    y = click.SCREEN_HEIGHT * (0.5 + rise * near / depth / (up - down))
    return x, y, depth


def menu(reader, game, at):
    count, over = struct.unpack("<ii", reader.read(game + at, 8))
    rows = []
    if 0 < count <= ROWS:
        values = struct.unpack(f"<{count}i", reader.read(game + at + 8 + ROWS * RGL_STRING_SIZE, 4 * count))
        rows = [(reader.rgl_string(game + at + 8 + n * RGL_STRING_SIZE), values[n]) for n in range(count)]
    return count, over, rows


def main():
    game = process.try_attach()
    found, _ = session.locate(game)
    reader = Reader(game)
    o = game.profile.screen["map"]
    atlas = WorldMap(reader, o)
    atlas.refresh(found)
    window = reader.u32(game.profile.screen["game_windows"] + 4 * MAP_WINDOW)
    at = find_rows(reader, found)

    def drawn(spot):
        reader.cached and None
        return project(reader, window, struct.unpack("<3f", reader.read(spot.address + o["position"], 12)))

    if len(sys.argv) < 2:
        for spot in atlas.spots[:12]:
            where = drawn(spot)
            print(spot.number, spot.name, "behind the camera" if where is None
                  else "x %.3f y %.3f depth %.1f" % where)
        return

    spot = next(s for s in atlas.spots if s.name.lower().startswith(sys.argv[1].lower()))
    x, y, _depth = drawn(spot)
    print(f"{spot.name} (party {spot.number}) drawn at x {x:.3f} y {y:.3f}")
    print("menu before:", menu(reader, found, at))
    before = reader.read(window + FIELDS[0], FIELDS[1])
    hwnd = process.find_window(game.pid)
    click.use_config(game.profile.config_file)
    import win
    win.focus(hwnd)
    time.sleep(0.4)
    click.move(hwnd, x, y)
    time.sleep(0.3)
    click.click(hwnd, x, y, right=True)
    time.sleep(0.5)
    reader = Reader(game)       # a fresh reader: nothing cached from before the click
    print("menu after:", menu(reader, found, at))
    after = reader.read(window + FIELDS[0], FIELDS[1])
    for n in range(0, FIELDS[1], 4):
        if before[n:n + 4] != after[n:n + 4]:
            print(f"  window+{FIELDS[0] + n:#x}: {struct.unpack_from('<i', before, n)[0]} -> "
                  f"{struct.unpack_from('<i', after, n)[0]} (float {struct.unpack_from('<f', after, n)[0]:.3f})")
    last = None
    for step in range(0, 60):   # slide down and to the right a little: which row is under the mouse?
        dy = step * 0.004
        click.move(hwnd, x + 0.02, y - dy)
        time.sleep(0.06)
        count, over, _rows = menu(Reader(game), found, at)
        if (count, over) != last:
            print(f"  {dy:.3f} below the click: {count} rows, mouse over row {over}")
            last = count, over
    click.move(hwnd, 0.99, 0.74)    # park the mouse in a corner
    time.sleep(0.5)
    print("menu after moving away:", menu(Reader(game), found, at)[:2])


if __name__ == "__main__":
    main()
