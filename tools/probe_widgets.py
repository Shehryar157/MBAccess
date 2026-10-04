"""Passive probe: every pointer in a window's first 0x800 bytes that leads to
an object with a vtable (a C++ object), with its class, position and text.

    python tools/probe_widgets.py [window_number]

A vtable is the table of a C++ class's methods; every object of a class
points at the same one, so the vtable address works like type(obj) in Python.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process
from mbaccess.mem import Reader, ReadError

VTABLES = (0x7be000, 0x85e000)   # the exe's .rdata section

game = process.try_attach()
r = Reader(game)
s = game.profile.screen
number = int(sys.argv[1])
window = r.ptr(s["game_windows"] + 4 * number)
print(f"window {number} at {window:#x}")

for off in range(0, 0x800, 4):
    try:
        p = r.ptr(window + off)
        if p < 0x10000 or not VTABLES[0] <= r.ptr(p) < VTABLES[1]:
            continue
        vt = r.ptr(p)
        x, y = struct.unpack("<ff", r.read(p + s["widget_position"], 8))
        flags = r.u32(p + s["widget_flags"])
        try:
            t = r.rgl_string(p + s["widget_text"])[:50]
        except ReadError:
            t = None
    except ReadError:
        continue
    print(f"+{off:#05x} -> {p:#x} vt {vt:#x} flags {flags:#x} pos ({x:.3f}, {y:.3f}) {t!r}")
