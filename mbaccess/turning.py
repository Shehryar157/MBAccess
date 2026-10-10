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
# Windows' timer ticks every 15.6 ms by default, so sleep(0.01) really slept ~16 ms and the
# arrow-key spin stuttered. Asking for 1 ms makes short sleeps (and so turning) smooth.
ctypes.WinDLL("winmm").timeBeginPeriod(1)
MOUSEEVENTF_MOVE = 0x1
KEYEVENTF_SCANCODE, KEYEVENTF_KEYUP = 0x8, 0x2
SCAN_A, SCAN_D = 0x1E, 0x20        # DirectInput games read scan codes, not key codes

TOLERANCE = 2.0         # degrees
MAX_NUDGE = 4000        # mouse steps per correction: a whole 45-degree turn (~700) goes at once
BURST = 120             # ... but sent as small moves: one 675-step move turned the WRONG way
BURST_GAP = 0.004       # seconds between them (2026-10-10)
HORSE_TIMEOUT = 4.0     # seconds holding A or D before giving up
SPIN_SPEED = 90.0       # degrees a second while Left or Right arrow is held (on foot)
SPIN_TICK = 0.01
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
        self.game = game
        self.profile = game.profile
        self.say = say
        self.steps_per_degree = 10.0    # camera, on foot: ~600 steps for 59 degrees (2026-10-10); learned while turning
        self.sign = 1                   # flips if moving the mouse right turns us left
        self.busy = False
        self.horse_overshoot = 15.0     # degrees the horse swings on after letting go (learned)
        self.hwnd = None

    def center_pointer(self):
        """Put the mouse pointer in the middle of the game window. Windowed Warband
        only feels mouse movement while the pointer is over it; it recentres the
        pointer each frame, but a pointer that escaped (2026-10-10: one big move threw
        it to the screen's edge) stays out, and every turn after that did nothing."""
        from ctypes import wintypes
        from . import process
        if not self.hwnd or not _user32.IsWindow(self.hwnd):
            self.hwnd = process.find_window(self.game.pid)
        if not self.hwnd:
            return
        rect, pt = wintypes.RECT(), wintypes.POINT()
        _user32.GetClientRect(self.hwnd, ctypes.byref(rect))
        pt.x, pt.y = rect.right // 2, rect.bottom // 2
        _user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        _user32.SetCursorPos(pt.x, pt.y)

    def start_spinning(self, held, active, left_key, right_key, speed=lambda: SPIN_SPEED):
        """Left / Right arrow held on foot: turn on the spot, as a sighted player does by moving the
        mouse. held(vk) says if a key is down; active() if we're walking in a scene;
        speed() the degrees a second (the Accessibility tab's Turn speed)."""
        def run():
            r = Reader(self.game)       # the spin thread's own reader
            spinning, mounted, checked = False, False, 0.0
            owed, last = 0.0, time.perf_counter()     # mouse steps not yet sent
            while True:
                time.sleep(SPIN_TICK)
                now = time.perf_counter()
                elapsed, last = min(now - last, 0.05), now
                try:
                    if not active() or self.busy:
                        spinning = False
                        continue
                    left, right = held(left_key), held(right_key)
                    if left == right:
                        owed = 0.0
                        if spinning:
                            spinning = False
                            self.say(self.facing_words())
                        continue
                    if now - checked > 0.25:        # mounted? (horses turn with A/D)
                        p = walls.find_player(r, walls.mission_address(r, self.profile), self.profile)
                        mounted, checked = bool(p and p[4]), now
                    if mounted:
                        continue
                    if not spinning:
                        self.center_pointer()
                    spinning = True
                    # Turn by the time that really passed, so the speed is right whatever
                    # the tick; the fraction of a step left over is kept for next time.
                    owed += speed() * elapsed * self.steps_per_degree * self.sign * (-1 if left else 1)
                    whole = int(owed)
                    owed -= whole
                    if whole:
                        _user32.mouse_event(MOUSEEVENTF_MOVE, whole, 0, 0, 0)
                except (ReadError, OSError, TypeError):
                    spinning = False
        threading.Thread(target=run, daemon=True, name="spin").start()

    def _player(self):
        return walls.find_player(self.r, walls.mission_address(self.r, self.profile), self.profile)

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
        self.center_pointer()
        stuck = 0
        for _ in range(40):
            before = math.degrees(self._player()[3])
            error = wrap(target - before)
            if abs(error) <= TOLERANCE:
                return True
            # Facing grows anticlockwise (left); moving the mouse right turns right.
            nudge = int(max(-MAX_NUDGE, min(MAX_NUDGE, -error * self.steps_per_degree * self.sign)))
            self._burst(nudge or (1 if error < 0 else -1))
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

    def _burst(self, steps):
        """Move the mouse `steps` sideways as quick small moves, like a real mouse."""
        while steps:
            part = max(-BURST, min(BURST, steps))
            _user32.mouse_event(MOUSEEVENTF_MOVE, part, 0, 0, 0)
            steps -= part
            if steps:
                time.sleep(BURST_GAP)

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
        """Hold A or D until the horse has turned (it turns standing still too, the user
        says). The horse swings on after the key is let go, so let go early by the
        swing learned last time."""
        scan = SCAN_A if left else SCAN_D
        _user32.keybd_event(0, scan, KEYEVENTF_SCANCODE, 0)
        turned = False
        try:
            start = time.time()
            while time.time() - start < HORSE_TIMEOUT:
                facing = math.degrees(self._player()[3])
                error = wrap(target - facing)
                if abs(error) <= self.horse_overshoot or (error > 0) != left:
                    turned = True
                    break
                time.sleep(0.005)
        finally:
            _user32.keybd_event(0, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)
        if not turned:
            self.say("the horse didn't turn")
            return False
        released = math.degrees(self._player()[3])
        time.sleep(0.6)
        swing = abs(wrap(math.degrees(self._player()[3]) - released))
        self.horse_overshoot = max(2.0, min(40.0, 0.5 * self.horse_overshoot + 0.5 * swing))
        return True
