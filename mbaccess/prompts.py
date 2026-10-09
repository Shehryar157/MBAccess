"""The game's action prompts in a scene ("Talk", "Mount", "Dismount", "Open"...), spoken,
and F on horseback made to dismount the way a sighted player does it.

The prompt isn't text in memory: the game draws it each frame from three numbers in the
scene window (WSE tactical_window order, found 2026-10-10, docs/findings/scenes.md):
- +0x408 use_object_type: -1 nothing, 2 an agent (horse: "Mount"; person: "Talk",
  assumed), 3 Dismount (only while looking down at your own horse). Others not seen yet.
- +0x40c use_object_no: the agent or mission object's number.
- +0x414 use_object_in_range: 1 when close enough to press F.

Dismounting: Warband shows "Dismount" only when you look straight down at your horse
(Steam forum; verified: 600 mouse steps down gave type 3, then F dismounted). F alone,
looking ahead, does nothing. So on F, mounted and looking at nothing, we tilt the
camera down until type 3 appears, press F, and tilt back.
"""
import ctypes
import struct
import threading
import time

from . import walls
from .mem import Reader, ReadError

USE = 0x408
NOTHING, AGENT, DISMOUNT = -1, 2, 3
SCENE_WINDOW = 10

_user32 = ctypes.WinDLL("user32")
MOUSEEVENTF_MOVE = 0x1
KEYEVENTF_SCANCODE, KEYEVENTF_KEYUP = 0x8, 0x2
SCAN_F = 0x21
LOOK_STEP, LOOK_LIMIT = 60, 1500     # mouse steps per nudge; give up past this


class Prompts:
    def __init__(self, game, reader, say, scanner):
        self.game, self.r, self.say, self.scanner = game, reader, say, scanner
        self.window_table = game.profile.screen["game_windows"]
        self.last = None
        self.busy = False           # dismounting: don't announce our own look-down

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
        # Not seen yet (doors, items, chests): name it from the scanner and log the
        # number, so the next session can learn its verb.
        print("prompt type", kind, "number", no)
        name = self.scanner.object_name(no)
        return name or "something to use"

    def poll(self):
        """Each main-loop tick while walking in a scene: speak a new prompt."""
        if self.busy:
            return
        try:
            kind, no, in_range = self._use()
        except ReadError:
            return
        now = (kind, no, in_range)
        if now == self.last:
            return
        self.last = now
        if kind == NOTHING or not (in_range or kind == DISMOUNT):
            return
        words = self.describe(kind, no)
        if words:
            self.say(words)

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
        if kind != NOTHING or not player or not player[4]:
            return
        self.busy = True
        threading.Thread(target=self._dismount, daemon=True, name="dismount").start()

    def _dismount(self):
        r = Reader(self.game)       # our own: this runs on its own thread
        moved = 0
        try:
            time.sleep(0.1)         # let the game handle the player's own F first
            while moved < LOOK_LIMIT:
                if self._use(r)[0] == DISMOUNT:
                    _user32.keybd_event(0, SCAN_F, KEYEVENTF_SCANCODE, 0)
                    time.sleep(0.1)
                    _user32.keybd_event(0, SCAN_F, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)
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
