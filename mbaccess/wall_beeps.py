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
import struct
import threading
import time

import numpy as np

from . import battle, keys, scanner as scanner_mod, walls
from .mem import Reader, ReadError
from .sound3d import Sound3D

RATE = 44100
TICK = 0.05                     # seconds between distance checks
REACH = {False: 4.0, True: 6.0}  # metres where beeping starts: on foot, on horseback
STEPS = 4                       # distance steps; each closer step beeps a little higher
BASE = 440                      # Hz, the pitch of the farthest step
HYSTERESIS = 0.3                # metres past a step boundary before it counts as left
SCENE_WINDOW = 10
# A wall in these directions that falls out of range (a side street opens on your left)
# gives a whoosh. Not behind (walking away from a wall says nothing new), not diagonals
# (corners_only hides them whenever a side wall explains them).
OPEN_ZONES = ("front", "left", "right")
OPEN_GAIN = 0.7
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


# Stairs and steps: after a steep climb on foot, say how far up or down you went.
CLIMB_WINDOW = 2.0      # metres walked that the slope is measured over
CLIMB_STEEP = 0.4       # rise per metre walked that counts as stairs (~22 degrees; hills are gentler)
CLIMB_FLAT = 0.15       # below this the climb is over
CLIMB_SAY = 1.5         # metres up or down worth saying (a doorstep isn't)


CLIMB_NOTES = (523.25, 659.25)  # C5 -> E5 going up; reversed going down
CLIMB_GAIN = 0.6
LEVEL_SAME = 2.5        # metres: a climb found this close to one already played is the same one
LEVEL_FORGET = 3.0      # metres beyond reach before a played climb or drop can play again


def _slur(first, second, length=0.26, switch=0.09):
    """A beep that slurs from one note to the next with no new attack, like a guitar
    hammer-on (rising) or pull-off (falling): one continuous wave whose pitch jumps.
    Sine plus a soft octave, a quick start and a smooth decay."""
    t = np.arange(int(RATE * length)) / RATE
    freq = np.where(t < switch, first, second)
    phase = 2 * math.pi * np.cumsum(freq) / RATE      # continuous phase: no click at the jump
    tone = np.sin(phase) + 0.25 * np.sin(2 * phase)
    envelope = np.minimum(1, t / 0.005) * np.exp(-t / 0.12)
    out = tone * envelope * np.minimum(1, (length - t) / 0.02)
    return out / np.max(np.abs(out))


NAME_REACH = {False: 1.5, True: 2.5}    # metres: name the thing ahead when this close
NAME_CLEAR = 0.6                        # metres further before the same thing is new again


def _string(history, period, count, decay, brightness):
    """Continue a plucked string for `count` samples (Karplus-Strong): each new sample is
    the average of the two samples one period back, a little quieter. Worked a period at
    a time with numpy, since a block only depends on the block before it."""
    h = len(history)
    y = np.empty(h + count + period + 1)
    y[:h] = history
    n = h
    while n < h + count:
        prev = y[n - period - 1:n]
        y[n:n + period] = decay * (brightness * prev[1:] + (1 - brightness) * prev[:-1])
        n += period
    return y[h:h + count]


def _guitar_body(length=0.35):
    """A classical guitar body's ring: a few wooden resonances (air cavity ~100 Hz, top
    plate ~200 Hz, higher plate modes), each a decaying sine. Convolving the string with
    this is what makes it sound like it's coming out of a guitar, not a wire."""
    t = np.arange(int(RATE * length)) / RATE
    modes = ((102, 0.12, 1.0), (196, 0.10, 0.9), (285, 0.07, 0.45), (403, 0.05, 0.5),
             (550, 0.04, 0.3), (720, 0.03, 0.2), (1050, 0.02, 0.12))
    ir = sum(g * np.exp(-t / tau) * np.sin(2 * math.pi * f * t) for f, tau, g in modes)
    return ir / np.sum(np.abs(ir))


def _hammer_on():
    """The "you can use this" cue: a classical (nylon string) guitar hammer-on, G3 then up
    a major third to B3 on the same ringing string.

    Plucked string: a soft burst of noise (the fingertip) circulates in a loop one
    period long, losing its bright overtones first, as a real string does. Plucking a
    fifth of the way along the string (a comb filter on the burst) gives the round
    nylon tone. The hammer-on shortens the loop mid-note with no new pluck, and the
    guitar body's resonances (_guitar_body) give it warmth."""
    rng = np.random.default_rng(11)         # the same pluck every time
    first, second, switch, length = 196.0, 246.94, 0.11, 1.1
    n1, n2 = int(round(RATE / first)), int(round(RATE / second))
    burst = rng.uniform(-1, 1, n1 + 1)
    for _ in range(4):                      # a fingertip, not a pick: soften the burst
        burst = 0.5 * (burst + np.roll(burst, 1))
    at = int(n1 * 0.2)                      # plucked a fifth along the string
    burst = burst - np.roll(burst, at)
    burst -= burst.mean()
    head = _string(burst, n1, int(RATE * switch), 0.9985, 0.45)
    hist = np.concatenate([burst, head])
    tail = _string(hist[-(n2 + 1):], n2, int(RATE * (length - switch)), 0.9982, 0.42)
    string = np.concatenate([head, tail])
    # the hammered finger adds a faint tap of its own
    tap = np.zeros_like(string)
    k = int(RATE * switch)
    tap[k:k + 200] = 0.15 * np.hanning(200) * rng.uniform(-1, 1, 200)
    ir = _guitar_body()
    size = 1 << (len(string) + len(ir)).bit_length()        # convolve via FFT: fast
    body = np.fft.irfft(np.fft.rfft(string + tap, size) * np.fft.rfft(ir, size), size)[:len(string)]
    out = 0.45 * string / np.max(np.abs(string)) + 0.55 * body / np.max(np.abs(body))
    t = np.arange(len(out)) / RATE
    out *= np.minimum(1, t / 0.002) * np.minimum(1, (length - t) / 0.15)
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


def _whoosh(length=0.32):
    """The "it's open here" sound: soft noise that brightens as it swells, then fades,
    like air opening up. Noise, not a tone, so it's never mistaken for a wall beep."""
    rng = np.random.default_rng(7)          # the same whoosh every time
    noise = rng.standard_normal(int(RATE * length))
    smooth = lambda x, n: np.convolve(x, np.ones(n) / n, mode="same")
    dark, bright = smooth(noise, 24), smooth(noise, 5) - smooth(noise, 60)
    t = np.linspace(0, 1, len(noise))
    mix = (1 - t) * dark / np.abs(dark).max() + t * bright / np.abs(bright).max()
    envelope = np.sin(math.pi * t ** 0.7) ** 2        # swells, peaks early-middle, fades
    return 0.6 * mix * envelope


SWING_GAIN = 0.9
SWING_VOICES = 3        # attackers heard at once: each needs its own source


def _zip(length=0.11):
    """An enemy's weapon going up: a quick dry sweep upward with a breath of noise. No
    steady pitch, so it's never taken for a wall beep, and short, because the swing is
    already on its way."""
    t = np.arange(int(RATE * length)) / RATE
    sweep = 520 * 3.0 ** (t / length)                       # 520 Hz up to 1560 Hz
    tone = np.sin(2 * math.pi * np.cumsum(sweep) / RATE)
    noise = np.random.default_rng(3).standard_normal(len(t))
    noise = noise - np.convolve(noise, np.ones(12) / 12, mode="same")    # the bright part only
    envelope = np.minimum(1, t / 0.004) * np.exp(-t / (length * 0.45))
    return (0.7 * tone + 0.3 * noise / np.abs(noise).max()) * envelope


def swing_pitch(distance):
    """The zip's pitch: as written at the edge of reach, a third higher point blank."""
    return 1.0 + 0.3 * max(0.0, min(1.0, 1 - (distance - 1.0) / (battle.MELEE_REACH - 1.0)))


def _creak(length=0.42):
    """An archer or thrower aiming at you: a low rising creak, like a string being drawn."""
    t = np.arange(int(RATE * length)) / RATE
    sweep = 95 * 1.8 ** (t / length)
    phase = 2 * math.pi * np.cumsum(sweep) / RATE
    buzz = sum(np.sin(m * phase) / m for m in range(1, 9))  # a rough, stringy tone
    grain = 0.6 + 0.4 * np.sign(np.sin(2 * math.pi * 34 * t))    # the creak's stutter
    envelope = np.minimum(1, t / 0.03) * np.minimum(1, (length - t) / 0.06)
    return 0.5 * buzz / np.abs(buzz).max() * grain * envelope


AIM_GAIN = 0.45
LOCK_HZ, LOCK_EVERY = 1245, 0.16    # in reach: quick high blips, like a lock-on tone
CLOSER_HZ = 830                     # facing him, too far: the same voice lower and slower


def closer_interval(distance, reach):
    """Seconds between "get closer" blips: slow far off, quickening as the gap closes."""
    return 0.35 + 0.65 * max(0.0, min(1.0, (distance - reach) / (battle.AIM_FAR - reach + 0.01)))


SINE = [(1, 1.0)]
BRIGHT =[(1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15)]         # all overtones: clear, bright
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


# The Accessibility tab's "Learn sounds" list: (id, what the player hears it called).
LESSONS = (
    ("front", "wall ahead. Each step closer beeps a little higher"),
    ("front right", "wall ahead on the right, diagonal. Shorter and brighter"),
    ("right", "wall on the right"),
    ("behind right", "wall behind on the right, diagonal. Hollow double blip"),
    ("behind", "wall behind. A double blip"),
    ("behind left", "wall behind on the left, diagonal"),
    ("left", "wall on the left"),
    ("front left", "wall ahead on the left, diagonal"),
    ("open", "opening. A wall on your left, ahead or right falls away, like a side street"),
    ("use", "you can use something: talk, mount, go through"),
    ("ping near", "tracking ping, ahead, coming closer: it gets quicker"),
    ("ping behind", "tracking ping, behind you: lower"),
    ("drone", "horse slowing down after you let go of W"),
    ("climb up", "a way up in that direction: stairs, a ramp or steps. Plays once as it comes in range"),
    ("climb down", "a way down or a drop in that direction"),
    ("swing", "an enemy near you raises his weapon: block now. It comes from where he "
              "stands, and is higher the closer he is"),
    ("aim", "an archer or thrower aims at you"),
    ("lock", "you face an enemy and your weapon reaches him: attack now"),
    ("closer", "you face an enemy but he is too far: quicker as you close in"),
)


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
        self.open_sources = {zone: self.audio.source(VOICES[zone][0], OPEN_GAIN * volume) for zone in OPEN_ZONES}
        self.open_buffer = self.audio.buffer(_whoosh())
        self.volume = volume
        self.trail = []                 # (metres walked so far, height) over the last CLIMB_WINDOW
        self.walked = 0.0
        self.climb_from = None          # height where the current steep climb began
        self.climb_source = self.audio.source(0, CLIMB_GAIN * volume / 0.35)
        self.levels_heard = []          # (x, y, +1/-1) climbs and drops already played
        self.climb_up = self.audio.buffer(0.8 * _slur(*CLIMB_NOTES))
        self.climb_down = self.audio.buffer(0.8 * _slur(*CLIMB_NOTES[::-1]))
        self.swings = None              # battle.SwingWatch, set by run.py once the names load
        self.swing_sources = [self.audio.source(0, SWING_GAIN * volume / 0.35) for _ in range(SWING_VOICES)]
        self.swing_turn = 0
        self.zip, self.creak = self.audio.buffer(0.8 * _zip()), self.audio.buffer(0.8 * _creak())
        self.lock_on = lambda: True     # set by run.py: the Accessibility setting
        self.aim_source = self.audio.source(0, AIM_GAIN * volume / 0.35)
        self.lock = self.audio.buffer(0.8 * _shape(LOCK_HZ, HOLLOW, 0.05))
        self.closer = self.audio.buffer(0.8 * _shape(CLOSER_HZ, HOLLOW, 0.05))
        self.next_aim = 0.0
        self.demo_source = self.audio.source(0, 0)     # Learn sounds: its own, so the
        self.demo_turn = 0                              # beep thread never cuts it off
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

    def demo(self, lesson):
        """Play one of LESSONS (Learn sounds, Accessibility tab) from where it would really
        come from. A new demo cuts off the one playing."""
        self.demo_turn += 1
        threading.Thread(target=self._demo, args=(lesson, self.demo_turn), daemon=True,
                         name="sound demo").start()

    def _demo(self, lesson, turn):
        a, src, v = self.audio, self.demo_source, self.volume

        def play(buffer, angle, gain, pitch=1.0):
            if turn != self.demo_turn:
                return False                # another demo started: stop this one
            a.place(src, angle)
            a.set(src, gain=gain, pitch=pitch)
            a.play(src, buffer)
            return True

        def wait(seconds):
            time.sleep(seconds)
            return turn == self.demo_turn

        if lesson in VOICES:
            angle, _, _, _, gain = VOICES[lesson]
            for step in range(STEPS):           # the four steps, far to near
                if not play(self.sounds[lesson, step], angle, gain * v) or not wait(0.45):
                    return
        elif lesson == "open":
            play(self.open_buffer, VOICES["left"][0], OPEN_GAIN * v)
        elif lesson == "use":
            play(self.hammer, 0, 0.5 * v / 0.35)
        elif lesson in ("ping near", "ping behind"):
            behind = lesson == "ping behind"
            for distance in ((20, 12, 8, 5, 3) if not behind else (10,) * 5):
                angle = 180 if behind else 0
                if not play(self.ping_buffer, angle, PING_GAIN * v / 0.35, ping_pitch(angle)):
                    return
                if not wait(ping_interval(distance)):
                    return
        elif lesson in ("climb up", "climb down"):
            play(self.climb_up if lesson == "climb up" else self.climb_down, 0, CLIMB_GAIN * v / 0.35)
        elif lesson == "swing":
            # From the right at the edge of reach, then ahead and close: higher.
            for angle, distance in ((70, battle.MELEE_REACH), (0, 1.5)):
                if not play(self.zip, angle, SWING_GAIN * v / 0.35, swing_pitch(distance)) or not wait(0.7):
                    return
        elif lesson == "aim":
            play(self.creak, -40, SWING_GAIN * v / 0.35)
        elif lesson == "lock":
            for _ in range(8):
                if not play(self.lock, 0, AIM_GAIN * v / 0.35) or not wait(LOCK_EVERY):
                    return
        elif lesson == "closer":
            for distance in (20, 14, 9, 5, 3):
                if not play(self.closer, 0, AIM_GAIN * v / 0.35) or not wait(closer_interval(distance, 2.0)):
                    return
        elif lesson == "drone":
            a.place(src, 0)
            a.set(src, gain=DRONE_GAIN, pitch=1.0)
            a.loop(src, self.drone_buffer)
            try:
                for n in range(50):             # 2.5 s slide down to the halt
                    if not wait(0.05):
                        return
                    a.set(src, pitch=1.0 - (1.0 - LOWEST_PITCH) * n / 49,
                          gain=DRONE_GAIN * min(1.0, (50 - n) / 10))
            finally:
                a.stop(src)
                a.set(src, pitch=1.0)

    def _climb(self, player):
        """On stairs (steep, on foot): once you're off them, "up 4 metres". Measured as
        height gained over the last CLIMB_WINDOW metres walked, so standing still or a
        jump in place doesn't count, and gentle hills stay quiet."""
        if player is None or player[4]:
            self.trail, self.climb_from = [], None
            return
        x, y, z = player[0], player[1], player[2]
        if self.trail:
            step = math.hypot(x - self.trail[-1][2], y - self.trail[-1][3])
            if step > 2.0:              # moved by a door or a load, not by walking
                self.trail, self.climb_from = [], None
            elif step < 0.02:
                return                  # standing still: nothing to measure
            else:
                self.walked += step
        self.trail.append((self.walked, z, x, y))
        while len(self.trail) > 2 and self.walked - self.trail[1][0] >= CLIMB_WINDOW:
            self.trail.pop(0)
        span = self.walked - self.trail[0][0]
        if span < CLIMB_WINDOW * 0.75:
            return
        slope = (z - self.trail[0][1]) / span
        if abs(slope) >= CLIMB_STEEP and self.climb_from is None:
            self.climb_from = self.trail[0][1]
        elif abs(slope) <= CLIMB_FLAT and self.climb_from is not None:
            rise = z - self.climb_from
            self.climb_from = None
            if abs(rise) >= CLIMB_SAY:
                self.spoken.put("%s %d metres" % ("up" if rise > 0 else "down", round(abs(rise))))

    def _levels(self, player, dist, reach):
        """A climb or drop comes into range: the up or down slur once, from its direction.
        Not again as you come closer; again only after you've gone well away from it."""
        px, py = player[0], player[1]
        self.levels_heard = [(x, y, s) for x, y, s in self.levels_heard
                             if math.hypot(x - px, y - py) <= reach + LEVEL_FORGET]
        for zone, sign, x, y in walls.level_changes(self.walls, player, dist, reach):
            if any(s == sign and math.hypot(x - hx, y - hy) < LEVEL_SAME
                   for hx, hy, s in self.levels_heard):
                continue
            self.levels_heard.append((x, y, sign))
            self.audio.place(self.climb_source, VOICES[zone][0])
            self.audio.play(self.climb_source, self.climb_up if sign > 0 else self.climb_down)

    def _swings(self, player):
        """Play each attack an enemy has just begun on us, from where he stands."""
        if self.swings is None:
            return
        mission = walls.mission_address(self.reader, self.profile)
        with self.reader.cached():
            started = self.swings.check(self.reader, mission, player)
        for kind, distance, angle in started[:SWING_VOICES]:
            source = self.swing_sources[self.swing_turn % SWING_VOICES]
            self.swing_turn += 1
            self.audio.place(source, -angle)        # ours grow to the left, the sound's to the right
            self.audio.set(source, pitch=swing_pitch(distance) if kind == "melee" else 1.0)
            self.audio.play(source, self.zip if kind == "melee" else self.creak)

    def _aim(self, player):
        """The lock-on blips: quick and high while your weapon reaches the enemy you
        face, lower and slower while you face one who is still too far."""
        now = time.perf_counter()
        if not self.lock_on() or now < self.next_aim:
            return
        mission = walls.mission_address(self.reader, self.profile)
        with self.reader.cached():
            found = battle.aim(self.reader, mission, player, self.profile.screen)
        if found is None:
            return
        state, distance, angle, reach = found
        self.audio.place(self.aim_source, -angle)
        self.audio.play(self.aim_source, self.lock if state == "hit" else self.closer)
        self.next_aim = now + (LOCK_EVERY if state == "hit" else closer_interval(distance, reach))

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
        player = self.player = walls.find_player(r, mission, self.profile)
        if player is None:
            return None
        reach = max(REACH.values())
        dist = walls.zone_distances(self.walls, player, reach=reach)
        self._name_ahead(player, dist)
        self._levels(player, dist, REACH[player[4]])
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
                self._climb(self.player)
                try:
                    self._swings(self.player)
                    self._aim(self.player)
                except (ReadError, ValueError, OSError, struct.error):
                    pass
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
                        was = self.last_step[zone]
                        self.last_step[zone] = min(was, max(step, back))
                        if was >= 0 and self.last_step[zone] == -1 and zone in OPEN_ZONES:
                            self.audio.play(self.open_sources[zone], self.open_buffer)   # open now
            time.sleep(TICK)
