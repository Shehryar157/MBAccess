"""Passive probe: walk a window's widget tree from its root and print it.

    python tools/probe_tree.py window_number [root_offset_hex]

A container widget has a name (rgl::string at +0x2d0) and an stl::vector of
child widget pointers at +0x364 (start, end, capacity). We treat an object
as a container when both look valid.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process
from mbaccess.mem import Reader, ReadError

VTABLES = (0x7be000, 0x85e000)
game = process.try_attach()
r = Reader(game)
s = game.profile.screen


def children(p):
    try:
        name = r.rgl_string(p + 0x2d0)
        start, end, cap = struct.unpack("<III", r.read(p + 0x364, 12))
    except ReadError:
        return None, []
    if not name.isprintable() or not (start and start <= end <= cap) or (end - start) > 4000:
        return None, []
    kids = struct.unpack(f"<{(end - start) // 4}I", r.read(start, end - start))
    return name, [k for k in kids if is_object(k)]


def is_object(p):
    try:
        return p > 0x10000 and VTABLES[0] <= r.ptr(p) < VTABLES[1]
    except ReadError:
        return False


def text(p):
    try:
        t = r.rgl_string(p + s["widget_text"])
        return t[:60] if t.isprintable() else None
    except ReadError:
        return None


def walk(p, depth=0, seen=None):
    seen = seen if seen is not None else set()
    if p in seen or depth > 12:
        return
    seen.add(p)
    x, y = struct.unpack("<ff", r.read(p + s["widget_position"], 8))
    flags = r.u32(p + s["widget_flags"])
    name, kids = children(p)
    print(f"{'  ' * depth}{p:#x} vt {r.ptr(p):#x} f{flags:#x} ({x:.3f},{y:.3f})"
          f"{' [' + name + ']' if name else ''} {text(p)!r}")
    for k in kids:
        walk(k, depth + 1, seen)


number = int(sys.argv[1])
off = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x13c
window = r.ptr(s["game_windows"] + 4 * number)
walk(r.ptr(window + off))
