"""Passive probe: list the open-window stack and, for the top window, every
pointer in its first 0x800 bytes that leads to a widget with text.

    python tools/probe_windows.py [window_number]
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process
from mbaccess.mem import Reader, ReadError

game = process.try_attach()
r = Reader(game)
s = game.profile.screen

block_map, map_size, first, count = struct.unpack("<IIII", r.read(s["open_windows"], 16))
stack = []
for i in range(first, first + count):
    block = r.ptr(block_map + 4 * ((i // 4) % map_size))
    stack.append(r.i32(block + 4 * (i % 4)))
print("open windows (bottom..top):", stack)

number = int(sys.argv[1]) if len(sys.argv) > 1 else stack[-1]
window = r.ptr(s["game_windows"] + 4 * number)
print(f"window {number} at {window:#x}, vtable {r.ptr(window):#x}")


def widget_text(w):
    try:
        t = r.rgl_string(w + s["widget_text"])
    except ReadError:
        return None
    if not t or len(t) > 200 or not t.isprintable():
        return None
    return t


for off in range(0, 0x800, 4):
    try:
        p = r.ptr(window + off)
        if p < 0x10000:
            continue
        t = widget_text(p)
    except ReadError:
        continue
    if t is not None:
        x, y = struct.unpack("<ff", r.read(p + s["widget_position"], 8))
        flags = r.u32(p + s["widget_flags"])
        print(f"+{off:#05x} -> {p:#x} flags {flags:#x} pos ({x:.3f}, {y:.3f}) {t!r}")
