"""Turn the player by a set angle in a scene (Shift+A / Shift+D: 45 degrees).

On foot the mouse turns you, so we nudge the mouse sideways and read the facing back
from memory until it's within TOLERANCE: a feedback loop, like a thermostat. It learns
how many mouse steps make a degree as it goes, so later turns settle faster.
On horseback the mouse only moves the camera; A and D steer the horse, so we hold one
until the horse has turned far enough.
"""
import ctypes
import math
import threading
import time

from . import walls
from .mem import Reader, ReadError

_user32 = ctypes.WinDLL("user32")
MOUSEEVENTF_MOVE = 0x1
KEYEVENTF_SCANCODE, KEYEVENTF_KEYUP = 0x8, 0x2
SCAN_A, SCAN_D = 0x1E, 0x20        # DirectInput games read scan codes, not key codes

TOLERANCE = 2.0         # degrees
MAX_NUDGE = 300         # mouse steps in one move
HORSE_TIMEOUT = 4.0     # seconds holding A or D before giving up
COMPASS = ("east", "north-east", "north", "north-west",
           "west", "south-west", "south", "south-east")


def wrap(degrees):
    return (degrees + 180) % 360 - 180


def compass(facing_radians):
    """The way the player faces, in 8 directions (+y north, as on the world map)."""
    angle = math.degrees(facing_radians + walls.FORWARD) % 360
    return COMPASS[int((angle + 22.5) // 45) % 8]


class Turner:
    def __init__(self, game, say):
        self.r = Reader(game)       # our own: turning runs on its own thread
        self.profile = game.profile
        self.say = say
        self.steps_per_degree = 5.0     # a first guess; learned while turning
        self.sign = 1                   # flips if moving the mouse right turns us left
        self.busy = False

    def _player(self):
        return walls.find_player(self.r, walls.mission_address(self.r, self.profile))

    def facing_words(self):
        p = self._player()
        return "facing " + compass(p[3]) if p else "can't find you"

    def turn(self, degrees):
        """Positive = left. Runs in the background so the mod stays responsive."""
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._turn, args=(degrees,), daemon=True, name="turn").start()

    def _turn(self, degrees):
        try:
            p = self._player()
            if p is None:
                return
            target = math.degrees(p[3]) + degrees
            ok = self._steer_horse(target, degrees > 0) if p[4] else self._mouse(target)
            if ok:
                self.say(self.facing_words())
        except (ReadError, OSError):
            pass
        finally:
            self.busy = False

    def _mouse(self, target):
        stuck = 0
        for _ in range(40):
            before = math.degrees(self._player()[3])
            error = wrap(target - before)
            if abs(error) <= TOLERANCE:
                return True
            # Facing grows anticlockwise (left); moving the mouse right turns right.
            nudge = int(max(-MAX_NUDGE, min(MAX_NUDGE, -error * self.steps_per_degree * self.sign)))
            _user32.mouse_event(MOUSEEVENTF_MOVE, nudge or (1 if error < 0 else -1), 0, 0, 0)
            moved = self._settle(before)
            if abs(moved) < 0.3:
                stuck += 1
                if stuck >= 6:
                    self.say("couldn't turn")
                    return False
                continue
            stuck = 0
            if (moved > 0) != (error > 0):
                self.sign = -self.sign          # we turned the wrong way: flip and retry
                continue
            measured = abs(nudge) / abs(moved)
            self.steps_per_degree = 0.5 * self.steps_per_degree + 0.5 * measured
        return False

    def _settle(self, before):
        """Degrees turned since `before`, once the game has applied our nudge: watch
        every 5 ms and go on as soon as the facing stops changing (at most 80 ms)."""
        last, still, start = before, 0, time.perf_counter()
        while time.perf_counter() - start < 0.08:
            time.sleep(0.005)
            now = math.degrees(self._player()[3])
            if now != last:
                last, still = now, 0
            elif last != before:
                still += 1
                if still >= 2:      # changed, then held for two looks: settled
                    break
        return wrap(last - before)

    def _steer_horse(self, target, left):
        scan = SCAN_A if left else SCAN_D
        _user32.keybd_event(0, scan, KEYEVENTF_SCANCODE, 0)
        try:
            start = time.time()
            while time.time() - start < HORSE_TIMEOUT:
                error = wrap(target - math.degrees(self._player()[3]))
                # stop a little early: the horse keeps turning briefly after release
                if abs(error) <= TOLERANCE * 2 or (error > 0) != left:
                    return True
                time.sleep(0.005)
        finally:
            _user32.keybd_event(0, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)
        self.say("the horse didn't turn")
        return False
