"""Passive probe: find the map's right-click (context) menu rows in the game object.

    python tools/probe_context.py

WarbandLib's game.h has, in a row: context_menu_num_items, context_menu_mouseover_index,
context_menu_items[50] (rgl::strings), context_menu_values[50]. Fifty rgl::strings side
by side is a shape nothing else in the game object has, so we look for that instead of
trusting an offset from another version. Reads only.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process, session
from mbaccess.mem import RGL_STRING_SIZE, RGL_STRING_STATIC, Reader

ROWS = 50
SPAN = 0x30000      # how much of the game object to look through


def find_rows(reader, game):
    """Offset of context_menu_num_items, or None."""
    data = reader.read(game, SPAN)

    def string_at(offset):      # an rgl::string that still uses its own static buffer
        buffer, _capacity, length = struct.unpack_from("<III", data, offset + 4)
        return buffer == game + offset + RGL_STRING_STATIC and length < 128

    for offset in range(8, SPAN - ROWS * (RGL_STRING_SIZE + 4), 4):
        if all(string_at(offset + n * RGL_STRING_SIZE) for n in range(ROWS)) \
                and not string_at(offset - RGL_STRING_SIZE):
            return offset - 8
    return None


def main():
    game = process.try_attach()
    found, _ = session.locate(game)
    reader = Reader(game)
    at = find_rows(reader, found)
    if at is None:
        print("no run of 50 strings found")
        return
    count, over = struct.unpack("<ii", reader.read(found + at, 8))
    print(f"context menu at game+{at:#x}: {count} rows, mouse over row {over}")
    values = struct.unpack(f"<{ROWS}i", reader.read(found + at + 8 + ROWS * RGL_STRING_SIZE, 4 * ROWS))
    for n in range(ROWS):
        text = reader.rgl_string(found + at + 8 + n * RGL_STRING_SIZE)
        if text or n < count:
            print(f"  row {n}: {text!r} = {values[n]}")


if __name__ == "__main__":
    main()
