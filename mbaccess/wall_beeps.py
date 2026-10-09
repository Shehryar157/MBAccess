"""Wall beeps in scenes: a soft tone when you move closer to a wall.

Eight directions around the player, one per way the movement keys go (W, W+D, D,
...). Each remembers its last distance step; when you get a step closer, it beeps
once at that step's pitch. Standing still or moving away is silent.

Sounds are made in code (numpy) and played through OpenAL with HRTF (sound3d.py),
each from a fixed spot around your head:
- ahead, right, behind, left: the plain round sine; behind is a double blip.
- front diagonals: a shorter, brighter blip (overtones give HRTF something to shape;
  a pure sine is hard to place in front of or behind you).
- back diagonals: a hollow, reedy double blip, so they're never mistaken for the
  front diagonals even when front/back placement is fuzzy.
"""
import math
import threading
import time

import numpy as np

from . import walls
from .mem import Reader, ReadError
from .sound3d import Sound3D

RATE = 44100
TICK = 0.05                     # seconds between distance checks
REACH = {False: 4.0, True: 6.0}  # metres where beeping starts: on foot, on horseback
STEPS = 4                       # distance steps; each closer step beeps a little higher
BASE = 440                      # Hz, the pitch of the farthest step
HYSTERESIS = 0.3                # metres past a step boundary before it counts as left
SCENE_WINDOW = 10
# Where the diagonals sound, degrees from straight ahead. 45 is the true diagonal;
# raise it to push them toward your ears, lower it to pull them toward front/back.
DIAGONAL_ANGLE = 45
DIAGONAL_GAIN = 0.8             # diagonals a little softer than the main four

# Horse drone: a low hum only while the horse slows down. It slides from DRONE_HZ (the
# speed when slowing began) down to LOWEST_PITCH times that at a halt, whatever the
# starting speed, so every slowdown is a full, clear slide. User asked: only when
# slowing, and "more slopy" (2026-10-10; following absolute speed sounded constant).
DRONE_HZ = 220                  # starting pitch (exact cycles in a 1 s loop: no click)
DRONE_GAIN = 0.12               # quiet: under the beeps and the game
HALT_SPEED = 0.3                # below this the horse counts as stopped
LOWEST_PITCH = 0.35             # about an octave and a half down at the halt
SLOWING = 0.6                   # m/s the quick speed must fall below the slow one
SLOW_HOLD = 0.3                 # seconds the hum lingers after slowing pauses (no flicker)


def _drone():
    """One second of a soft low hum: fundamental plus quiet overtones, loops seamlessly."""
    t = np.arange(RATE) / RATE
    return 0.8 * (np.sin(2 * math.pi * DRONE_HZ * t) + 0.3 * np.sin(2 * math.pi * 2 * DRONE_HZ * t)
                  + 0.1 * np.sin(2 * math.pi * 3 * DRONE_HZ * t)) / 1.4


def _shape(freq, harmonics, length, blips=1, gap=0.04):
    """A beep: harmonics = [(multiple, loudness)], slow 25 ms fades (sharp edges click)."""
    t = np.arange(int(RATE * length)) / RATE
    fade = np.minimum(1, np.minimum(t, t[::-1]) / min(0.025, length / 3))
    one = sum(v * np.sin(2 * math.pi * freq * m * t) for m, v in harmonics)
    one = one / sum(v for _, v in harmonics) * fade
    parts = []
    for _ in range(blips):
        parts += [one, np.zeros(int(RATE * gap))]
    return np.concatenate(parts)


SINE = [(1, 1.0)]
BRIGHT = [(1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15)]         # all overtones: clear, bright
HOLLOW = [(1, 1.0), (3, 0.45), (5, 0.25), (7, 0.12)]        # odd ones only: reedy, clarinet-like

# zone -> (angle in degrees clockwise from ahead, harmonics, length, blips, gain)
VOICES = {
    "front":        (0, SINE, 0.09, 1, 1.0),
    "front right":  (DIAGONAL_ANGLE, BRIGHT, 0.06, 1, DIAGONAL_GAIN),
    "right":        (90, SINE, 0.09, 1, 1.0),
    "behind right": (180 - DIAGONAL_ANGLE, HOLLOW, 0.05, 2, DIAGONAL_GAIN),
    "behind":       (180, SINE, 0.09, 2, 1.0),
    "behind left":  (180 + DIAGONAL_ANGLE, HOLLOW, 0.05, 2, DIAGONAL_GAIN),
    "left":         (270, SINE, 0.09, 1, 1.0),
    "front left":   (360 - DIAGONAL_ANGLE, BRIGHT, 0.06, 1, DIAGONAL_GAIN),
}


class WallBeeper:
    def __init__(self, game, active, volume=0.35):
        """active(): True while the player is walking around (scene window on top)."""
        self.audio = Sound3D(RATE)
        self.reader = Reader(game)      # our own: the main loop's reader isn't thread-safe
        self.profile = game.profile
        self.active = active
        self.enabled = True
        self.sources, self.sounds = {}, {}      # zone -> source; (zone, step) -> buffer
        for zone, (angle, harmonics, length, blips, gain) in VOICES.items():
            self.sources[zone] = self.audio.source(angle, gain * volume)
            for step in range(STEPS):
                f = BASE * 2 ** (step * 2 / 12)        # each step two semitones up
                self.sounds[zone, step] = self.audio.buffer(0.8 * _shape(f, harmonics, length, blips))
        self.drone_source = self.audio.source(0, 0)
        self.drone_buffer = self.audio.buffer(_drone())
        self.drone_gain = 0.0           # faded up and down a little each tick: no clicks
        self.speed = 0.0                # smoothed, metres per second
        self.trend = 0.0                # smoothed much more: lags behind the speed
        self.last_pos = None            # (x, y, time)
        self.slow_from = None           # speed when the current slowdown began
        self.slowing_at = 0.0           # last time the speed was seen falling
        self.walls = None
        self.scene = None
        self.last_step = {zone: -1 for zone in VOICES}   # -1 = nothing in range
        self.stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="wall beeps").start()

    def _horse_drone(self, player):
        """While the horse slows, hum and slide the pitch down toward the halt."""
        now = time.perf_counter()
        before = self.speed
        if player and self.last_pos:
            x0, y0, t0 = self.last_pos
            dt = max(now - t0, 1e-3)
            v = math.hypot(player[0] - x0, player[1] - y0) / dt
            self.speed += 0.3 * (v - self.speed)        # moving average: steady, not jittery
            self.trend += 0.08 * (self.speed - self.trend)
            # slowing = the quick average clearly below the lagging one (jitter cancels out)
            if self.trend - self.speed > SLOWING:
                if self.slow_from is None:
                    self.slow_from = self.trend         # the top of the slide
                self.slowing_at = now
        else:
            self.speed = self.trend = 0.0
        self.last_pos = (player[0], player[1], now) if player else None
        slowing = bool(player and player[4] and self.slow_from
                       and now - self.slowing_at < SLOW_HOLD and self.speed > HALT_SPEED)
        if not slowing and self.drone_gain <= 0:
            self.slow_from = None                       # next slowdown starts a new slide
        target = DRONE_GAIN if slowing else 0.0
        if target and not self.drone_gain:
            self.audio.loop(self.drone_source, self.drone_buffer)
        self.drone_gain += max(-0.02, min(0.02, target - self.drone_gain))    # ~0.3 s fades
        if self.drone_gain <= 0:
            self.drone_gain = 0.0
            self.audio.stop(self.drone_source)
            return
        share = min(1.0, self.speed / self.slow_from) if self.slow_from else 0.0
        pitch = LOWEST_PITCH + (1 - LOWEST_PITCH) * share
        self.audio.set(self.drone_source, gain=self.drone_gain, pitch=pitch)

    def _distances(self):
        """({zone: metres}, on_horse), or None outside a scene."""
        r = self.reader
        mission = walls.mission_address(r, self.profile)
        if not mission:
            return None
        scene = r.u32(mission)
        if scene != self.scene:         # a new scene: read its walls once
            self.walls, self.scene = walls.SceneWalls(r, scene), scene
        player = self.player = walls.find_player(r, mission)
        if player is None:
            return None
        reach = max(REACH.values())
        dist = walls.zone_distances(self.walls, player, reach=reach)
        return walls.corners_only(dist, player[4], reach), player[4]

    def _run(self):
        while not self.stop.is_set():
            self.player = None
            try:
                result = self._distances() if self.enabled and self.active() else None
            except (ReadError, ValueError, OSError):
                result, self.scene = None, None     # scene changing or game closing
            self._horse_drone(self.player if result else None)
            if not result:
                self.last_step = {zone: -1 for zone in VOICES}
            else:
                dist, on_horse = result
                reach = REACH[on_horse]
                for zone in walls.ZONES:
                    d = dist[zone]
                    step = min(STEPS - 1, int((1 - d / reach) * STEPS)) if d < reach else -1
                    if step > self.last_step[zone]:
                        self.audio.play(self.sources[zone], self.sounds[zone, step])
                        self.last_step[zone] = step     # a step closer: say so once
                    elif step < self.last_step[zone]:
                        # farther: remember quietly, but only once clearly past the
                        # boundary, so wobbling on it doesn't beep again and again
                        d2 = d - HYSTERESIS
                        back = min(STEPS - 1, int((1 - d2 / reach) * STEPS)) if d2 < reach else -1
                        self.last_step[zone] = min(self.last_step[zone], max(step, back))
            time.sleep(TICK)
