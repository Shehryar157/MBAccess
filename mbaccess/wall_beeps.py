"""Wall beeps in scenes: a soft tone when you move closer to a wall.

Four zones around the player (front, right, behind, left). Each remembers its
last distance step; when you get a step closer, it beeps once at that step's
pitch. Standing still or moving away is silent. Same pure tone for every zone:
right and left are panned to that ear, behind is a double blip. Sounds are made
in code (numpy sine waves) and played with pygame's mixer, which pans per channel.
"""
import math
import os
import threading
import time

import numpy as np

from . import walls
from .mem import Reader, ReadError

RATE = 44100
TICK = 0.05                     # seconds between distance checks
REACH = {False: 4.0, True: 6.0}  # metres where beeping starts: on foot, on horseback
STEPS = 4                       # distance steps; each closer step beeps a little higher
BASE = 440                      # Hz, the pitch of the farthest step
HYSTERESIS = 0.3                # metres past a step boundary before it counts as left
SCENE_WINDOW = 10

# zone -> (double blip, (left volume, right volume))
VOICES = {
    "front":  (False, (1.0, 1.0)),
    "right":  (False, (0.0, 1.0)),
    "behind": (True, (1.0, 1.0)),
    "left":   (False, (1.0, 0.0)),
}


def _tone(freq, blips=1, length=0.09, gap=0.04):
    """A round beep: a pure sine with slow 25 ms fades (sharp edges sound like clicks)."""
    t = np.arange(int(RATE * length)) / RATE
    fade = np.minimum(1, np.minimum(t, t[::-1]) / 0.025)
    one = np.sin(2 * math.pi * freq * t) * fade
    parts = []
    for _ in range(blips):
        parts += [one, np.zeros(int(RATE * gap))]
    return np.concatenate(parts)


class WallBeeper:
    def __init__(self, game, active, volume=0.35):
        """active(): True while the player is walking around (scene window on top)."""
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame
        pygame.mixer.init(frequency=RATE, size=-16, channels=2, buffer=512)
        pygame.mixer.set_num_channels(8)
        self.reader = Reader(game)      # our own: the main loop's reader isn't thread-safe
        self.profile = game.profile
        self.active = active
        self.volume = volume
        self.enabled = True
        self.sounds = {}            # (zone, step) -> pygame Sound
        for zone, (double, _) in VOICES.items():
            for step in range(STEPS):
                f = BASE * 2 ** (step * 2 / 12)        # each step two semitones up
                pcm = (_tone(f, 2 if double else 1) * 32767 * 0.8).astype(np.int16)
                self.sounds[zone, step] = pygame.sndarray.make_sound(np.column_stack([pcm, pcm]))
        self.walls = None
        self.scene = None
        self.last_step = {zone: -1 for zone in VOICES}   # -1 = nothing in range
        self.stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="wall beeps").start()

    def _distances(self):
        """({zone: metres}, on_horse), or None outside a scene."""
        r = self.reader
        mission = walls.mission_address(r, self.profile)
        if not mission:
            return None
        scene = r.u32(mission)
        if scene != self.scene:         # a new scene: read its walls once
            self.walls, self.scene = walls.SceneWalls(r, scene), scene
        player = walls.find_player(r, mission)
        if player is None:
            return None
        return walls.zone_distances(self.walls, player, reach=max(REACH.values())), player[4]

    def _beep(self, zone, step):
        left, right = VOICES[zone][1]
        channel = self.sounds[zone, step].play()
        if channel:
            channel.set_volume(left * self.volume, right * self.volume)

    def _run(self):
        while not self.stop.is_set():
            try:
                result = self._distances() if self.enabled and self.active() else None
            except (ReadError, ValueError, OSError):
                result, self.scene = None, None     # scene changing or game closing
            if not result:
                self.last_step = {zone: -1 for zone in VOICES}
            else:
                dist, on_horse = result
                reach = REACH[on_horse]
                for zone in walls.ZONES:
                    d = dist[zone]
                    step = min(STEPS - 1, int((1 - d / reach) * STEPS)) if d < reach else -1
                    if step > self.last_step[zone]:
                        self._beep(zone, step)          # a step closer: say so once
                        self.last_step[zone] = step
                    elif step < self.last_step[zone]:
                        # farther: remember quietly, but only once clearly past the
                        # boundary, so wobbling on it doesn't beep again and again
                        d2 = d - HYSTERESIS
                        back = min(STEPS - 1, int((1 - d2 / reach) * STEPS)) if d2 < reach else -1
                        self.last_step[zone] = min(self.last_step[zone], max(step, back))
            time.sleep(TICK)
