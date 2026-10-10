"""The game's action prompts in a scene ("Talk", "Mount", "Dismount", "Open"...), spoken,
and F on horseback made to dismount the way a sighted player does it.

The prompt isn't text in memory: the game draws it each frame from three numbers in the
scene window (WSE tactical_window order, found 2026-10-10, docs/findings/scenes.md):
- +0x408 use_object_type: -1 nothing, 1 a mission object (ANY prop aimed at: a fence and
  a feeding trough showed it, in range at ~1.9 m), 2 an agent (horse: "Mount"; person: "Talk",
  assumed), 3 Dismount (only while looking down at your own horse). Others not seen yet.
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
NOTHING, OBJECT, AGENT, DISMOUNT = -1, 1, 2, 3
PASSAGE = 6     # a door to another scene (seen 2026-10-10 at "Door to the castle")
SCENE_WINDOW = 10

_user32 = ctypes.WinDLL("user32")
MOUSEEVENTF_MOVE = 0x1
KEYEVENTF_SCANCODE, KEYEVENTF_KEYUP = 0x8, 0x2
SCAN_F = 0x21
LOOK_STEP, LOOK_LIMIT = 60, 1500     # mouse steps per nudge; give up past this


# Metres from you to a thing's centre where the game lets you use it (tools/reach_test.py,
# 2026-10-10): a horse 1.3, a scene object about 1.9. People not measured: as a horse.
REACH = {"People": 1.3, "Animals": 1.3, "Items": 1.9, "Exits": 1.9}
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
        if kind == OBJECT:
            # The game aims at any prop (fences too), so speak only the usable kinds.
            known = self.scanner.object_names.get(no)
            if not known or known[1] not in ("Items", "Exits"):
                return None
            return ("Pick up " if known[1] == "Items" else "") + known[0]
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
            player = walls.find_player(self.r, walls.mission_address(self.r, self.game.profile))
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
            self.busy = True
            threading.Thread(target=self._aim_and_use, args=(self.near,), daemon=True,
                             name="aim").start()

    def _press_f(self):
        _user32.keybd_event(0, SCAN_F, KEYEVENTF_SCANCODE, 0)
        time.sleep(0.1)
        _user32.keybd_event(0, SCAN_F, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)

    def _aim_and_use(self, near):
        r = Reader(self.game)
        moved = 0
        try:
            p = walls.find_player(r, walls.mission_address(r, self.game.profile))
            self.turner._mouse(math.degrees(p[3]) + near[3])     # face it
            time.sleep(0.1)
            while moved <= 900:             # items on the ground need a look down
                kind, _, in_range = self._use(r)
                if kind not in (NOTHING, DISMOUNT) and in_range:
                    self._press_f()
                    break
                _user32.mouse_event(MOUSEEVENTF_MOVE, 0, LOOK_STEP, 0, 0)
                moved += LOOK_STEP
                time.sleep(0.03)
            else:
                self.say("can't reach it from here")
        except (ReadError, TypeError):
            pass
        finally:
            if moved:
                time.sleep(0.2)
                _user32.mouse_event(MOUSEEVENTF_MOVE, 0, -moved, 0, 0)
            self.last = None
            self.busy = False

    def _dismount(self):
        r = Reader(self.game)       # our own: this runs on its own thread
        moved = 0
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
                _user32.mouse_event(MOUSEEVENTF_MOVE, 0, -moved, 0, 0)     # look ahead again
            self.last = None
            self.busy = False
