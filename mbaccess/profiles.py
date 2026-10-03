"""Per-game settings: what's different between Warband and With Fire & Sword.

Both games share all the code; a Profile only holds the differences, such
as the exe name and where fields sit inside the engine's objects. Offsets
found by tools/discover.py are saved in profiles/<key>.json and override
the defaults here, so updating them never means editing code.
"""
import json
import os
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(HERE, "profiles")

# Field offsets inside wb::game. None = not discovered yet; features that
# need a missing offset stay switched off.
DEFAULT_GAME_OFFSETS = {
    "savegame_name": 8,    # from the 1.153 headers; to verify in-game
    "module_name": 160,    # from the 1.153 headers; to verify in-game
    "cur_menu_text": None,
    "cur_menu_no": None,
}


@dataclass
class Profile:
    key: str
    title: str
    exe_names: tuple
    game_offsets: dict = field(default_factory=lambda: dict(DEFAULT_GAME_OFFSETS))

    @property
    def path(self):
        return os.path.join(PROFILE_DIR, self.key + ".json")

    def load(self):
        """Merge in offsets saved by the discovery tool, if any."""
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.game_offsets.update(json.load(f).get("game_offsets", {}))
        return self

    def save(self):
        os.makedirs(PROFILE_DIR, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"game_offsets": self.game_offsets}, f, indent=2)


# Exe names to be confirmed once the games are installed.
PROFILES = [
    Profile("warband", "Mount and Blade: Warband", ("mb_warband.exe",)),
    Profile("wfs", "With Fire and Sword", ("mb_wfas.exe",)),
]


def for_exe(exe_name):
    for profile in PROFILES:
        if exe_name.lower() in profile.exe_names:
            return Profile(profile.key, profile.title, profile.exe_names).load()
    return None
