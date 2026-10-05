"""Passive probe: print a window's widget tree with each widget's kind.

    python tools/probe_tree.py window_number

Kinds come from the profile's class table; unknown classes print their
vtable address. Sliders also print the floats at +0x2b8..+0x2c4.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process
from mbaccess.mem import Reader, ReadError
from mbaccess.menu_watch import MenuWatcher

game = process.try_attach()
r = Reader(game)
w = MenuWatcher(r, None, game.profile.game_offsets, [], print, screen=game.profile.screen)
t = w.tree
number = int(sys.argv[1])
root = w.root(number)
print(f"window {number}, root at +{w.root_offsets.get(number, 0x13c):#x}")


def walk(p, depth=0, seen=set()):
    if p in seen or depth > 14:
        return
    seen.add(p)
    pad = "  " * depth
    try:
        x, y = t.position(p)
        kind = t.kind(p) or hex(r.ptr(p))
        name, kids = t.children(p)
        flags = r.u32(p + t.s["widget_flags"])
    except ReadError as e:
        print(pad + "unreadable", e)
        return
    try:
        words = t.text(p)[:50]
    except ReadError:
        words = None
    extra = ""
    if kind == "slider":
        extra = " floats " + str([round(v, 3) for v in struct.unpack("<4f", r.read(p + 0x2b8, 16))])
    print(f"{pad}{kind} ({x:.3f},{y:.3f}) f{flags:x}{' [' + name + ']' if name else ''} {words!r}{extra}")
    for k in kids:
        if k > 0x10000:
            walk(k, depth + 1)


walk(root)
