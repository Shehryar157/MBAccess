"""Passive probe: a troop's item slots, and where the inventory window keeps
the table linking each cell widget to its slot.

    python tools/probe_inventory.py [troop_no]      (default 0, the player)

Troop slots: 96 x (item_no, flags) at troop+0x2d0 (WarbandLib 1.153 layout,
which still holds in 1.174 for flags and skills). With the inventory open,
every cell widget is looked for in the window object; the offsets found are
the inventory_slot_widgets / equipment_slot_widgets tables.
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
s = game.profile.screen
w = MenuWatcher(r, None, game.profile.game_offsets, [], print, screen=s)
o = s["party_skills"]
cur = r.ptr(0x8b82a0)
troops = r.ptr(cur + o["troops"])
table, kinds = r.ptr(s["item_kinds"]), r.i32(s["item_kinds"] + 4)


def name(kind):
    return r.rgl_string(table + kind * s["item_kind_size"]) if 0 < kind < kinds else "?"


no = int(sys.argv[1]) if len(sys.argv) > 1 else 0
troop = troops + no * o["troop_size"]
print("troop", no, repr(r.rgl_string(troop + 4)))
slots = struct.unpack("<192i", r.read(troop + 0x2d0, 96 * 8))
for n in range(96):
    item, flags = slots[2 * n], slots[2 * n + 1] & 0xFFFFFFFF
    if item > 0:
        print(f"  slot {n}: {item} {name(item)!r} flags {flags:#x}")

top = w.top_window()
print("top window", top)
if top != 7:
    sys.exit()
window = w.window(7)
cells = []


def walk(p, seen=set()):
    if p in seen or len(seen) > 3000:
        return
    seen.add(p)
    try:
        if w.tree.kind(p) == "slot":
            cells.append((p, w.tree.position(p)))
        for k in w.tree.children(p)[1]:
            if k > 0x10000:
                walk(k)
    except ReadError:
        pass


walk(w.root(7))
print(len(cells), "cells")
blob = r.read(window, 0x4000)
words = struct.unpack(f"<{len(blob) // 4}I", blob)
where = {p: n * 4 for n, p in enumerate(words) if p}
for p, (x, y) in sorted(cells, key=lambda c: where.get(c[0], 1 << 30)):
    print(f"  cell {p:#x} at ({x:.3f},{y:.3f}) found at window+{where.get(p, -1):#x}")
print("held", r.i32(window + 0xbb0), r.i32(window + 0xbb4))
