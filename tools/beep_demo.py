"""Hear the wall beeps' eight positions (HRTF, headphones), clockwise from ahead.
Each direction plays far then close, with the direction's name spoken first.

    python tools/beep_demo.py [diagonal angle, default 45]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import speech, wall_beeps, walls
from mbaccess.sound3d import Sound3D

angle = float(sys.argv[1]) if len(sys.argv) > 1 else wall_beeps.DIAGONAL_ANGLE
audio = Sound3D(wall_beeps.RATE)
print("HRTF on" if audio.hrtf else "HRTF OFF (plain stereo)")
for zone in walls.ZONES:
    a, harmonics, length, blips, gain = wall_beeps.VOICES[zone]
    if zone in walls.DIAGONALS:
        a = {"front right": angle, "behind right": 180 - angle,
             "behind left": 180 + angle, "front left": 360 - angle}[zone]
    src = audio.source(a, gain * 0.35)
    speech.say(zone)
    time.sleep(1.2)
    for step in (0, wall_beeps.STEPS - 1):
        f = wall_beeps.BASE * 2 ** (step * 2 / 12)
        audio.play(src, audio.buffer(0.8 * wall_beeps._shape(f, harmonics, length, blips)))
        time.sleep(0.6)
    time.sleep(0.6)
