"""Finding a Steam game's folder: Steam's own list of library folders, from the registry."""
import os
import re
import winreg


def steam_libraries():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam = winreg.QueryValueEx(key, "SteamPath")[0]
    except OSError:
        return []
    libraries = [steam]
    try:
        with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8") as f:
            libraries += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', f.read())]
    except OSError:
        pass
    return libraries


def find_game(folder, exe):
    """The game's folder (steamapps\\common\\<folder>, holding <exe>) or None."""
    for library in steam_libraries():
        path = os.path.normpath(os.path.join(library, "steamapps", "common", folder))
        if os.path.exists(os.path.join(path, exe)):
            return path
    return None
