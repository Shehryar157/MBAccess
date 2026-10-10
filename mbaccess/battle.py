"""Fighters in a scene: health and teams (the start of battle support).

WarbandLib's agent.h (1.153) has, in a row: hit_points_at_spawn, hit_points_max,
hit_points_float (floats), then hit_points_int; and elsewhere team_no, group_no,
division_no. The offsets differ in 1.174 and the struct between is full of types we
can't size, so we find them by shape in the live agents instead (docs/findings/battles.md).
"""
import struct

from . import walls
from .mem import ReadError

HUMAN, HORSE = 0, 1
ALIVE = 1
MAX_HEALTH = 2000.0     # nothing in the game has more hit points than this


def agents(reader, mission, size=walls.AGENT_SIZE):
    """(number, address, whole agent bytes) of every agent in use, dead ones too."""
    begin, end = struct.unpack("<II", reader.read(mission + 0x20, 8))
    if not begin or end <= begin or end - begin > 4 * 1000:
        return
    chunks = struct.unpack("<%dI" % ((end - begin) // 4), reader.read(begin, end - begin))
    for c, chunk in enumerate(chunks):
        for i in range(16):
            try:
                data = reader.read(chunk + i * walls.AGENT_SIZE, size)
            except ReadError:
                continue
            if struct.unpack_from("<i", data, 4)[0] == 1:
                yield c * 16 + i, chunk + i * walls.AGENT_SIZE, data


def health_shape(data, offset):
    """Do the 16 bytes at offset look like spawn, max and current hit points (floats)
    and then the current ones again as a whole number?"""
    spawn, most, now, whole = struct.unpack_from("<3fi", data, offset)
    return (1.0 <= most <= MAX_HEALTH and 0.0 <= now <= most and 1.0 <= spawn <= most
            and abs(now - whole) < 1.0)


def find_health(living):
    """Offset of hit_points_at_spawn, given the bytes of several living agents: the
    places where every one of them has the health shape. A list, best guess first
    (several agents with different health leave one)."""
    if not living:
        return []
    size = min(len(data) for data in living)
    return [offset for offset in range(0x50, size - 16, 4)
            if all(health_shape(data, offset) for data in living)]


def small_int_fields(group, low=-1, high=15):
    """Offsets where every agent holds a small whole number and they aren't all the same:
    where a team, group or division number could be. {offset: [values]}."""
    if not group:
        return {}
    size = min(len(data) for data in group)
    found = {}
    for offset in range(0x50, size - 4, 4):
        values = [struct.unpack_from("<i", data, offset)[0] for data in group]
        if all(low <= v <= high for v in values) and len(set(values)) > 1:
            found[offset] = values
    return found
