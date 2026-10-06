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
    # Fixed addresses and widget offsets for reading what's on screen
    # (menu buttons and so on). Empty = not found yet for this version.
    screen: dict = field(default_factory=dict)
    # The game's settings folder inside Documents (rgl_config.txt lives there).
    config_dir: str = ""

    @property
    def config_file(self):
        docs = os.path.join(os.path.expanduser("~"), "Documents")
        return os.path.join(docs, self.config_dir, "rgl_config.txt")

    @property
    def path(self):
        return os.path.join(PROFILE_DIR, self.key + ".json")

    def load(self):
        """Merge in offsets saved by the discovery tool, if any."""
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.game_offsets.update(data.get("game_offsets", {}))
            self.screen.update(data.get("screen", {}))
        return self

    def save(self):
        os.makedirs(PROFILE_DIR, exist_ok=True)
        data = {}
        if os.path.exists(self.path):  # keep anything else in the file
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        data["game_offsets"] = self.game_offsets
        if self.screen:
            data["screen"] = self.screen
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


# Exe names to be confirmed once the games are installed.
PROFILES = [
    Profile("warband", "Mount and Blade: Warband", ("mb_warband.exe",),
            config_dir="Mount&Blade Warband"),
    Profile("wfs", "With Fire and Sword", ("mb_wfas.exe",),
            config_dir="Mount&Blade With Fire and Sword"),
]


def for_exe(exe_name):
    for profile in PROFILES:
        if exe_name.lower() in profile.exe_names:
            return Profile(profile.key, profile.title, profile.exe_names,
                           config_dir=profile.config_dir).load()
    return None
