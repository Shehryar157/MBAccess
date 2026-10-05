"""Game messages: speak each new one, and keep them in buffers to review.

The engine's window manager keeps every message it has shown in a list,
message_log (an stl::vector of rgl::strings, see docs/findings.md). We
remember how many we've seen; each tick, anything past that is new.

Buffers: "All" has everything; the others are categories picked by keywords
(message_categories.json, first match wins, "Other" for the rest). The game
doesn't store a category, so the keywords are our guesses, easy to adjust.
Keys: [ and ] change buffer, ; and ' read the previous or next message,
Shift with ; or ' jumps to the oldest or newest.
"""
import json
import os
import re

from . import keys
from . import text as text_mod
from .mem import ReadError

STRING_SIZE = 0x90   # one rgl::string
HERE = os.path.dirname(os.path.abspath(__file__))


def load_categories(path=os.path.join(HERE, "message_categories.json")):
    """[(name, compiled pattern)], one pattern of whole words per category."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [(name, re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")", re.I))
            for name, words in raw.items()]


def categorize(text, categories):
    for name, pattern in categories:
        if pattern.search(text):
            return name
    return "Other"


class Buffer:
    def __init__(self, name):
        self.name = name
        self.messages = []
        self.cursor = -1     # -1: on the newest, whatever arrives

    def at(self):
        return len(self.messages) - 1 if self.cursor < 0 else self.cursor


class MessageWatcher:
    def __init__(self, reader, log_address, say, categories=None, settings=None):
        self.reader = reader
        self.settings = settings     # which categories to speak (Accessibility tab)
        self.log = log_address
        self.say = say
        self.categories = load_categories() if categories is None else categories
        names = ["All"] + [n for n, _ in self.categories] + ["Other"]
        self.buffers = [Buffer(n) for n in names]
        self.current = 0
        self.seen = None     # None until the first read: old messages aren't spoken

    def poll(self):
        try:
            start, end = self.reader.u32(self.log), self.reader.u32(self.log + 4)
            count = (end - start) // STRING_SIZE
            if self.seen is None:
                first, speak = 0, False      # starting up: keep what's there, quietly
            elif count < self.seen:
                first, speak = count, False  # the log was emptied: start counting again
            else:
                first, speak = self.seen, True
            new = [text_mod.clean(self.reader.rgl_string(start + i * STRING_SIZE))
                   for i in range(first, count)]
        except ReadError:
            return
        self.seen = count
        for message in new:
            if not message:
                continue
            name = self.add(message)     # muted ones still go in the buffers
            if speak and (self.settings is None or self.settings.speaks_category(name)):
                self.say(message, interrupt=False)   # after whatever's being said

    def add(self, message):
        """File a message in All and its category's buffer; return the category."""
        self.buffers[0].messages.append(message)
        name = categorize(message, self.categories)
        for b in self.buffers[1:]:
            if b.name == name:
                b.messages.append(message)
        return name

    # --- reviewing --------------------------------------------------------

    def handle_keys(self, pressed):
        for key in pressed:
            if key in (keys.LEFT_BRACKET, keys.RIGHT_BRACKET):
                step = 1 if key == keys.RIGHT_BRACKET else -1
                self.current = (self.current + step) % len(self.buffers)
                self.buffers[self.current].cursor = -1
                self.read(announce=True)
            elif key in (keys.SEMICOLON, keys.QUOTE):
                self.move(key == keys.QUOTE, keys.is_down(keys.SHIFT))

    def move(self, newer, to_end):
        b = self.buffers[self.current]
        if not b.messages:
            self.say(f"{b.name}, empty")
            return
        last = len(b.messages) - 1
        here = b.at()
        target = (last if newer else 0) if to_end else here + (1 if newer else -1)
        if not 0 <= target <= last:
            self.say("No newer messages." if newer else "No older messages.")
            return
        b.cursor = -1 if target == last else target
        self.read()

    def read(self, announce=False):
        b = self.buffers[self.current]
        if not b.messages:
            self.say(f"{b.name}, empty")
            return
        n = b.at()
        message = b.messages[n]
        self.say(f"{b.name}: {message}, {n + 1} of {len(b.messages)}" if announce else message)
