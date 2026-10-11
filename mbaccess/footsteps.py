"""Louder footsteps: the mod changes the game's own sound list, with a backup.

The game reads Modules/<module>/sounds.txt and the sound files when it starts. That
file is a list of sound files (" name flags"), then the named sounds ("id flags count",
then "file-index 0" per file). Both kinds of flags hold the volume (0-15) in bits 8-11
and the priority (0-15) in bits 4-7. Native's footsteps are volume 4-5 and priority 1,
the quietest and first to be dropped in a busy scene, and the grass recordings
themselves peak at only 0.09-0.15 of full scale. So we raise the flags on the sounds
and on their files, and write louder .wav copies of the recordings (mbaccess_*.wav,
the originals untouched) for the file lines to point at.

sync() runs each time the mod starts (with the launcher, before the game reads the
file), so a game update or Steam's "verify files" putting the original back is mended
at the next start. Switched off in the settings, it puts the original back instead.
"""
import glob
import os
import shutil
import struct
import wave

PREFIX = "mbaccess_"
BACKUP_END = ".mbaccess-backup"
PEAK = 0.9      # of full scale
# sound id -> (volume, priority)
LOUDER = {"snd_footstep_grass": (11, 6), "snd_footstep_wood": (12, 6),
          "snd_footstep_water": (11, 6)}


def raised(flags, volume, priority):
    return flags & ~0xff0 | volume << 8 | priority << 4


def patch(lines, louder):
    """sounds.txt's lines with the footsteps raised. louder(file name) makes the louder
    copy and returns its name, or None if it can't (the line then keeps its file).
    Running it on its own result changes nothing. Pure but for louder(): tested."""
    lines = list(lines)
    for n, line in enumerate(lines):
        words = line.split(" ")
        if words[0] not in LOUDER:
            continue
        volume, priority = LOUDER[words[0]]
        words[1] = str(raised(int(words[1]), volume, priority))
        lines[n] = " ".join(words)
        for index in words[3:3 + 2 * int(words[2]):2]:
            at = 2 + int(index)         # file lines start after the version and the count
            _, name, flags = lines[at].split(" ")
            lines[at] = f" {louder(name) or name} {raised(int(flags), volume, priority)}"
    return lines


def _ogg_format(path):
    """(sample rate, channels) from the Vorbis header at the start of an .ogg file."""
    with open(path, "rb") as f:
        head = f.read(4096)
    at = head.index(b"\x01vorbis") + 11          # past the tag and the 4-byte version
    channels, rate = struct.unpack_from("<BI", head, at)
    return rate, channels


def _louder_copy(path, copy, peak):
    """Write a louder .wav copy of a sound file (.ogg or .wav)."""
    # pygame decodes the .ogg files; "dummy" = no sound device needed, nothing is played.
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    import numpy as np
    import pygame
    if path.lower().endswith(".ogg"):
        rate, channels = _ogg_format(path)
    else:
        with wave.open(path) as w:
            rate, channels = w.getframerate(), w.getnchannels()
    pygame.mixer.quit()
    pygame.mixer.init(frequency=rate, size=-16, channels=channels, allowedchanges=0)
    samples = pygame.sndarray.array(pygame.mixer.Sound(path)).astype(np.float64)
    gain = max(1.0, peak * 32767 / max(1.0, np.abs(samples).max()))   # never make it quieter
    with wave.open(copy + ".part", "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.clip(samples * gain, -32767, 32767).astype("<i2").tobytes())
    os.replace(copy + ".part", copy)
    return gain


def _modules(folder):
    """(module folder, its sounds.txt) for every module that has one."""
    for module in sorted(glob.glob(os.path.join(folder, "Modules", "*"))):
        sounds = os.path.join(module, "sounds.txt")
        if os.path.isfile(sounds):
            yield module, sounds


def _read(path):
    # latin-1 gives every byte back unchanged, whatever a module's author typed.
    with open(path, encoding="latin-1", newline="") as f:
        return f.read()


def apply(folder, peak=PEAK):
    """Raise the footsteps in every module of the game in this folder. True if a file
    was changed (heard from the next time the game reads it)."""
    changed = False
    for module, sounds in _modules(folder):
        places = [os.path.join(folder, "Sounds"), os.path.join(module, "Sounds")]

        def louder(name):
            original = name[len(PREFIX):] if name.startswith(PREFIX) else name
            stem = os.path.splitext(original)[0]
            copy = PREFIX + stem + ".wav"
            for place in places:
                if os.path.exists(os.path.join(place, copy)):
                    return copy
            for place in places:
                # A line already pointing at our copy only remembers the stem.
                for source in ([original] if name == original else [stem + ".ogg", stem + ".wav"]):
                    path = os.path.join(place, source)
                    if os.path.exists(path):
                        try:
                            gain = _louder_copy(path, os.path.join(place, copy), peak)
                        except Exception as e:      # an odd file: leave that one as it is
                            print(f"footsteps: {source}: {e!r}")
                            return None
                        print(f"footsteps: {source} -> {copy}, {gain:.1f} times louder")
                        return copy
            return None

        try:
            text = _read(sounds)
            new = "\n".join(patch(text.split("\n"), louder))
            if new == text:
                continue
            if PREFIX not in text:      # untouched by us: this is the original to keep
                shutil.copyfile(sounds, sounds + BACKUP_END)
            with open(sounds + ".part", "w", encoding="latin-1", newline="") as f:
                f.write(new)
            os.replace(sounds + ".part", sounds)    # in one step: the game never reads half a file
            print("footsteps: raised in", os.path.basename(module))
            changed = True
        except Exception as e:
            print(f"footsteps: {os.path.basename(module)}: {e!r}")
    return changed


def restore(folder):
    """Put every module's original sounds.txt back and delete the louder copies."""
    for module, sounds in _modules(folder):
        backup = sounds + BACKUP_END
        try:
            if os.path.exists(backup):
                if PREFIX in _read(sounds):     # else the game already has a fresh original
                    shutil.copyfile(backup, sounds)
                    print("footsteps: original put back in", os.path.basename(module))
                os.remove(backup)
            for place in (os.path.join(folder, "Sounds"), os.path.join(module, "Sounds")):
                for path in glob.glob(os.path.join(place, PREFIX + "*.wav")):
                    os.remove(path)
        except OSError as e:
            print(f"footsteps: {os.path.basename(module)}: {e!r}")


def sync(folder, on):
    try:
        apply(folder) if on else restore(folder)
    except Exception as e:
        print("footsteps:", repr(e))
