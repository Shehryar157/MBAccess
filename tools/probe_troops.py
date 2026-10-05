"""Print troops' attributes and skills (party-skill research).

    python tools/probe_troops.py [troop_no ...]      (default: 0, the player)

The troops array pointer is at game+0x140f0, the count right after it.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process
from mbaccess.mem import Reader, ReadError

ID_AT = 4 + 3 * 0x90        # renamed, then name, name_plural, image_mesh_name, id
r = Reader(process.try_attach())
cur = r.ptr(0x8b82a0)
troops, count = r.ptr(cur + 0x140f0), r.i32(cur + 0x140f4)
print(f"troops {troops:#x}, {count} of them")
# Stride: the distance to troop 1's id string.
for stride in range(0x300, 0x4000, 4):
    try:
        t = r.rgl_string(troops + stride + ID_AT)
    except ReadError:
        continue
    if t.startswith("trp_"):
        print(f"stride {stride:#x}: troop 1 is {t}")
        break
for no in [int(a) for a in sys.argv[1:]] or [0]:
    p = troops + no * stride
    attrs = struct.unpack("<4i", r.read(p + 0x26c, 16))
    words = struct.unpack("<6I", r.read(p + 0x27c, 24))
    skills = [(words[i // 8] >> 4 * (i % 8)) & 0xF for i in range(42)]
    print(no, r.rgl_string(p + ID_AT), repr(r.rgl_string(p + 4)), "attrs", attrs)
    print("  skills", {i: v for i, v in enumerate(skills) if v})
