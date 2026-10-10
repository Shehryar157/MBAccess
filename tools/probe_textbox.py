"""Passive probe: find multi-line text widgets of one class in a window and
dump them (full text, position, size, and the fields after the text).

    python tools/probe_textbox.py window_number [vtable_hex]

Made for the Notes screen (window 21), whose topic list and page text are
widgets of class 0x819984. Fields that look like stl vectors (start <= end
<= cap, close together) are expanded as floats and ints.
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
s = game.profile.screen
number = int(sys.argv[1])
vtable = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x819984


def walk(p, seen=set()):
    if p in seen or p < 0x10000:
        return
    seen.add(p)
    if r.ptr(p) == vtable:
        yield p
    _, kids = t.children(p)
    for k in kids:
        yield from walk(k)


for p in walk(w.root(number)):
    print(f"=== widget {p:#x} pos {t.position(p)} size {struct.unpack('<ff', r.read(p + 0x1ac, 8))}"
          f" flags {r.u32(p + s['widget_flags']):#x}")
    print(repr(r.rgl_string(p + s["widget_text"])))
    for off in range(0x1f0, 0x420, 4):
        a, b, c = struct.unpack("<III", r.read(p + off, 12))
        f = struct.unpack("<f", r.read(p + off, 4))[0]
        note = ""
        if a > 0x10000 and a <= b <= c and b - a <= 4096:
            try:
                raw = r.read(a, min(b - a, 128))
                n = len(raw) // 4
                note = (f" VECTOR {(b - a)} bytes: floats "
                        f"{[round(x, 3) for x in struct.unpack(f'<{n}f', raw)][:16]}"
                        f" ints {list(struct.unpack(f'<{n}i', raw))[:16]}")
            except ReadError:
                pass
        print(f"  +{off:#x}: {a:#010x} {a:11d} {f:10.4f}{note}")
