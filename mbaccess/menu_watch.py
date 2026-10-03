"""Speaking game menus (the town, village and event menus) when they change.

We poll: every tick we read the current menu number and its text (with the
game's variables already filled in, e.g. "You are in Praven"), and speak
when either changes. The menu's name and options come from menus.txt,
indexed by the menu number.
"""
from . import text as text_mod
from .mem import ReadError


class MenuWatcher:
    def __init__(self, reader, game_address, offsets, menus, say):
        self.reader = reader
        self.game = game_address
        self.offsets = offsets
        self.menus = menus
        self.say = say
        self.last = None

    @property
    def enabled(self):
        return self.offsets.get("cur_menu_no") is not None and \
            self.offsets.get("cur_menu_text") is not None

    def read_state(self):
        number = self.reader.i32(self.game + self.offsets["cur_menu_no"])
        body = self.reader.rgl_string(self.game + self.offsets["cur_menu_text"])
        return number, body

    def describe(self, number, body):
        parts = [text_mod.clean(body)]
        if 0 <= number < len(self.menus):
            options = [text_mod.clean(i.text) for i in self.menus[number].items]
            # Until we read the visible options from the screen, list the
            # menu's possible options (some may be hidden in-game).
            if options:
                parts.append("Options: " + "; ".join(o for o in options if o))
        return "\n".join(p for p in parts if p)

    def poll(self):
        if not self.enabled:
            return
        try:
            state = self.read_state()
        except ReadError:
            return  # mid-update or loading; try again next tick
        if state != self.last:
            self.last = state
            self.say(self.describe(*state))
