"""Fighters in a scene: health and teams (the start of battle support).

WarbandLib's agent.h (1.153) has, in a row: hit_points_at_spawn, hit_points_max,
hit_points_float (floats), then hit_points_int; and elsewhere team_no, group_no,
division_no. The offsets differ in 1.174 and the struct between is full of types we
can't size, so we find them by shape in the live agents instead (docs/findings/battles.md).
"""
import math
import struct

from . import walls
from .mem import ReadError

HUMAN, HORSE = 0, 1
ALIVE = 1
MAX_HEALTH = 2000.0     # nothing in the game has more hit points than this
# Found by find_health in Buvran's centre (2026-10-10): villagers 42-44, a horse 100, us 52.
HEALTH_MAX, HEALTH_NOW = 0x5ffc, 0x6000     # floats; +0x5ff8 at spawn, +0x6004 as an int
AGENT_HORSE = 0x114     # the agent number of the horse a rider is on, or -1
# The team number (found in a Jelkala arena melee the user fought, 2026-10-10: the six
# fighters read 3, 5, 3, 5, 2, 2, the Tournament Master watching -1, the player 6; +0x7b8
# holds the same). Villagers in a peaceful scene are -1 and the player 0.
AGENT_TEAM = 0x7b4
NO_TEAM = -1


# The upper body's current animation: an index into the module's actions.txt (found in the
# user's custom battle, 2026-10-10: 188 ready_throwing_knife, 189 release_throwing_knife,
# 320 defend_shield_keep, 143 equip_default, -1 between). +0x6e8 holds the same.
AGENT_ACTION = 0x6e4
SWINGS = ("slash", "thrust", "overswing", "swing", "direct", "uppercut")   # melee "ready_" names
MELEE_REACH = 5.0       # metres: a raised weapon this near is meant for us
RANGED_REACH = 80.0
AIMED = 15.0            # degrees: an archer facing us this squarely is aiming at us
AIM_WIDTH = 3.0         # metres either side of us that still counts as "at us" from afar


def wind_up(name):
    """ "melee" or "ranged" if the animation is a weapon being raised or drawn, else None.
    Told from the names the game gives them: ready_slashright_onehanded, ready_bow..."""
    if not name.startswith("ready_"):
        return None
    return "melee" if any(word in name for word in SWINGS) else "ranged"


class SwingWatch:
    """Notices enemies near the player starting an attack: what a sighted player sees as
    a weapon going up. check() gives each new one once."""

    def __init__(self, action_names):
        self.names = action_names
        self.last = {}          # agent number -> the action it was in

    def check(self, reader, mission, player):
        """[(kind, distance, angle)] for attacks that began since the last call: kind
        "melee" or "ranged", angle in degrees from where the player faces (positive left)."""
        fighters, mine = [], NO_TEAM
        for no, _address, data in agents(reader, mission, AGENT_TEAM + 4):
            kind, _, status, flags = struct.unpack_from("<iiiI", data, walls.AGENT_TYPE)
            if kind != HUMAN or status != ALIVE:
                continue
            team = struct.unpack_from("<i", data, AGENT_TEAM)[0]
            if flags & 1:
                mine = team
            else:
                fighters.append((no, team, data))
        started, seen = [], {}
        px, py, facing = player[0], player[1], player[3]
        for no, team, data in fighters:
            action = seen[no] = struct.unpack_from("<i", data, AGENT_ACTION)[0]
            if action == self.last.get(no) or side(mine, team) != "Enemies":
                continue
            kind = wind_up(self.names[action]) if 0 <= action < len(self.names) else None
            if kind is None:
                continue
            x, y = struct.unpack_from("<2f", data, walls.AGENT_POS)
            distance = math.hypot(x - px, y - py)
            if kind == "melee" and distance > MELEE_REACH:
                continue
            if kind == "ranged":
                # Is he facing us? His heading against the direction from him to us.
                heading = struct.unpack_from("<f", data, walls.AGENT_DIRF)[0] + walls.FORWARD
                off = math.degrees(math.atan2(py - y, px - x) - heading)
                # Far off, "at us" is a narrow line: within AIM_WIDTH metres of where we stand.
                allowed = min(AIMED, math.degrees(math.atan2(AIM_WIDTH, max(distance, 0.1))))
                if distance > RANGED_REACH or abs((off + 180) % 360 - 180) > allowed:
                    continue
            angle = math.degrees(math.atan2(y - py, x - px) - facing - walls.FORWARD)
            started.append((kind, distance, (angle + 180) % 360 - 180))
        self.last = seen
        return started


# What a fighter carries and holds (from the user's custom battle, 2026-10-10: Throwing
# Daggers and a Wooden Shield). Item slot n's kind is at +0x7d4 + 8 * n (the int after it
# is that item's own count: daggers thrown, a shield's 360 hit points). +0x830 = the slot
# in the right hand, +0x834 the left (a shield); -1 = nothing. +0x838/+0x83c repeat them.
AGENT_ITEMS, ITEM_STRIDE, ITEM_SLOTS = 0x7d4, 8, 4
AGENT_HANDS = 0x830


def player_agent(reader, mission):
    """Address of the player's living agent, or None."""
    for _no, address, data in agents(reader, mission, 0x38):
        kind, _, status, flags = struct.unpack_from("<iiiI", data, walls.AGENT_TYPE)
        if kind == HUMAN and status == ALIVE and flags & 1:
            return address
    return None


def held(reader, address):
    """(right hand's item kind, left hand's): None for an empty hand."""
    kinds = []
    for slot in struct.unpack("<2i", reader.read(address + AGENT_HANDS, 8)):
        kinds.append(reader.i32(address + AGENT_ITEMS + ITEM_STRIDE * slot)
                     if 0 <= slot < ITEM_SLOTS else None)
    return tuple(kinds)


def held_words(now, name, before=None):
    """What to say when the hands change from `before` to `now`: the names of what's
    newly held, or that a hand is now empty. With no `before`, everything held."""
    right, left = now
    parts = []
    if before is None:
        parts = [name(kind) for kind in now if kind is not None]
    else:
        if right != before[0]:
            parts.append(name(right) if right is not None else "weapon put away")
        if left != before[1]:
            parts.append(name(left) if left is not None else "no shield")
    return ", ".join(parts)


class HandWatch:
    """Speaks the weapon or shield the player has just switched to: a sighted player sees
    it in their hands. poll() returns the words, or None."""
    EVERY = 0.15

    def __init__(self, name):
        self.name = name        # item kind -> its name
        self.last, self.checked = None, 0.0

    def poll(self, reader, mission, now):
        if now - self.checked < self.EVERY:
            return None
        self.checked = now
        me = player_agent(reader, mission)
        if me is None:
            self.last = None    # not in a scene, or knocked out: start again next time
            return None
        hands = held(reader, me)
        if hands == self.last:
            return None
        before, self.last = self.last, hands
        return held_words(hands, self.name, before) or None


def side(mine, theirs):
    """ "Enemies", "Allies" or None (a bystander, or no fight) for someone on team
    `theirs` when we're on team `mine`. Every other team counts as an enemy: right in an
    arena melee; a battle beside an allied lord (a friendly team) still has to be checked."""
    if theirs == NO_TEAM or mine == NO_TEAM:
        return None
    return "Allies" if theirs == mine else "Enemies"
HEAD = 0x120            # bytes of an agent that tell who it is


def health(reader, address):
    """(now, most) hit points of the agent at address."""
    most, now = struct.unpack("<2f", reader.read(address + HEALTH_MAX, 8))
    return now, most


def health_words(reader, mission):
    """ "Health 40 of 52, horse 100 of 100": the player's, and their horse's if mounted."""
    found = {no: (address, data) for no, address, data in agents(reader, mission, HEAD)}
    for address, data in found.values():
        kind, _, status, flags = struct.unpack_from("<iiiI", data, walls.AGENT_TYPE)
        if kind != HUMAN or not flags & 1:
            continue
        if status != ALIVE:
            return "you are down"
        words = "Health %.0f of %.0f" % health(reader, address)
        horse = found.get(struct.unpack_from("<i", data, AGENT_HORSE)[0])
        if horse:
            words += ", horse %.0f of %.0f" % health(reader, horse[0])
        return words
    return "can't find you"


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
