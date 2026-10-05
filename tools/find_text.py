"""Search the game's memory for a piece of text, like Ctrl+F over the whole process.

    python tools/find_text.py "some text"

Looks for it as plain bytes and as UTF-16 (2 bytes a letter, how Windows
edit controls often keep text). Prints each address and what's around it.
Takes a few seconds: it reads every writable region once.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process

game = process.try_attach()
word = sys.argv[1]
needles = {"ascii": word.encode("latin-1"), "utf16": word.encode("utf-16-le")}
for start, size in game.regions():
    try:
        data = game.read(start, size)
    except Exception:
        continue
    for kind, needle in needles.items():
        at = data.find(needle)
        while at >= 0:
            around = data[max(0, at - 16):at + len(needle) + 16]
            print(f"{start + at:#010x} {kind:5} {around!r}")
            at = data.find(needle, at + 1)
