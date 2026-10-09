"""Scene scanner: what's around the player, by direction, while walking in a scene.

K, L, semicolon, O: things to the left, behind, right and ahead, nearest first; the same
key again steps to the next one. Shift+L / Shift+semicolon: previous / next category.
J or Shift+K: where the current thing is now (it may have moved, and so may you).

Directions are relative to the way the player faces: a thing counts as ahead when it's
within 45 degrees of straight ahead, so "mostly ahead, a bit left" is under O.

Memory layout (Warband 1.174, found 2026-10-10, docs/findings/scenes.md "Scanner"):
- mission+0xc75c: mission_objects (rgl::stable_vector, same shape as the agents at
  mission+4): chunks of 16 objects, OBJECT_SIZE bytes each. Found by shape
  (tools/probe_objects.py), so it can be found again for WFS.
- object: valid +4, no +8, position matrix +0x18 (origin x y z at +0x48), meta type +0x1ac,
  sub kind +0x1b0, id rgl::string +0x1b4 ("spr_village_house_e"), variation +0x244.
- agent: troop number +0x298 (troop name = troops[n] name), horse item +0x29c (assumed).
"""
import math
import struct

from . import keys, text as text_mod, walls
from .mem import ReadError

OBJECTS = 0xc75c
OBJECT_SIZE = 0x298
OBJ_POS, OBJ_META, OBJ_KIND, OBJ_ID, OBJ_VARIATION = 0x48, 0x1ac, 0x1b0, 0x1b4, 0x244
AGENT_TROOP, AGENT_HORSE_ITEM = 0x298, 0x29c
AGENT_HEAD = 0x2a0                  # bytes of each agent we need

# Object meta types (WSE mission_object.h; 0, 1, 2 and 4 seen in a village 2026-10-10).
PROP, ENTRY, SCENE_ITEM, PLANT, PASSAGE, SPAWNED_ITEM, DEATH_ITEM, SPAWNED_PROP = 0, 1, 2, 4, 5, 6, 8, 10
META_CATEGORY = {PROP: "Objects", SPAWNED_PROP: "Objects", PASSAGE: "Exits",
                 SCENE_ITEM: "Items", SPAWNED_ITEM: "Items", DEATH_ITEM: "Items"}

CATEGORIES = ("All", "People", "Exits", "Items", "Objects", "Animals")
# Hard-coded (can't be discovered from memory yet): props a sighted player never sees,
# such as light sources and invisible barriers. Matched against the id without "spr_".
INVISIBLE = ("light", "barrier", "ai_limiter", "invisible", "collision", "entry", "sound",
             "spawn", "dummy", "fire_point", "particle", "snowy_barrel")
DOOR_WORDS = ("door", "gate", "passage", "stairs", "ladder")

DIRECTIONS = {keys.KEY_O: "ahead", keys.KEY_K: "to the left",
              keys.SEMICOLON: "to the right", keys.KEY_L: "behind"}


def prop_name(ident):
    """'spr_village_house_e' -> 'village house': words from the id, without
    variant letters or numbers ('castle_f_stairs' -> 'castle stairs')."""
    for prefix in ("spr_", "itm_"):
        if ident.startswith(prefix):
            ident = ident[len(prefix):]
    words = [w for w in ident.split("_") if len(w) > 1 and not w.isdigit()]
    while len(words) > 1 and words[-1] in ("night", "day", "new", "old"):
        words.pop()
    return " ".join(words) or "something"


def relative(player, x, y):
    """(distance, angle in degrees: 0 ahead, positive to the left, -180..180)."""
    px, py, _, facing, _ = player
    heading = facing + walls.FORWARD
    a = math.degrees(math.atan2(y - py, x - px) - heading)
    a = (a + 180) % 360 - 180
    return math.hypot(x - px, y - py), a


def quarter(angle):
    if abs(angle) <= 45:
        return keys.KEY_O
    if abs(angle) >= 135:
        return keys.KEY_L
    return keys.KEY_K if angle > 0 else keys.SEMICOLON


def describe_angle(a):
    """Words for a relative angle (positive = left)."""
    side = "left" if a > 0 else "right"
    m = abs(a)
    if m < 10:
        return "straight ahead"
    if m < 30:
        return "ahead, slightly " + side
    if m < 60:
        return "ahead " + side
    if m < 80:
        return side + ", a little ahead"
    if m <= 100:
        return side
    if m <= 120:
        return side + ", a little behind"
    if m <= 150:
        return "behind " + side
    if m <= 170:
        return "behind, slightly " + side
    return "straight behind"


def describe_distance(d):
    return "%d metre%s" % (round(d), "" if round(d) == 1 else "s") if d >= 1.5 else "right here"


class Scanner:
    def __init__(self, reader, profile, say, item_name=None, passage_name=None):
        self.r, self.profile, self.say = reader, profile, say
        self.item_name = item_name or (lambda kind: "item")
        self.passage_name = passage_name or (lambda number: None)
        self.category = 0
        self.direction = None
        self.snapshot = []          # (key, name) for the current direction, nearest first
        self.index = -1
        self.current = None         # key of the thing last spoken: ("agent", no) / ("object", no)

    # --- reading the scene -------------------------------------------------------

    def _troop_name(self, number):
        offsets = self.profile.screen.get("party_skills", {})
        game = self.r.u32(self.profile.game_offsets["cur_game_ptr"])
        troops = self.r.u32(game + offsets["troops"])
        return text_mod.clean(self.r.rgl_string(troops + number * offsets["troop_size"] + 4))

    def _chunks(self, header):
        begin, end = struct.unpack("<II", self.r.read(header, 8))
        if not begin or end <= begin or end - begin > 4 * 4000:
            return ()
        return struct.unpack("<%dI" % ((end - begin) // 4), self.r.read(begin, end - begin))

    def things(self):
        """Every thing worth announcing: dicts with key, name, category, x, y, z."""
        mission = walls.mission_address(self.r, self.profile)
        found, people = [], []
        horses = []
        for chunk in self._chunks(mission + 0x20):
            for i in range(16):
                try:
                    h = self.r.read(chunk + i * walls.AGENT_SIZE, AGENT_HEAD)
                except ReadError:
                    continue
                no = struct.unpack_from("<i", h, 8)[0]
                valid = struct.unpack_from("<i", h, 4)[0]
                kind, _, status, flags = struct.unpack_from("<iiiI", h, walls.AGENT_TYPE)
                if valid != 1 or status != 1 or flags & 1:
                    continue
                x, y, z = struct.unpack_from("<3f", h, walls.AGENT_POS)
                if kind == 1:
                    horses.append((no, x, y, z, struct.unpack_from("<i", h, AGENT_HORSE_ITEM)[0]))
                    continue
                troop = struct.unpack_from("<i", h, AGENT_TROOP)[0]
                try:
                    name = self._troop_name(troop)
                except (ReadError, KeyError, TypeError):
                    name = "someone"
                people.append(dict(key=("agent", no), name=name, category="People", x=x, y=y, z=z))
        found += people
        player = walls.find_player(self.r, mission)
        riders = [(p["x"], p["y"]) for p in people] + ([player[:2]] if player else [])
        for no, x, y, z, item in horses:
            # A ridden horse shares its rider's position: the rider is enough.
            if any(abs(x - rx) < 0.1 and abs(y - ry) < 0.1 for rx, ry in riders):
                continue
            found.append(dict(key=("agent", no), name=self.item_name(item) or "horse",
                              category="Animals", x=x, y=y, z=z))
        for chunk in self._chunks(mission + OBJECTS + 0x1c):
            try:
                block = self.r.read(chunk, 16 * OBJECT_SIZE)
            except ReadError:
                continue
            for i in range(16):
                o = i * OBJECT_SIZE
                if struct.unpack_from("<i", block, o + 4)[0] != 1:
                    continue
                meta, kind = struct.unpack_from("<ii", block, o + OBJ_META)
                category = META_CATEGORY.get(meta)
                if category is None:
                    continue
                no = struct.unpack_from("<i", block, o + 8)[0]
                x, y, z = struct.unpack_from("<3f", block, o + OBJ_POS)
                if category == "Items":
                    name = self.item_name(kind)
                else:
                    ident = self.r.rgl_string(chunk + o + OBJ_ID)
                    bare = ident[4:] if ident.startswith("spr_") else ident
                    if meta != PASSAGE and any(bare.startswith(w) or ("_" + w) in bare for w in INVISIBLE):
                        continue
                    name = prop_name(ident)
                    if meta == PASSAGE:
                        variation = struct.unpack_from("<i", block, o + OBJ_VARIATION)[0]
                        name = self.passage_name(variation) or "passage"
                    elif any(w in bare for w in DOOR_WORDS):
                        category = "Exits"
                found.append(dict(key=("object", no), name=name, category=category, x=x, y=y, z=z))
        return player, found

    # --- keys --------------------------------------------------------------------

    def handle_keys(self, pressed):
        """Act on the scanner's keys; True if any was ours."""
        mine = False
        shift = keys.is_down(keys.SHIFT)
        for key in pressed:
            if key == keys.KEY_J or (key == keys.KEY_K and shift):
                self.where()
            elif key in (keys.KEY_L, keys.SEMICOLON) and shift:
                self.category = (self.category + (1 if key == keys.SEMICOLON else -1)) % len(CATEGORIES)
                self.direction = None
                self.say(CATEGORIES[self.category])
            elif key in DIRECTIONS:
                self.step(key)
            else:
                continue
            mine = True
        return mine

    def _read(self):
        with self.r.cached():
            player, found = self.things()
        if player is None:
            self.say("can't find you in the scene")
            return None, []
        wanted = CATEGORIES[self.category]
        if wanted != "All":
            found = [t for t in found if t["category"] == wanted]
        return player, found

    def step(self, key):
        if key != self.direction:
            player, found = self._read()
            if player is None:
                return
            rows = []
            for t in found:
                d, a = relative(player, t["x"], t["y"])
                if quarter(a) == key:
                    rows.append((d, t["key"], t["name"]))
            rows.sort()
            self.snapshot = [(k, n) for _, k, n in rows]
            self.direction, self.index = key, -1
        if not self.snapshot:
            self.say("nothing %s" % DIRECTIONS[key] if self.category == 0
                     else "no %s %s" % (CATEGORIES[self.category].lower(), DIRECTIONS[key]))
            self.direction = None       # look again next press: things move
            return
        self.index += 1
        wrapped = self.index >= len(self.snapshot)
        if wrapped:
            self.index = 0
        key_, name = self.snapshot[self.index]
        self.current = (key_, name)
        spoken = self._where_words(key_, name, short=True)
        self.say(("top. " if wrapped else "") + spoken)

    def _where_words(self, thing_key, name, short=False):
        player, found = self._read_all()
        if player is None:
            return name
        for t in found:
            if t["key"] == thing_key:
                d, a = relative(player, t["x"], t["y"])
                if short:
                    return "%s, %s" % (name, describe_distance(d))
                words = "%s: %s, %s" % (name, describe_distance(d), describe_angle(a))
                rise = t["z"] - player[2]
                if abs(rise) >= 2 and d >= 1.5:
                    words += ", %d metres %s" % (round(abs(rise)), "up" if rise > 0 else "down")
                return words
        return "%s is gone" % name

    def _read_all(self):
        with self.r.cached():
            return self.things()

    def where(self):
        if self.current is None:
            self.say("nothing chosen. Use K, L, semicolon or O first")
            return
        self.say(self._where_words(*self.current))
