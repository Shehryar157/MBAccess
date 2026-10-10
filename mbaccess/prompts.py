"""The game's action prompts in a scene ("Talk", "Mount", "Dismount", "Open"...), spoken,
and F on horseback made to dismount the way a sighted player does it.

The prompt isn't text in memory: the game draws it each frame from three numbers in the
scene window (WSE tactical_window order, found 2026-10-10, docs/findings/scenes.md):
- +0x408 use_object_type: -1 nothing, 1 a person ("Talk", in range within 3.2 m; VERIFIED
  by screenshot; earlier notes also saw it on props, unconfirmed), 2 a horse ("Mount"),
  3 Dismount (only while looking down at your own horse), 6 a door to another scene.
- +0x40c use_object_no: the agent or mission object's number.
- +0x414 use_object_in_range: 1 when close enough to press F.

Dismounting: Warband shows "Dismount" only when you look straight down at your horse
(Steam forum; verified: 600 mouse steps down gave type 3, then F dismounted). F alone,
looking ahead, does nothing. So on F, mounted and looking at nothing, we tilt the
camera down until type 3 appears, press F, and tilt back.
"""
import ctypes
import math
import struct
import threading
import time

from . import walls
from .mem import Reader, ReadError

USE = 0x408
# 1 = a person to talk to, number = agent (VERIFIED 2026-10-10: screenshot "Guild Master /
# Talk" with type 1, no 12 = his agent). 2 = a horse to mount (agent number). 3 dismount.
NOTHING, PERSON, AGENT, DISMOUNT = -1, 1, 2, 3
PASSAGE = 6     # a door to another scene (seen 2026-10-10 at "Door to the castle")
# An item on the ground; number = its mission object number (VERIFIED 2026-10-10: a dropped
# crossbow and bolts in Jelkala, objects 334/335, offered from 1.2 m looking ~35 degrees down,
# on foot only: mounted, looking down only ever offers Dismount).
ITEM = 7
SCENE_WINDOW = 10

_user32 = ctypes.WinDLL("user32")
MOUSEEVENTF_MOVE = 0x1
KEYEVENTF_SCANCODE, KEYEVENTF_KEYUP = 0x8, 0x2
SCAN_F = 0x21
LOOK_STEP, LOOK_LIMIT = 60, 1500     # mouse steps per nudge; give up past this


# Metres from you to a thing's centre where the game lets you use it (tools/reach_test.py,
# 2026-10-10): a horse 1.3, a scene object about 1.9, a person 3.2 (Guild Master; "Talk"
# shows from 5 m but only works within 3.2).
REACH = {"People": 3.0, "Animals": 1.3, "Items": 1.9, "Exits": 1.9}
NEARBY_EVERY = 0.25     # seconds between "what's close enough" checks


class Prompts:
    def __init__(self, game, reader, say, scanner, mode=lambda: "Facing it",
                 cue=lambda angle=0.0: None, turner=None):
        """mode(): the Accessibility setting, "Facing it" (the game's own prompt) or
        "Close enough" (anything usable within REACH, whichever way you face).
        cue(angle): play the hammer-on "you can use this" sound from that direction."""
        self.game, self.r, self.say, self.scanner = game, reader, say, scanner
        self.mode, self.cue, self.turner = mode, cue, turner
        self.window_table = game.profile.screen["game_windows"]
        self.last = None
        self.busy = False           # dismounting or aiming: don't announce our own moves
        self.near = None            # (key, words, distance, angle) in "close enough" mode
        self.near_checked = 0.0

    def _use(self, reader=None):
        r = reader or self.r
        window = r.ptr(self.window_table + 4 * SCENE_WINDOW)
        kind, no, _, in_range = struct.unpack("<4i", r.read(window + USE, 16))
        return kind, no, in_range

    def describe(self, kind, no):
        if kind == DISMOUNT:
            return "Dismount"
        if kind == AGENT:
            who = self.scanner.agent_name(no)
            if who is None:
                return None
            name, horse = who
            return "Mount: " + name if horse else "Talk to " + name
        if kind == PERSON:
            who = self.scanner.agent_name(no)
            if who is not None:
                if not who[1] and self.scanner.agent_side(no) == "Enemies":
                    return None     # in a fight the game shows an enemy's name, not "Talk"
                return ("Mount: " if who[1] else "Talk to ") + who[0]
            # Not a living person: older notes saw type 1 on props (a fence); speak only usable kinds.
            known = self.scanner.object_names.get(no)
            if not known or known[1] not in ("Items", "Exits"):
                return None
            return ("Pick up " if known[1] == "Items" else "") + known[0]
        if kind == ITEM:
            known = self.scanner.object_names.get(no)
            if known is None:           # dropped since the scanner last looked
                self.scanner._read_all()
                known = self.scanner.object_names.get(no)
            return "Pick up " + (known[0] if known else "item")
        if kind == PASSAGE:
            # Assumed: no = the passage's mission object number, as for type 1.
            known = self.scanner.object_names.get(no)
            return known[0] if known else "door"
        print("prompt type", kind, "number", no)     # unseen kinds: learn from the log
        return None

    def poll(self):
        """Each main-loop tick while walking in a scene: speak a new prompt."""
        if self.busy:
            return
        try:
            kind, no, in_range = self._use()
        except ReadError:
            return
        close_mode = self.mode() == "Close enough"
        if close_mode:
            self._poll_nearby()
        now = (kind, no, in_range)
        if now == self.last:
            return
        self.last = now
        if kind == NOTHING or not (in_range or kind == DISMOUNT):
            return
        if close_mode and kind != DISMOUNT:
            return              # already announced when it came close enough
        words = self.describe(kind, no)
        if words:
            if kind != DISMOUNT:
                self.cue(0.0)   # the game's prompt is for what's straight ahead
            self.say(words)

    def _poll_nearby(self):
        if time.time() - self.near_checked < NEARBY_EVERY:
            return
        self.near_checked = time.time()
        near = self.scanner.nearby_usable(REACH)
        if (near and near[0]) == (self.near and self.near[0]):
            self.near = near
            return
        self.near = near
        if near:
            self.cue(near[3])
            self.say(near[1])

    def on_action_key(self):
        """F was pressed (and passed to the game). If that does nothing because the
        player is mounted and looking at nothing, dismount as a sighted player would."""
        if self.busy:
            return
        try:
            kind, _, _ = self._use()
            player = walls.find_player(self.r, walls.mission_address(self.r, self.game.profile), self.game.profile)
        except ReadError:
            return
        if kind != NOTHING or not player:
            return
        if player[4]:
            self.busy = True
            threading.Thread(target=self._dismount, daemon=True, name="dismount").start()
        elif self.mode() == "Close enough" and self.near and self.turner:
            # Close enough but not facing it: turn to it, look down if the game
            # needs that, and press F, as a sighted player aims with the mouse.
            self.near = self.scanner.nearby_usable(REACH) or self.near   # where it is NOW
            self.busy = True
            threading.Thread(target=self._aim_and_use, args=(self.near,), daemon=True,
                             name="aim").start()

    def _press_f(self):
        _user32.keybd_event(0, SCAN_F, KEYEVENTF_SCANCODE, 0)
        time.sleep(0.1)
        _user32.keybd_event(0, SCAN_F, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)

    def _offered(self, r, want, wait):
        """Does the game offer the thing we turned to, within `wait` seconds? Only that
        thing: an item lying under a horse first offers the horse, and F then mounts it
        (happened in a test, 2026-10-10)."""
        until = time.perf_counter() + wait
        while True:
            kind, no, in_range = self._use(r)
            if in_range and no == want[1] and (kind in (PERSON, AGENT)) == (want[0] == "agent") \
                    and kind not in (NOTHING, DISMOUNT):
                return True
            if time.perf_counter() >= until:
                return False
            time.sleep(0.02)

    def _angle_now(self, r, want, angle):
        """The angle to turn by to face the thing. A person or horse may have walked on
        since we last looked, so theirs is worked out again from where they stand now."""
        mission = walls.mission_address(r, self.game.profile)
        player = walls.find_player(r, mission, self.game.profile)
        if want[0] == "agent":
            begin, end = struct.unpack("<II", r.read(mission + 0x20, 8))
            chunk = r.ptr(begin + 4 * (want[1] // 16))
            x, y = struct.unpack("<2f", r.read(chunk + want[1] % 16 * walls.AGENT_SIZE + walls.AGENT_POS, 8))
            angle = math.degrees(math.atan2(y - player[1], x - player[0]) - player[3] - walls.FORWARD)
        return math.degrees(player[3]) + angle

    def _aim_and_use(self, near):
        r = Reader(self.game)
        moved = 0
        pitch = walls.camera_pitch(r, self.game.profile)
        want = near[0]                      # ("agent", no) or ("object", no)
        started = time.perf_counter()
        try:
            found = False
            for attempt in range(3):        # a walking villager can take a second aim
                self.turner._mouse(self._angle_now(r, want, near[3] if attempt == 0 else 0.0))
                found = self._offered(r, want, 0.15)
                if found or want[0] != "agent":
                    break
            # Only an item on the ground needs a look down; a person, horse or door doesn't.
            while not found and near[4] == "Items" and moved <= 900:
                _user32.mouse_event(MOUSEEVENTF_MOVE, 0, LOOK_STEP, 0, 0)
                moved += LOOK_STEP
                found = self._offered(r, want, 0.03)
            # For the log: the user found this slow (2026-10-10); how long does it take?
            print(f"aim at {near[1]!r}: {time.perf_counter() - started:.2f} s, "
                  f"{attempt + 1} turns, looked down {moved}, offered {found}")
            if found:
                self._press_f()
            else:
                self.say("can't reach it from here")
        except (ReadError, TypeError):
            pass
        finally:
            if moved:
                time.sleep(0.2)
                self._look_up(r, pitch)
            self.last = None
            self.busy = False

    def _look_up(self, r, pitch):
        """Back to the up/down angle we started at. By watching the camera, not by
        counting steps: the camera stops at its lowest, so steps past that never happened,
        and undoing them all pointed the camera at the sky (2026-10-10). Small moves: one
        big jump can throw the pointer out of the window and the game stops feeling it."""
        for _ in range(150):
            error = walls.camera_pitch(r, self.game.profile) - pitch
            if abs(error) < 0.03:
                return
            _user32.mouse_event(MOUSEEVENTF_MOVE, 0, -20 if error > 0 else 20, 0, 0)
            time.sleep(0.015)

    def _dismount(self):
        r = Reader(self.game)       # our own: this runs on its own thread
        moved = 0
        pitch = walls.camera_pitch(r, self.game.profile)
        if self.turner:
            self.turner.center_pointer()
        try:
            time.sleep(0.1)         # let the game handle the player's own F first
            while moved < LOOK_LIMIT:
                if self._use(r)[0] == DISMOUNT:
                    self._press_f()
                    time.sleep(0.2)
                    break
                _user32.mouse_event(MOUSEEVENTF_MOVE, 0, LOOK_STEP, 0, 0)
                moved += LOOK_STEP
                time.sleep(0.03)
            else:
                self.say("couldn't dismount here")
        except ReadError:
            pass
        finally:
            if moved:
                self._look_up(r, pitch)     # look ahead again
            self.last = None
            self.busy = False
