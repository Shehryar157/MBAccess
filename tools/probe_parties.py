"""Map research: list the parties and find where a party keeps its position.

    python tools/probe_parties.py [dump <party_id>]

Parties: an stl::vector of party pointers at game+0x140b8 (the items of
rgl::hash_vector<party>). Towns never move, so their position in memory must
match the one written in Modules/Native/parties.txt: we look for that pair
of floats in each town to find the offset.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process
from mbaccess.mem import Reader, ReadError

PARTIES_TXT = r"D:\steam\steamapps\common\MountBlade Warband\Modules\Native\parties.txt"
ID_AT = 0xa0
SPAN = 0x2000

r = Reader(process.try_attach())
game = r.ptr(0x8b82a0)
parties = [r.ptr(at) for at in r.vector(game + 0x140b8, 4)]
print(f"{len(parties)} parties")
by_id = {}
for p in parties:
    if p:
        try:
            by_id[r.rgl_string(p + ID_AT)] = p
        except ReadError:
            pass

if sys.argv[1:2] == ["dump"]:
    p = by_id[sys.argv[2]]
    data = r.read(p, 0x300)
    for off in range(0, 0x300, 4):
        i, = struct.unpack_from("<i", data, off)
        f, = struct.unpack_from("<f", data, off)
        print(f"+{off:#05x} {i:12d} {f:14.4f}")
    sys.exit()

# id -> (x, y) start position from parties.txt
start = {}
for line in open(PARTIES_TXT):
    w = line.split()
    if len(w) > 15 and w[3].startswith("p_"):
        start[w[3]] = (float(w[14]), float(w[15]))

hits = {}
for pid, (x, y) in start.items():
    if not pid.startswith(("p_town", "p_castle", "p_village")) or pid not in by_id:
        continue
    data = r.read(by_id[pid], SPAN)
    pair = struct.pack("<ff", x, y)
    offs = [m.start() for m in re.finditer(re.escape(pair), data) if m.start() % 4 == 0]
    for o in offs:
        hits[o] = hits.get(o, 0) + 1
print("position offsets (offset: towns matching):",
      {f"{o:#x}": n for o, n in sorted(hits.items())})
print("first ids:", list(by_id)[:12])
