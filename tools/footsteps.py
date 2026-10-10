"""Make footsteps louder by editing the module's sounds.txt (the game reads it at start-up).

    python tools/footsteps.py            raise footsteps (backs up sounds.txt first)
    python tools/footsteps.py restore    put the original back

Each sound line is: id, flags, file count, files... The flags hold the volume (0-15) in
bits 8-11 and the priority (0-15) in bits 4-7 (header_sounds.py: sf_vol_4 = 0x400,
sf_priority_1 = 0x10). Native's footsteps are volume 4-5 and priority 1, the quietest
and first to be dropped in a busy scene. Every agent shares these sounds; yours are
loudest anyway because they play at your ears and others' fade with distance.
"""
import os
import shutil
import sys

GAME = r"D:\steam\steamapps\common\MountBlade Warband\Modules\Native"
SOUNDS = os.path.join(GAME, "sounds.txt")
BACKUP = SOUNDS + ".mbaccess-backup"
# sound id -> (volume, priority)
LOUDER = {"snd_footstep_grass": (11, 6), "snd_footstep_wood": (12, 6),
          "snd_footstep_water": (11, 6)}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "restore":
        if os.path.exists(BACKUP):
            shutil.copyfile(BACKUP, SOUNDS)
            print("original sounds.txt restored")
        else:
            print("no backup: nothing to restore")
        return
    if not os.path.exists(BACKUP):
        shutil.copyfile(SOUNDS, BACKUP)
    with open(BACKUP, encoding="utf-8", newline="") as f:
        lines = f.read().split("\n")        # always start from the original
    for n, line in enumerate(lines):
        words = line.split(" ")
        if words and words[0] in LOUDER:
            volume, priority = LOUDER[words[0]]
            flags = int(words[1])
            old = (flags >> 8) & 0xf, (flags >> 4) & 0xf
            words[1] = str(flags & ~0xff0 | volume << 8 | priority << 4)
            lines[n] = " ".join(words)
            print(f"{words[0]}: volume {old[0]} -> {volume}, priority {old[1]} -> {priority}")
    with open(SOUNDS, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines))
    print("done: restart the game to hear it")


if __name__ == "__main__":
    main()
