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

The right-click menu (Move here, View notes, Accompany) is the game's own:
the module script fills it, so we open the real one. We put the map camera
on the place (it then sits mid-screen and close, wherever it is), right-click
where the camera says it's drawn, and check the game's answer: the party the
menu is for, in the map window. The rows are in the game object. To choose
one we slide the mouse down until the game says it's over that row, so no row
height is assumed. The menu closes by itself when the mouse goes far from it.
"""
import contextlib
import math
import struct
import threading
import time
from dataclasses import dataclass

from . import text as text_mod
from .form import Item
from .mem import RGL_STRING_SIZE, RGL_STRING_STATIC, ReadError

DISABLED, ALWAYS_VISIBLE = 0x100, 0x4000
# The player's click order: behaviour 4 ("attack party" in header_parties.py,
# but for the player it means "go and meet it": arriving starts the encounter
# that opens the place's menu or the conversation). Behaviour 1, "travel to
# party", is the AI lords' order: the party rides in quietly and no menu opens.
MEET, IN_TOWN = 4, 8
MOVE_TO_POINT, MOVE_TO_PARTY = 1, 2     # move modes: a place click / a party click
REFRESH = 1.0          # seconds between reads of the party table
CHUNK = 0x278          # one read per party: from its start to attached_to
STACK_SIZE = 32
KINDS = (("p_town", "town"), ("p_castle", "castle"), ("p_village", "village"))
COMPASS = ("east", "north-east", "north", "north-west",
           "west", "south-west", "south", "south-east")
MAP_WINDOW = 6
NO_MENU = -1            # the map window's menu mode while no right-click menu is open
MENU_ROWS = 50          # the game object has room for 50 rows
MOVE_HERE = -7          # a row's value: cmenu_move (the engine's own travel order)
SCREEN_HEIGHT = 0.75    # engine screen coordinates: x 0-1, y 0-0.75 from the bottom
# Where to right-click, from the spot the place is drawn at. Dead on first; the rest
# are for a place our own party stands on and covers (the game then answers "party 0").
AIM = ((0.0, 0.0), (-0.06, 0.0), (0.06, 0.0), (0.0, 0.06), (-0.035, 0.0), (0.035, 0.0))
UNDER_US = 0.6          # map units: a place this near is covered by our own party
ROW_STEP, ROW_REACH = 0.004, 0.25   # sliding down the rows: step, and how far to look
# Where the mouse goes to close a menu: far from where places are drawn (low, mid-screen),
# but not at a screen edge, which would scroll the map.
FAR_AWAY = (0.5, 0.62)
MENU_WAIT = 0.4         # seconds for the menu to answer a right click
CAMERA_WAIT = 0.8       # seconds for the camera to arrive over a place


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
        self.menu_at = self.menu_spot = None    # the open right-click menu: where we clicked, on what
        self.home = None        # the camera's place before we moved it onto a menu's party

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
        self.r.write(me + o["behaviour"], struct.pack("<ii", MEET, spot.number))
        self.r.write(me + o["move_target"], struct.pack("<ff", spot.x, spot.y))
        if spot.kind:       # a place doesn't move: a click on it orders "ride to this point"
            mode = MOVE_TO_POINT
        else:               # a moving party: follow it (the game keeps the point updated)
            mode = MOVE_TO_PARTY
            self.r.write(me + o["move_target_party"], struct.pack("<i", spot.number))
        self.r.write(me + o["move_mode"], struct.pack("<i", mode))
        self.target = spot
        if self.say:
            self.say(f"Travelling to {spot.name}")

    def check_arrival(self, game):
        """Say when we reach what we set off for: the encounter changes the
        order (to 7, negotiate, for a place), and the game opens its menu or
        the conversation, which the mod then reads."""
        if self.target is None:
            return
        o, me = self.o, self.player(game)
        behaviour, thing = struct.unpack("<ii", self.r.read(me + o["behaviour"], 8))
        if behaviour == MEET and thing == self.target.number:
            return              # still on the way
        if thing == self.target.number and self.say:
            self.say(f"Arrived at {self.target.name}")
        self.target = None      # arrived, or the player gave another order

    # --- the right-click menu ------------------------------------------------

    def live(self, address, fmt):
        """Read past the reader's page cache: we're waiting for the game to change it."""
        return struct.unpack(fmt, self.r._direct(address, struct.calcsize(fmt)))

    def project(self, window, point):
        """Map position -> where it's drawn (engine screen coordinates), or None behind
        the camera. The camera matrix's rows are right, up, backward, then its place;
        after it come the view's left, right, up and down edges and the near distance."""
        m = self.live(window + self.o["camera"], "<16f")
        left, right, up, down, near = self.live(window + self.o["camera"] + 64, "<5f")
        v = [point[n] - m[12 + n] for n in range(3)]
        side, rise, back = (sum(v[n] * m[row * 4 + n] for n in range(3)) for row in range(3))
        if -back <= near:
            return None
        return (0.5 + side * near / -back / (right - left),
                SCREEN_HEIGHT * (0.5 + rise * near / -back / (up - down)))

    def menu_rows(self, game):
        """The open menu's rows as (text, value), and the row under the mouse (-1: none)."""
        at = game + self.o["context_rows"]
        count, over = self.live(at, "<ii")
        if not 0 < count <= MENU_ROWS:      # junk until the first menu of a session
            return [], -1
        values = self.live(at + 8 + MENU_ROWS * RGL_STRING_SIZE, f"<{count}i")
        return [(text_mod.clean(self.r.rgl_string(at + 8 + n * RGL_STRING_SIZE)), values[n])
                for n in range(count)], over

    def menu_party(self, window):
        """The party the open right-click menu is for, or None with no menu open."""
        mode, party = self.live(window + self.o["context_menu"], "<ii")
        return None if mode == NO_MENU else party

    def open_menu(self, game, window, mouse, item):
        """Right-click the place as a sighted player would. Returns its rows ([] if the
        game offers none or we couldn't hit it); the menu is then open under the mouse."""
        spot = self.spot_at(item.widget)
        if spot is None or "camera" not in self.o:
            return []
        o = self.o
        self.close_menu(window, mouse)
        if self.menu_party(window) is not None:
            self.dismiss(window, mouse)     # one the player opened by hand
        place = self.live(spot.address + o["position"], "<3f")
        self.home = self.r._direct(window + o["camera_origin"], 12)
        # Look at it as the camera looks at our own party: from one unit above the ground.
        over_it = struct.pack("<3f", place[0], place[1], place[2] + 1.0)
        with self.camera_held(window, over_it):
            # The camera matrix follows a frame or two later: wait until the place is
            # drawn mid-screen, as our own party is when the camera is on it.
            until = time.monotonic() + CAMERA_WAIT
            drawn = None
            while time.monotonic() < until and not (drawn and abs(drawn[0] - 0.5) < 0.01):
                time.sleep(0.03)
                drawn = self.project(window, place)
            if not (drawn and abs(drawn[0] - 0.5) < 0.01):
                drawn = None
            covered = math.hypot(spot.x - self.here[0], spot.y - self.here[1]) < UNDER_US
            for dx, dy in (AIM[1:] if covered else AIM) if drawn else ():
                x, y = drawn[0] + dx, drawn[1] + dy
                mouse.hover(x, y)
                time.sleep(0.15)    # the game picks what's under the mouse as it moves
                mouse.click(x, y, right=True)
                until = time.monotonic() + MENU_WAIT
                while time.monotonic() < until and self.menu_party(window) is None:
                    time.sleep(0.03)
                if self.menu_party(window) == spot.number:
                    self.menu_at, self.menu_spot = (x, y), spot
                    return self.menu_rows(game)[0]
                if self.menu_party(window) is not None:
                    self.dismiss(window, mouse)     # something else's menu
        self.close_menu(window, mouse)
        return []

    @contextlib.contextmanager
    def camera_held(self, window, origin):
        """Keep the map camera over a point for the length of the block. While time runs
        the game slides the camera back to our own party, several map units a second,
        so one write isn't enough: a thread writes it again every few milliseconds."""
        done = threading.Event()

        def hold():
            while not done.is_set():
                try:
                    self.r.write(window + self.o["camera_origin"], origin)
                except Exception:
                    return      # the game closed
                time.sleep(0.004)

        thread = threading.Thread(target=hold, daemon=True)
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join()

    def point_at_row(self, game, mouse, row):
        """Slide the mouse down from the click until the game says it's over that row.
        Returns the height it's then at, or None if the row never came under it."""
        x, y = self.menu_at
        for step in range(int(ROW_REACH / ROW_STEP)):
            mouse.hover(x + 0.02, y - step * ROW_STEP)
            time.sleep(0.03)
            if self.menu_rows(game)[1] == row:
                # A little further in, so we aren't on the row's very edge.
                mouse.hover(x + 0.02, y - (step + 1) * ROW_STEP)
                time.sleep(0.05)
                return y - (step + 1) * ROW_STEP if self.menu_rows(game)[1] == row else None
        return None

    def choose_row(self, game, window, mouse, row):
        """Click a row of the open menu. True if the game took it."""
        rows, _over = self.menu_rows(game)
        y = None
        if self.menu_party(window) is not None and row < len(rows):
            y = self.point_at_row(game, mouse, row)
        if y is None:
            self.close_menu(window, mouse)
            return False
        mouse.click(self.menu_at[0] + 0.02, y, hold=0.05)
        time.sleep(0.2)     # let the game see the click before the mouse leaves
        if rows[row][1] == MOVE_HERE:
            self.target = self.menu_spot    # so we say when we arrive, as after Enter
        self.close_menu(window, mouse)
        return True

    def dismiss(self, window, mouse):
        """Take the mouse away from the menu: the game then closes it."""
        mouse.hover(*FAR_AWAY)
        until = time.monotonic() + MENU_WAIT
        while time.monotonic() < until and self.menu_party(window) is not None:
            time.sleep(0.03)

    def close_menu(self, window, mouse):
        """Close our menu, if it's open, and put the camera back where it was."""
        if self.menu_at is not None:
            self.dismiss(window, mouse)
        if self.home is not None:
            self.r.write(window + self.o["camera_origin"], self.home)
        self.menu_at = self.menu_spot = self.home = None
