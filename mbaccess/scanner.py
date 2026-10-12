"""Scene scanner: what's around the player, by direction, while walking in a scene.

Two lines through the player: O / L step along the ahead-behind line (further ahead /
further back), K / semicolon along the left-right line (further left / further right).
Starting with a key gives the nearest thing on that side. Shift+K / Shift+L: previous / next category.
J: where the current thing is now (it may have moved, and so may you).
Shift+J: track it: a ping plays from where it is (wall_beeps.py plays it).
Apostrophe: compass. Shift+A / Shift+D: turn 45 degrees left / right, Shift+S: turn round
(turning.py). Ctrl+A / Ctrl+D: turn to face the nearest thing on the left / right in the
current category (snap); it becomes the current thing, so J and Shift+J follow it.

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

from . import battle, keys, text as text_mod, walls
from .mem import ReadError

OBJECTS = 0xc75c
OBJECT_SIZE = 0x298
OBJ_POS, OBJ_META, OBJ_KIND, OBJ_ID = 0x48, 0x1ac, 0x1b0, 0x1b4
# A passage's menu option number (its second variation). Found 2026-10-10 in Jelkala's town
# centre: five doors read 7, 6, 5, 4, 2 here (dungeon, arena, shop, tavern, castle); the
# first variation (+0x244) was 0 for most of them.
OBJ_VARIATION = 0x248
AGENT_TROOP, AGENT_HORSE_ITEM = 0x298, 0x29c
AGENT_HEAD = 0x2a0                  # bytes of each agent we need

# Object meta types (WSE mission_object.h; 0, 1, 2 and 4 seen in a village 2026-10-10).
PROP, ENTRY, SCENE_ITEM, PLANT, PASSAGE, SPAWNED_ITEM, DEATH_ITEM, SPAWNED_PROP = 0, 1, 2, 4, 5, 6, 8, 10
META_CATEGORY = {PROP: "Objects", SPAWNED_PROP: "Objects", PASSAGE: "Exits",
                 # Items placed in the scene are merchants' displays: no prompt at any angle
                 # (Kettle Hat on the armourer's stall, 1.2 m, 2026-10-10). Named, but Objects.
                 SCENE_ITEM: "Objects", SPAWNED_ITEM: "Items", DEATH_ITEM: "Items"}
ITEM_METAS = (SCENE_ITEM, SPAWNED_ITEM, DEATH_ITEM)

CATEGORIES = ("All", "People", "Enemies", "Allies", "Exits", "Items", "Objects", "Animals", "Corpses")
# Hard-coded (can't be discovered from memory yet): props a sighted player never sees,
# such as light sources and invisible barriers. Matched against the id without "spr_".
INVISIBLE = ("light", "barrier", "ai_limiter", "invisible", "collision", "entry", "sound",
             "spawn", "dummy", "fire_point", "particle", "snowy_barrel",
             "shadow", "glow")      # 2026-10-10 tavern: shadow_square, glow_a are effects
# Props a player can walk through or climb count as Exits. Door props are only the picture of a
# door: the usable door is the passage on top of it (or the door does nothing), so they stay
# Objects (2026-10-10: "rhodok house passage" lay 0.3 m from the real "Door to the dungeon").
DOOR_WORDS = ("gate", "stairs", "ladder")

DIRECTIONS = {keys.KEY_O: "ahead", keys.KEY_K: "to the left",
              keys.SEMICOLON: "to the right", keys.KEY_L: "behind"}
SNAP_AHEAD = 10     # degrees: Ctrl+A/D skip a thing this close to straight ahead
SIDE_WORDS = {("ahead", 1): "ahead", ("ahead", -1): "behind",
              ("side", 1): "right", ("side", -1): "left"}


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
    def __init__(self, reader, profile, say, item_name=None, passage_name=None, turner=None):
        self.r, self.profile, self.say = reader, profile, say
        self.turner = turner
        self.tracked = None         # (key, name) the ping follows, or None
        self.item_name = item_name or (lambda kind: "item")
        self.passage_name = passage_name or (lambda number: None)
        self.category = 0
        self.direction = None
        self.current = None         # key of the thing last spoken: ("agent", no) / ("object", no)
        self.troop_names = {}       # troop number -> name: they never change
        self.counters = lambda: []  # the scene's on-screen counts (set by run.py)
        self.orders = lambda: []    # the open order panel's rows (set by run.py)
        self.holding = lambda: ""   # what's in the player's hands (set by run.py)
        self.object_names = {}      # object number -> (name, category or None to skip)
        self.names_scene = None     # the scene object_names belong to

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
        my_team = battle.NO_TEAM
        for chunk in self._chunks(mission + 0x20):
            for i in range(16):
                try:
                    h = self.r.read(chunk + i * walls.AGENT_SIZE, AGENT_HEAD)
                except ReadError:
                    continue
                no = struct.unpack_from("<i", h, 8)[0]
                valid = struct.unpack_from("<i", h, 4)[0]
                kind, _, status, flags = struct.unpack_from("<iiiI", h, walls.AGENT_TYPE)
                if valid == 1 and status == 1 and flags & 1 and kind == battle.HUMAN:
                    my_team = self.r.i32(chunk + i * walls.AGENT_SIZE + battle.AGENT_TEAM)
                fallen = battle.FALLEN.get(status)
                if valid != 1 or flags & 1 or not (status == 1 or fallen):
                    continue
                x, y, z = struct.unpack_from("<3f", h, walls.AGENT_POS)
                if kind == 1:
                    item = struct.unpack_from("<i", h, AGENT_HORSE_ITEM)[0]
                    if fallen:
                        found.append(dict(key=("agent", no), category="Corpses", x=x, y=y, z=z,
                                          name="%s, %s" % (self.item_name(item) or "horse", fallen)))
                    else:
                        horses.append((no, x, y, z, item))
                    continue
                troop = struct.unpack_from("<i", h, AGENT_TROOP)[0]
                name = self.troop_names.get(troop)
                if name is None:
                    try:
                        name = self.troop_names[troop] = self._troop_name(troop)
                    except (ReadError, KeyError, TypeError):
                        name = "someone"
                if fallen:
                    found.append(dict(key=("agent", no), name="%s, %s" % (name, fallen),
                                      category="Corpses", x=x, y=y, z=z))
                    continue
                people.append(dict(key=("agent", no), name=name, category="People", x=x, y=y, z=z,
                                   team=self.r.i32(chunk + i * walls.AGENT_SIZE + battle.AGENT_TEAM)))
        for person in people:       # in a fight: which side they're on
            person["side"] = battle.side(my_team, person["team"])
        found += people
        player = walls.find_player(self.r, mission, self.profile)
        riders = [(p["x"], p["y"]) for p in people] + ([player[:2]] if player else [])
        for no, x, y, z, item in horses:
            # A ridden horse shares its rider's position: the rider is enough.
            if any(abs(x - rx) < 0.1 and abs(y - ry) < 0.1 for rx, ry in riders):
                continue
            found.append(dict(key=("agent", no), name=self.item_name(item) or "horse",
                              category="Animals", x=x, y=y, z=z))
        scene = self.r.u32(mission)
        if scene != self.names_scene:       # names are read once per scene
            self.object_names, self.names_scene = {}, scene
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
                known = self.object_names.get(no)
                if known is None:
                    known = self.object_names[no] = self._object_name(chunk + o, block, o, meta, kind, category)
                name, category = known
                if category is not None:
                    found.append(dict(key=("object", no), name=name, category=category, x=x, y=y, z=z))
        return player, found

    def _object_name(self, address, block, o, meta, kind, category):
        """(name, category), or (None, None) for things a sighted player never sees."""
        if meta in ITEM_METAS:
            return self.item_name(kind), category
        ident = self.r.rgl_string(address + OBJ_ID)
        bare = ident[4:] if ident.startswith("spr_") else ident
        if meta != PASSAGE and any(bare.startswith(w) or ("_" + w) in bare for w in INVISIBLE):
            return None, None
        name = prop_name(ident)
        if meta == PASSAGE:
            variation = struct.unpack_from("<i", block, o + OBJ_VARIATION)[0]
            name = self.passage_name(variation) or "passage"
        elif any(w in bare for w in DOOR_WORDS):
            category = "Exits"
        return name, category

    # --- keys --------------------------------------------------------------------

    def handle_keys(self, pressed):
        """Act on the scanner's keys; True if any was ours."""
        mine = False
        shift = keys.is_down(keys.SHIFT)
        for key in pressed:
            if key == keys.KEY_J and shift:
                self.toggle_tracking()
            elif key == keys.KEY_J:
                self.where()
            elif key == keys.QUOTE and self.turner:
                self.say(self.turner.facing_words())
            elif key == keys.KEY_H:
                words = battle.health_words(self.r, walls.mission_address(self.r, self.profile))
                holding = self.holding()
                self.say(", ".join([words] + (["holding " + holding] if holding else [])
                                   + [c for c in self.counters() if c.startswith("ammunition")]))
            elif key == keys.KEY_B:
                self.battle_status()
            elif key == keys.KEY_N:
                self.nearest_enemy()
            elif key == keys.KEY_M:
                self.repeat_orders()
            elif key in (keys.KEY_A, keys.KEY_D) and shift and self.turner:
                self.turner.turn(45 if key == keys.KEY_A else -45)
            elif key == keys.KEY_S and shift and self.turner:
                self.turner.turn(180)
            elif key in (keys.KEY_A, keys.KEY_D) and keys.is_down(keys.CONTROL) and self.turner:
                self.snap(1 if key == keys.KEY_A else -1)
            elif key in (keys.KEY_K, keys.KEY_L) and shift:
                self.category = (self.category + (1 if key == keys.KEY_L else -1)) % len(CATEGORIES)
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
        if wanted == "All":     # the fallen only in their own list: a battlefield has dozens
            found = [t for t in found if t["category"] != "Corpses"]
        else:
            found = [t for t in found if wanted in (t["category"], t.get("side"))]
        return player, found

    # --- battles: who's standing, and the nearest enemy -------------------------------

    def battle_status(self):
        """B: how many stand on each side, and where the enemy's main body is."""
        player, found = self._read_all()
        if player is None:
            self.say("can't find you in the scene")
            return
        enemies = [t for t in found if t.get("side") == "Enemies"]
        allies = [t for t in found if t.get("side") == "Allies"]
        counts = [c for c in self.counters() if not c.startswith("ammunition")]   # the arena's own
        if not enemies and not allies:
            self.say(", ".join(counts) or "no fight here")
            return
        def middle(group):
            """Where most of a group is: what a sighted player sees as "the line"."""
            x = sum(t["x"] for t in group) / len(group)
            y = sum(t["y"] for t in group) / len(group)
            d, a = relative(player, x, y)
            return "%s, %s" % (describe_distance(d), describe_angle(a))

        parts = []
        if allies:
            parts.append("%d with you, most of them %s" % (len(allies), middle(allies)))
        else:
            parts.append("nobody with you")
        if enemies:
            parts.append("%d against, most of them %s" % (len(enemies), middle(enemies)))
        else:
            parts.append("no enemies standing")
        self.say(". ".join(parts + counts))

    def repeat_orders(self):
        """M: the order panel's rows again (they're read once when it opens)."""
        rows = self.orders()
        self.say("Orders: " + ", ".join(rows) if rows else "no order list open. Press 1, 2, 3 or 0 first")

    def nearest_enemy(self):
        """N: the nearest enemy, how far and which way."""
        player, found = self._read_all()
        if player is None:
            self.say("can't find you in the scene")
            return
        enemies = [(relative(player, t["x"], t["y"]), t) for t in found if t.get("side") == "Enemies"]
        if not enemies:
            self.say("no enemies")
            return
        (d, a), t = min(enemies, key=lambda e: e[0][0])
        self.say("%s, %s, %s" % (t["name"], describe_distance(d), describe_angle(a)))

    def step(self, key):
        """Walk one of two lines through the player: ahead/behind (O further ahead,
        L further back) or left/right (K further left, semicolon further right).
        Read fresh every press, stepping from the thing we're on."""
        axis = "ahead" if key in (keys.KEY_O, keys.KEY_L) else "side"
        sign = 1 if key in (keys.KEY_O, keys.SEMICOLON) else -1
        player, found = self._read()
        if player is None:
            return
        rows = []
        for t in found:
            d, a = relative(player, t["x"], t["y"])
            q = quarter(a)
            if axis == "ahead" and q in (keys.KEY_O, keys.KEY_L):
                rows.append((d if q == keys.KEY_O else -d, t["key"], t["name"]))
            elif axis == "side" and q in (keys.SEMICOLON, keys.KEY_K):
                rows.append((d if q == keys.SEMICOLON else -d, t["key"], t["name"]))
        rows.sort()
        keys_ = [k for _, k, _ in rows]
        here = self.current[0] if self.current and self.direction == axis else None
        if here in keys_:
            i = keys_.index(here) + sign
        elif sign > 0:      # start at the nearest on the side pressed
            i = next((n for n, r in enumerate(rows) if r[0] >= 0), len(rows))
        else:
            i = max((n for n, r in enumerate(rows) if r[0] < 0), default=-1)
        side = SIDE_WORDS[axis, sign]
        if not 0 <= i < len(rows):
            further = "further " if here in keys_ else ""
            what = "" if self.category == 0 else CATEGORIES[self.category].lower() + " "
            self.say("no %s%s%s" % (what, further, side) if what else "nothing %s%s" % (further, side))
            return
        signed, thing, name = rows[i]
        self.direction, self.current = axis, (thing, name)
        where = SIDE_WORDS[axis, 1 if signed >= 0 else -1]
        self.say("%s, %s %s" % (name, describe_distance(abs(signed)), where)
                 if abs(signed) >= 1.5 else "%s, right here" % name)

    def snap(self, side):
        """Turn to the next thing round on one side (1 left, -1 right): the smallest turn
        past SNAP_AHEAD degrees, so presses sweep round in order (user's choice,
        2026-10-10). What's already in front is skipped; behind counts."""
        player, found = self._read()
        if player is None:
            return
        best = None
        for t in found:
            d, a = relative(player, t["x"], t["y"])
            if a * side > SNAP_AHEAD and d >= 0.5 and (best is None or abs(a) < abs(best[1])):
                best = (d, a, t)
        if best is None:
            what = "" if self.category == 0 else CATEGORIES[self.category].lower()
            self.say("no %s to the %s" % (what or "thing", "left" if side > 0 else "right"))
            return
        d, a, t = best
        self.direction, self.current = None, (t["key"], t["name"])
        self.turner.turn(a, words=lambda: "%s, %s" % (t["name"], describe_distance(d)))

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

    def toggle_tracking(self):
        if self.current is None:
            self.say("nothing chosen. Use K, L, semicolon or O first")
        elif self.tracked and self.tracked[0] == self.current[0]:
            self.tracked = None
            self.say("tracking off")
        else:
            self.tracked = self.current
            self.say("tracking " + self.current[1])

    def lost(self):
        """Called by the ping's thread when the tracked thing is gone."""
        if self.tracked:
            name, self.tracked = self.tracked[1], None
            self.say("%s is gone. Tracking off" % name)

    def position(self, reader, thing_key):
        """(x, y, z) of one thing, read on its own (cheap enough for 20 times a second),
        or None if it's gone. A thing's number is its slot: chunk no // 16, place no % 16."""
        kind, no = thing_key
        mission = walls.mission_address(reader, self.profile)
        if kind == "agent":
            header, size, pos = mission + 0x20, walls.AGENT_SIZE, walls.AGENT_POS
        else:
            header, size, pos = mission + OBJECTS + 0x1c, OBJECT_SIZE, OBJ_POS
        begin, end = struct.unpack("<II", reader.read(header, 8))
        if not begin or no // 16 >= (end - begin) // 4:
            return None
        thing = reader.u32(begin + no // 16 * 4) + no % 16 * size
        valid, number = struct.unpack("<ii", reader.read(thing + 4, 8))
        if valid != 1 or number != no:
            return None
        if kind == "agent" and struct.unpack("<i", reader.read(thing + walls.AGENT_STATUS, 4))[0] != 1:
            return None
        return struct.unpack("<3f", reader.read(thing + pos, 12))

    def landmarks(self):
        """(name, x, y) of every visible prop and plant: what walls and trees are."""
        mission = walls.mission_address(self.r, self.profile)
        out = []
        for chunk in self._chunks(mission + OBJECTS + 0x1c):
            try:
                block = self.r.read(chunk, 16 * OBJECT_SIZE)
            except ReadError:
                continue
            for i in range(16):
                o = i * OBJECT_SIZE
                if struct.unpack_from("<i", block, o + 4)[0] != 1:
                    continue
                meta = struct.unpack_from("<i", block, o + OBJ_META)[0]
                if meta not in (PROP, SPAWNED_PROP, PLANT, PASSAGE):
                    continue
                ident = self.r.rgl_string(chunk + o + OBJ_ID)
                bare = ident[4:] if ident.startswith("spr_") else ident
                if meta != PASSAGE and any(bare.startswith(w) or ("_" + w) in bare for w in INVISIBLE):
                    continue
                x, y = struct.unpack_from("<2f", block, o + OBJ_POS)
                if meta == PASSAGE:     # no id text: named by its door ("Door to the castle")
                    variation = struct.unpack_from("<i", block, o + OBJ_VARIATION)[0]
                    out.append((self.passage_name(variation) or "door", x, y))
                else:
                    out.append((prop_name(ident), x, y))
        return out

    def name_boxes(self, boxes):
        """A name for each solid shape's box: the prop or plant standing inside it,
        nearest its middle; None when there's none (a plain wall, a rock)."""
        marks = self.landmarks()
        names = []
        for x0, y0, _, x1, y1, _ in boxes:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            inside = [(abs(x - cx) + abs(y - cy), n) for n, x, y in marks
                      if x0 - 0.5 <= x <= x1 + 0.5 and y0 - 0.5 <= y <= y1 + 0.5]
            names.append(min(inside)[1] if inside else None)
        return names

    def nearby_usable(self, reach):
        """The nearest thing you could use (person, horse, item, exit) within reach:
        (key, words, distance, angle, category) or None. For the "close enough" setting."""
        player, found = self._read_all()
        if player is None:
            return None
        best = None
        for t in found:
            if t["category"] not in ("People", "Animals", "Items", "Exits"):
                continue
            if t.get("side"):
                continue        # in a fight nobody can be talked to, friend or enemy
            d, a = relative(player, t["x"], t["y"])
            limit = reach[t["category"]] if isinstance(reach, dict) else reach
            if d <= limit and (best is None or d < best[2]):
                verb = {"People": "Talk to ", "Animals": "Mount: ", "Items": "Pick up "}.get(t["category"], "")
                best = (t["key"], verb + t["name"], d, a, t["category"])
        return best

    def agent_name(self, no):
        """(name, is_horse) for agent number `no`, or None: for the game's prompts."""
        mission = walls.mission_address(self.r, self.profile)
        chunks = self._chunks(mission + 0x20)
        if not 0 <= no // 16 < len(chunks):
            return None
        h = self.r.read(chunks[no // 16] + no % 16 * walls.AGENT_SIZE, AGENT_HEAD)
        if struct.unpack_from("<i", h, 4)[0] != 1:
            return None
        if struct.unpack_from("<i", h, walls.AGENT_TYPE)[0] == 1:
            return self.item_name(struct.unpack_from("<i", h, AGENT_HORSE_ITEM)[0]) or "horse", True
        troop = struct.unpack_from("<i", h, AGENT_TROOP)[0]
        if troop not in self.troop_names:
            self.troop_names[troop] = self._troop_name(troop)
        return self.troop_names[troop], False

    def agent_side(self, no):
        """ "Enemies", "Allies" or None for agent number `no`: so a fight's prompts don't
        offer to talk to an enemy."""
        mission = walls.mission_address(self.r, self.profile)
        chunks = self._chunks(mission + 0x20)
        if not 0 <= no // 16 < len(chunks):
            return None
        mine = battle.NO_TEAM
        for chunk in chunks:
            for i in range(16):
                try:
                    h = self.r.read(chunk + i * walls.AGENT_SIZE, 0x38)
                except ReadError:
                    continue
                kind, _, status, flags = struct.unpack_from("<iiiI", h, walls.AGENT_TYPE)
                if struct.unpack_from("<i", h, 4)[0] == 1 and kind == battle.HUMAN and flags & 1:
                    mine = self.r.i32(chunk + i * walls.AGENT_SIZE + battle.AGENT_TEAM)
        theirs = self.r.i32(chunks[no // 16] + no % 16 * walls.AGENT_SIZE + battle.AGENT_TEAM)
        return battle.side(mine, theirs)

    def object_name(self, no):
        """The name the scanner gave mission object `no`, if it has read it."""
        known = self.object_names.get(no)
        return known[0] if known else None

    def where(self):
        if self.current is None:
            self.say("nothing chosen. Use K, L, semicolon or O first")
            return
        self.say(self._where_words(*self.current))
