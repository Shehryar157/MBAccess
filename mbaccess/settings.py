"""The mod's own settings, saved in settings.json next to run.py.

Works like a Python dict that saves itself: settings.get("speak_messages")
reads one, settings.set(...) changes it and writes the file at once, so
nothing is lost if the game crashes. Missing keys fall back to DEFAULTS, so
an old settings.json keeps working when we add new settings.
"""
import json
import os

from . import paths

PATH = os.path.join(paths.USER, "settings.json")

ITEM_DETAILS = ("Full", "Name and price", "Name only")
TURN_SPEEDS = (30, 45, 60, 90, 120, 180, 240)    # degrees a second, arrow keys on foot
INTERACT_MODES = ("Facing it", "Close enough")    # when the "you can use this" cue plays
DEFAULTS = {
    "speak_messages": True,
    "muted_categories": [],      # message categories not spoken (still kept in the buffers)
    "item_details": "Full",      # how much of an inventory item's tooltip to read
    "turn_speed": 90,            # degrees a second while an arrow key turns you on foot
    "name_ahead": True,          # say what's in front when you come close: "crude fence"
    "lock_on": True,             # battle: blips while you face an enemy (in reach / too far)
    "interact_mode": "Facing it",   # Facing it: the game's own rule; Close enough: nearby
}


class Settings:
    def __init__(self, path=PATH):
        self.path = path
        self.values = dict(DEFAULTS)
        try:
            with open(path, encoding="utf-8") as f:
                self.values.update(json.load(f))
        except (OSError, ValueError):
            pass    # no file yet, or a broken one: use the defaults

    def get(self, key):
        return self.values.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        self.values[key] = value
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.values, f, indent=2)
        except OSError as e:
            print("could not save settings:", e)

    def speaks_category(self, name):
        return self.get("speak_messages") and name not in self.get("muted_categories")

    def toggle_category(self, name):
        muted = list(self.get("muted_categories"))
        if name in muted:
            muted.remove(name)
        else:
            muted.append(name)
        self.set("muted_categories", muted)
