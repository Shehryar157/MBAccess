"""Make footsteps louder (the game reads sounds.txt and the sound files at start-up).

    python tools/footsteps.py            raise footsteps (backs up sounds.txt first)
    python tools/footsteps.py 0.6        same, but a gentler boost (peak 0.6 instead of 0.9)
    python tools/footsteps.py restore    put the original back and delete the louder copies

sounds.txt is a list of sound files ("name flags"), then the named sounds
("id flags count", then "file-index 0" per file). Both kinds of flags hold the volume
(0-15) in bits 8-11 and the priority (0-15) in bits 4-7 (header_sounds.py: sf_vol_4 =
0x400, sf_priority_1 = 0x10). Native's footsteps are volume 4-5 and priority 1, the
quietest and first to be dropped in a busy scene, and the grass recordings themselves
peak at only 0.09-0.15 of full scale. So this does three things: raises the flags on the
sounds, raises them on their files, and writes louder .wav copies of the recordings
(mbaccess_*.wav, originals untouched) for the file lines to point at. Every agent shares
these sounds; yours are loudest anyway because they play at your ears and others' fade
with distance.
"""
import glob
import os
import shutil
import struct
import sys
import wave

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import numpy as np
import pygame

ROOT = r"D:\steam\steamapps\common\MountBlade Warband"
GAME = os.path.join(ROOT, "Modules", "Native")
SOUNDS = os.path.join(GAME, "sounds.txt")
BACKUP = SOUNDS + ".mbaccess-backup"
FILES = os.path.join(ROOT, "Sounds")
PREFIX = "mbaccess_"
PEAK = 0.9
# sound id -> (volume, priority)
LOUDER = {"snd_footstep_grass": (11, 6), "snd_footstep_wood": (12, 6),
          "snd_footstep_water": (11, 6)}


def raised(flags, volume, priority):
    return flags & ~0xff0 | volume << 8 | priority << 4


def ogg_format(path):
    """(sample rate, channels) from the Vorbis header at the start of an .ogg file."""
    with open(path, "rb") as f:
        head = f.read(4096)
    at = head.index(b"\x01vorbis") + 11          # past the tag and the 4-byte version
    channels, rate = struct.unpack_from("<BI", head, at)
    return rate, channels


def louder_copy(name, peak):
    """Write a louder .wav copy of a sound file; returns the copy's name and the gain used."""
    path = os.path.join(FILES, name)
    if name.lower().endswith(".ogg"):
        rate, channels = ogg_format(path)
    else:
        with wave.open(path) as w:
            rate, channels = w.getframerate(), w.getnchannels()
    pygame.mixer.quit()
    pygame.mixer.init(frequency=rate, size=-16, channels=channels, allowedchanges=0)
    samples = pygame.sndarray.array(pygame.mixer.Sound(path)).astype(np.float64)
    gain = max(1.0, peak * 32767 / max(1.0, np.abs(samples).max()))   # never make it quieter
    copy = PREFIX + os.path.splitext(name)[0] + ".wav"
    with wave.open(os.path.join(FILES, copy), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.clip(samples * gain, -32767, 32767).astype("<i2").tobytes())
    return copy, gain


def restore():
    if os.path.exists(BACKUP):
        shutil.copyfile(BACKUP, SOUNDS)
        print("original sounds.txt restored")
    else:
        print("no backup: nothing to restore")
    for path in glob.glob(os.path.join(FILES, PREFIX + "*.wav")):
        os.remove(path)
        print("deleted", os.path.basename(path))


def main():
    peak = PEAK
    if len(sys.argv) > 1:
        if sys.argv[1] == "restore":
            return restore()
        peak = float(sys.argv[1])
    if not os.path.exists(BACKUP):
        shutil.copyfile(SOUNDS, BACKUP)
    with open(BACKUP, encoding="utf-8", newline="") as f:
        lines = f.read().split("\n")        # always start from the original
    for n, line in enumerate(lines):
        words = line.split(" ")
        if not words or words[0] not in LOUDER:
            continue
        volume, priority = LOUDER[words[0]]
        flags = int(words[1])
        old = (flags >> 8) & 0xf, (flags >> 4) & 0xf
        words[1] = str(raised(flags, volume, priority))
        lines[n] = " ".join(words)
        print(f"{words[0]}: volume {old[0]} -> {volume}, priority {old[1]} -> {priority}")
        for index in words[3:3 + 2 * int(words[2]):2]:
            at = 2 + int(index)             # file lines start after the version and the count
            _, name, file_flags = lines[at].split(" ")
            if name.startswith(PREFIX):     # a file shared by two sounds: already done
                continue
            copy, gain = louder_copy(name, peak)
            lines[at] = f" {copy} {raised(int(file_flags), volume, priority)}"
            print(f"  {name} -> {copy}, {gain:.1f} times louder")
    with open(SOUNDS, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines))
    print("done: restart the game to hear it")


if __name__ == "__main__":
    main()
