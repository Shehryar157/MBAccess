"""The world map: what a sighted player can see on it, and travelling.

A sighted player travels by clicking a town, a village, a moving party or a
spot of ground; the party rides there by itself (the game plans the road).
So we list the things they can see, nearest first, with the direction and
distance, and Enter gives the same travel order a click gives.

Memory (docs/findings/map.md, profile screen["map"], Warband 1.174):
- game+parties is an stl::vector of pointers to BLOCKS of 16 parties:
  party n = blocks[n // 16] + (n % 16) * party_size. Party 0 is the player.
- In a party: +4 valid, +8 its number, name and id (rgl::strings), position
  (x east, y north), label_visible (1 = spotted, for moving parties),
  faction, flags (0x100 disabled, 0x4000 always visible: towns, castles and
  villages), troop stacks (count is a stack's first int), attached_to.
- A click's travel order (found by watching a real click): behaviour +
  its object, move mode, target point and target party.

What we list: places that are always visible (unless disabled), and moving
parties only while spotted, as a sighted player only sees those.
"""
import math
import struct
import time
from dataclasses import dataclass

from . import text as text_mod
from .form import Item
from .mem import RGL_STRING_STATIC, ReadError

DISABLED, ALWAYS_VISIBLE = 0x100, 0x4000
TRAVEL_TO_PARTY, IN_TOWN = 1, 8        # ai behaviours (header_parties.py)
MOVE_TO_PARTY = 2                       # move mode a click on a party writes
REFRESH = 1.0          # seconds between reads of the party table
CHUNK = 0x278          # one read per party: from its start to attached_to
STACK_SIZE = 32
KINDS = (("p_town", "town"), ("p_castle", "castle"), ("p_village", "village"))
COMPASS = ("east", "north-east", "north", "north-west",
           "west", "south-west", "south", "south-east")


@dataclass
class Spot:
    number: int
    address: int
    name: str
    kind: str          # "town", "castle", "village", or "" for a moving party
    x: float
    y: float
    faction: str
    troops: int = 0


def compass(dx, dy):
    """One of 8 directions; the map's +x is east and +y north."""
    angle = math.degrees(math.atan2(dy, dx)) % 360
    return COMPASS[int((angle + 22.5) // 45) % 8]


def describe(spot, here):
    """ "Jelkala, town, 3 north-east, Kingdom of Rhodoks": what tells places
    apart comes first; the kingdom, often the same down the list, last."""
    dx, dy = spot.x - here[0], spot.y - here[1]
    distance = math.hypot(dx, dy)
    where = "here" if distance < 0.5 else f"{distance:.0f} {compass(dx, dy)}"
    parts = [spot.name, spot.kind, f"{spot.troops} troops" if spot.troops else "",
             where, spot.faction]
    return ", ".join(p for p in parts if p)


class WorldMap:
    def __init__(self, reader, offsets, say=None):
        self.r, self.o = reader, offsets
        self.say = say
        self.spots, self.here, self.when, self.game = [], (0.0, 0.0), 0.0, None
        self.factions = []
        self.target = None      # the Spot we sent the party to

    # --- reading -----------------------------------------------------------

    def parties(self, game):
        """(number, address) of every party slot in use."""
        o = self.o
        for b, at in enumerate(self.r.vector(game + o["parties"], 4)):
            block = self.r.ptr(at)
            for slot in range(o["block"]):
                yield b * o["block"] + slot, block + slot * o["party_size"]

    def string_in(self, data, address, offset):
        """An rgl::string inside a chunk we already read: short ones sit in
        its static buffer; a long one is read from where it points."""
        buffer, = struct.unpack_from("<I", data, offset + 4)
        length, = struct.unpack_from("<I", data, offset + 12)
        if buffer == address + offset + RGL_STRING_STATIC and length < 128:
            start = offset + RGL_STRING_STATIC
            return data[start:start + length].decode("latin-1")
        return self.r.rgl_string(address + offset)

    def faction_names(self, game):
        o = self.o
        first, count = struct.unpack("<Ii", self.r.read(game + o["factions"], 8))
        names = []
        for n in range(max(0, min(count, 256))):
            name = self.r.rgl_string(first + n * o["faction_size"])
            names.append("" if name.startswith("{!}") else text_mod.clean(name))
        return names

    def troops(self, address, data):
        o = self.o
        first, = struct.unpack_from("<I", data, o["stacks"])
        count, = struct.unpack_from("<i", data, o["num_stacks"])
        if not 0 < count <= 64:
            return 0
        stacks = self.r.read(first, count * STACK_SIZE)
        return sum(struct.unpack_from("<i", stacks, n * STACK_SIZE)[0] for n in range(count))

    def refresh(self, game):
        o = self.o
        if game != self.game:
            self.game, self.factions, self.target = game, self.faction_names(game), None
        spots, here = [], None
        for number, p in self.parties(game):
            try:
                data = self.r.read(p, CHUNK)
            except ReadError:
                continue
            valid, no = struct.unpack_from("<ii", data, 4)
            if not valid or no != number:
                continue        # an empty slot
            x, y = struct.unpack_from("<ff", data, o["position"])
            if number == 0:
                here = (x, y)
                continue
            flags, = struct.unpack_from("<Q", data, o["flags"])
            if flags & DISABLED:
                continue
            attached, = struct.unpack_from("<i", data, o["attached_to"])
            seen, = struct.unpack_from("<i", data, o["label_visible"])
            static = flags & ALWAYS_VISIBLE
            if not static and (seen != 1 or attached != -1):
                continue        # a moving party not spotted, or inside a town
            name = self.string_in(data, p, o["name"])
            if not name or name.startswith("{!}"):
                continue
            pid = self.string_in(data, p, o["id"])
            kind = next((k for prefix, k in KINDS if pid.startswith(prefix)), "")
            faction_no, = struct.unpack_from("<i", data, o["faction"])
            faction = self.factions[faction_no] if 0 <= faction_no < len(self.factions) else ""
            spot = Spot(number, p, text_mod.clean(name), kind, x, y, faction)
            if not static:
                try:
                    spot.troops = self.troops(p, data)
                except ReadError:
                    pass
            spots.append(spot)
        if here is None:
            raise ReadError("no player party")
        spots.sort(key=lambda s: math.hypot(s.x - here[0], s.y - here[1]))
        self.spots, self.here, self.when = spots, here, time.monotonic()

    def items(self, game):
        """The list for the map screen, as the mod's own (virtual) items.
        The party's address is the item's widget, so the cursor stays on the
        same place while the list re-sorts as we ride."""
        if game != self.game or time.monotonic() - self.when >= REFRESH:
            self.refresh(game)
        self.check_arrival(game)
        return [Item("place", describe(s, self.here), 0.0, 0.0, widget=s.address,
                     virtual="map") for s in self.spots]

    def spot_at(self, address):
        return next((s for s in self.spots if s.address == address), None)

    # --- travelling ----------------------------------------------------------

    def player(self, game):
        return next(p for n, p in self.parties(game) if n == 0)

    def travel(self, game, item):
        """Give the order a click on that place gives (findings/map.md).
        The move mode goes last: it's what sets the party off."""
        spot = self.spot_at(item.widget)
        if spot is None:
            return
        o, me = self.o, self.player(game)
        self.r.write(me + o["behaviour"], struct.pack("<ii", TRAVEL_TO_PARTY, spot.number))
        self.r.write(me + o["move_target"], struct.pack("<ff", spot.x, spot.y))
        self.r.write(me + o["move_target_party"], struct.pack("<i", spot.number))
        self.r.write(me + o["move_mode"], struct.pack("<i", MOVE_TO_PARTY))
        self.target = spot
        if self.say:
            self.say(f"Travelling to {spot.name}")

    def check_arrival(self, game):
        """Say when we reach the place we set off for: the game then marks
        the party as in town with that place as its object."""
        if self.target is None:
            return
        o, me = self.o, self.player(game)
        behaviour, thing = struct.unpack("<ii", self.r.read(me + o["behaviour"], 8))
        if behaviour == IN_TOWN and thing == self.target.number:
            if self.say:
                self.say(f"Arrived at {self.target.name}")
            self.target = None
        elif behaviour != TRAVEL_TO_PARTY or thing != self.target.number:
            self.target = None      # the player gave another order
