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
import queue
import threading
import time

import numpy as np

from . import keys, scanner as scanner_mod, walls
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

# Horse drone: a low hum from the moment W is let go on a moving horse until it halts.
# It slides from DRONE_HZ (the speed at the let-go) down to LOWEST_PITCH times that at
# the halt, whatever the starting speed, and only ever downward: one clean slide.
# User asked (2026-10-10): start at the key release, only while slowing, a clean slope.
DRONE_HZ = 220                  # starting pitch (exact cycles in a 1 s loop: no click)
DRONE_GAIN = 0.12               # quiet: under the beeps and the game
HALT_SPEED = 0.3                # below this the horse counts as stopped
LOWEST_PITCH = 0.35             # about an octave and a half down at the halt
FORWARD_KEY = 0x57              # W: holding it keeps the horse going, so no hum


# Tracking ping (Shift+J in the scanner): a mellow "bwip", unlike the wall beeps.
PING_HZ = 620
PING_GAIN = 0.5
PING_BEHIND_PITCH = 0.6     # straight behind: this much of the pitch (ahead half: full)
PING_SLOW, PING_FAST = 0.9, 0.3     # seconds between pings: far away, close up
PING_FAR, PING_NEAR = 30.0, 3.0     # metres where the rate stops changing


def _beacon():
    """The tracking beep: mellow, not bright. A round sine with a touch of its octave,
    a soft 8 ms start, a smooth fade, and a slight upward glide that makes it a "bwip"."""
    length = 0.13
    t = np.arange(int(RATE * length)) / RATE
    glide = 1 + 0.04 * np.minimum(1, t / length)        # rises 4% over the beep
    phase = 2 * math.pi * PING_HZ * np.cumsum(glide) / RATE
    tone = np.sin(phase) + 0.15 * np.sin(2 * phase)
    envelope = np.minimum(1, t / 0.008) * np.exp(-t / 0.06)
    end = np.minimum(1, (length - t) / 0.015)
    out = tone * envelope * end
    return out / np.max(np.abs(out))


NAME_REACH = {False: 1.5, True: 2.5}    # metres: name the thing ahead when this close
NAME_CLEAR = 0.6                        # metres further before the same thing is new again


def _hammer_on():
    """The "you can use this" cue: a classical (nylon string) guitar hammer-on, D4 then
    up a major third to F#4 on the same ringing string.

    Karplus-Strong plucked string: a short burst of soft noise (the finger's pluck)
    circulates in a loop one period long; each pass averages neighbouring samples, so
    the bright overtones die first, as on a real string. The hammer-on shortens the
    loop mid-note without a new pluck: the same vibration, now at the higher pitch."""
    rng = np.random.default_rng(7)          # the same pluck every time
    first, second, switch, length = 293.66, 369.99, 0.075, 0.6
    n1 = int(round(RATE / first))
    pluck = rng.uniform(-1, 1, n1)
    for _ in range(3):                      # soften the burst: a fingertip, not a pick
        pluck = 0.5 * (pluck + np.roll(pluck, 1))
    loop, out, decay = list(pluck), [], 0.996
    total, at = int(RATE * length), int(RATE * switch)
    i = 0
    while len(out) < total:
        if len(out) == at:                  # hammer on: same string, shorter loop
            n2 = int(round(RATE / second))
            old = np.array(loop[i:] + loop[:i])
            loop = list(np.interp(np.linspace(0, len(old) - 1, n2), np.arange(len(old)), old))
            i = 0
        n = len(loop)
        value = decay * 0.5 * (loop[i] + loop[(i + 1) % n])
        out.append(loop[i])
        loop[i] = value
        i = (i + 1) % n
    out = np.array(out)
    body = np.convolve(out, np.ones(6) / 6, mode="same")     # a little wooden warmth
    out = 0.7 * out + 0.3 * body
    out *= np.minimum(1, (len(out) - np.arange(len(out))) / (RATE * 0.05))   # gentle end
    return out / np.max(np.abs(out))


def ping_interval(distance):
    share = min(1.0, max(0.0, (distance - PING_NEAR) / (PING_FAR - PING_NEAR)))
    return PING_FAST + (PING_SLOW - PING_FAST) * share


def ping_pitch(angle):
    """angle: degrees from straight ahead, either side. Lower the further behind."""
    behind = max(0.0, abs(angle) - 90) / 90
    return 1.0 - (1.0 - PING_BEHIND_PITCH) * behind


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
        self.last_pos = None            # (x, y, time)
        self.slow_from = None           # speed when W was let go: the top of the slide
        self.pitch = 1.0                # only ever goes down during a slide
        self.walls = None
        self.scene = None
        self.scanner = None             # set by run.py: what to track, and where it is
        self.spoken = queue.Queue()     # words for the main loop to speak (it owns speech)
        self.name_ahead = lambda: True  # set by run.py: the Accessibility setting
        self.namer = scanner_mod.Scanner(self.reader, self.profile, lambda s: None)
        self.box_names = []
        self.last_ahead = None          # the shape we last named
        self.cue_source = self.audio.source(0, 0.5 * volume / 0.35)
        self.hammer = self.audio.buffer(0.7 * _hammer_on())
        self.ping_source = self.audio.source(0, PING_GAIN * volume / 0.35)
        self.ping_buffer = self.audio.buffer(0.8 * _beacon())
        self.next_ping = 0.0
        self.last_step = {zone: -1 for zone in VOICES}   # -1 = nothing in range
        self.stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="wall beeps").start()

    def _horse_drone(self, player):
        """From letting go of W until the horse halts: hum, sliding steadily down."""
        now = time.perf_counter()
        if player and self.last_pos:
            x0, y0, t0 = self.last_pos
            v = math.hypot(player[0] - x0, player[1] - y0) / max(now - t0, 1e-3)
            self.speed += 0.3 * (v - self.speed)        # moving average: steady, not jittery
        else:
            self.speed = 0.0
        self.last_pos = (player[0], player[1], now) if player else None
        riding = bool(player and player[4])
        if not riding or keys.is_down(FORWARD_KEY):
            self.slow_from = None                       # W held (or on foot): no slide
        elif self.slow_from is None and self.speed > HALT_SPEED and self.drone_gain <= 0:
            self.slow_from, self.pitch = self.speed, 1.0    # just let go: start at the top
        coasting = bool(self.slow_from) and self.speed > HALT_SPEED
        if self.slow_from and not coasting:
            self.pitch = max(LOWEST_PITCH, self.pitch - 0.05)   # halted: finish the slide
        elif coasting:
            share = min(1.0, self.speed / self.slow_from)
            # a ratchet: the pitch never climbs back up, so the slide stays clean
            self.pitch = min(self.pitch, LOWEST_PITCH + (1 - LOWEST_PITCH) * share)
        target = DRONE_GAIN if coasting else 0.0
        if target and not self.drone_gain:
            self.audio.loop(self.drone_source, self.drone_buffer)
        step = 0.04 if target > self.drone_gain else 0.02   # in fast (~0.15 s), out ~0.3 s
        self.drone_gain += max(-step, min(step, target - self.drone_gain))
        if self.drone_gain <= 0:
            self.drone_gain = 0.0
            self.audio.stop(self.drone_source)
            if self.slow_from is not None and not coasting:
                self.slow_from = 0.0    # slide over: backing up with S won't restart it;
            return                      # only holding W again (which resets it) does
        self.audio.set(self.drone_source, gain=self.drone_gain, pitch=self.pitch)

    def cue(self, angle=0.0):
        """The hammer-on "you can use this" sound, from `angle` (scanner angles:
        degrees, positive to the left)."""
        self.audio.place(self.cue_source, -angle)
        self.audio.play(self.cue_source, self.hammer)

    def _name_ahead(self, player, dist):
        """Say what's straight ahead when you come close to it: "crude fence"."""
        if not self.name_ahead():
            return
        reach = NAME_REACH[player[4]]
        d = dist["front"]
        if d > reach + NAME_CLEAR:
            self.last_ahead = None
            return
        if d > reach:
            return
        a = player[3] + walls.FORWARD
        x, y = player[0] + (d + 0.15) * math.cos(a), player[1] + (d + 0.15) * math.sin(a)
        owner = self.walls.owner_at(x, y, player[2] + 1.0)
        if owner == self.last_ahead or owner is None and self.last_ahead == "wall":
            return
        self.last_ahead = owner if owner is not None else "wall"
        name = self.box_names[owner] if owner is not None and owner < len(self.box_names) else None
        self.spoken.put(name or "wall")

    def _ping(self, player):
        """Play the tracking ping from where the tracked thing is, around the head."""
        tracked = self.scanner and self.scanner.tracked
        if not tracked or time.perf_counter() < self.next_ping:
            return
        where = self.scanner.position(self.reader, tracked[0])
        if where is None:
            self.scanner.lost()
            return
        from .scanner import relative
        distance, angle = relative(player, where[0], where[1])
        # scanner angles grow to the left; sound angles grow clockwise (to the right)
        self.audio.place(self.ping_source, -angle)
        self.audio.set(self.ping_source, pitch=ping_pitch(angle))
        self.audio.play(self.ping_source, self.ping_buffer)
        self.next_ping = time.perf_counter() + ping_interval(distance)

    def _distances(self):
        """({zone: metres}, on_horse), or None outside a scene."""
        r = self.reader
        mission = walls.mission_address(r, self.profile)
        if not mission:
            return None
        scene = r.u32(mission)
        if scene != self.scene:         # a new scene: read its walls once
            self.walls, self.scene = walls.SceneWalls(r, scene), scene
            self.box_names = self.namer.name_boxes(self.walls.boxes)
            self.last_ahead = None
        player = self.player = walls.find_player(r, mission)
        if player is None:
            return None
        reach = max(REACH.values())
        dist = walls.zone_distances(self.walls, player, reach=reach)
        self._name_ahead(player, dist)
        return walls.corners_only(dist, player[4], reach), player[4]

    def _run(self):
        while not self.stop.is_set():
            self.player = None
            try:
                result = self._distances() if self.enabled and self.active() else None
            except (ReadError, ValueError, OSError):
                result, self.scene = None, None     # scene changing or game closing
            self._horse_drone(self.player if result else None)
            if result:
                self._ping(self.player)
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
