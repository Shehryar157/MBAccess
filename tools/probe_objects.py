"""Passive probe: find the mission's stable_vectors (agents, mission objects...) by shape.

A stable_vector is (num_items, num_ids, ids vector, items vector), where each vector has an
extra leading word in this build: (0, begin, end, capacity). items = list of chunk pointers.

    python tools/probe_objects.py
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process, walls
from mbaccess.mem import Reader, ReadError

game = process.try_attach()
r = Reader(game)
mission = walls.mission_address(r, game.profile)
SPAN = 0x30000
blob = r.read(mission, SPAN)
words = struct.unpack("<%dI" % (SPAN // 4), blob)
for i in range(len(words) - 11):
    n, ids, z1, ib, ie, ic, z2, cb, ce, cc = words[i:i + 10]
    if not (0 < n <= ids <= 20000 and ib and ie > ib and cb and ce > cb):
        continue
    if (ce - cb) // 4 != (ids + 15) // 16:
        continue
    chunk = r.u32(cb)
    head = r.read(chunk, 0x40)
    vt = struct.unpack_from("<I", head)[0]
    # stride: next place the vtable repeats
    stride = None
    try:
        big = r.read(chunk, 0x10000)
        for s in range(0x40, 0x10000, 4):
            if struct.unpack_from("<I", big, s)[0] == vt and struct.unpack_from("<i", big, s + 8)[0] == 1:
                stride = s
                break
    except ReadError:
        pass
    print("mission+%#x: items %d ids %d chunks %d vtable %#x stride %s first words %s" % (
        i * 4, n, ids, (ce - cb) // 4, vt, hex(stride) if stride else "?",
        " ".join("%x" % w for w in struct.unpack_from("<8I", head))))
