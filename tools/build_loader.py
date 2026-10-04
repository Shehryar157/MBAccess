"""Build and install the dinput8.dll loader that starts the mod with the game.

  python tools/build_loader.py build      compile loader/dinput8.dll (32-bit) with zig cc
  python tools/build_loader.py install    build, then copy into every installed game's folder
  python tools/build_loader.py uninstall  remove our files from the game folders

Both games import dinput8.dll and Windows looks in the game's own folder
first, so our copy is loaded; it forwards everything to the real one and
starts the command in MBAccess.txt. The games are 32-bit programs, so the
DLL must be 32-bit too (target x86).
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import winreg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIG = r"E:\code\mods\tools\zig\zig.exe"
LOADER = os.path.join(ROOT, "loader")
DLL = os.path.join(LOADER, "dinput8.dll")
OUR_FILES = ["dinput8.dll", "MBAccess.txt", "MBAccess_loader.log"]
# Folder name under steamapps\common -> the exe that proves it's the game.
GAMES = {"MountBlade Warband": "mb_warband.exe",
         "Mount & Blade With Fire and Sword": "mb_wfas.exe"}


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


def game_dirs():
    found = []
    for library in steam_libraries():
        for folder, exe in GAMES.items():
            path = os.path.normcase(os.path.join(library, "steamapps", "common", folder))
            if os.path.exists(os.path.join(path, exe)) and path not in found:
                found.append(path)
    return found


def build():
    subprocess.run([ZIG, "cc", "-target", "x86-windows-gnu", "-shared", "-O2",
                    "-o", DLL, "dinput8.c", "dinput8.def"], cwd=LOADER, check=True)
    print(f"built {DLL}")


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def install():
    build()
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    command = f'"{pythonw}" "{os.path.join(ROOT, "run.py")}" --with-game'
    for game in game_dirs():
        target = os.path.join(game, "dinput8.dll")
        marker = os.path.join(game, "MBAccess.txt")
        # Never overwrite somebody else's dinput8.dll (e.g. another mod's).
        if os.path.exists(target) and not os.path.exists(marker):
            print(f"skipped {game}: its dinput8.dll isn't ours")
            continue
        shutil.copyfile(DLL, target)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(command + "\n")
        assert sha(DLL) == sha(target)
        print(f"installed {target}")
    print(f"MBAccess.txt: {command}")


def uninstall():
    for game in game_dirs():
        for name in OUR_FILES:
            path = os.path.join(game, name)
            if os.path.exists(path):
                os.remove(path)
                print(f"removed {path}")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "build"
    {"build": build, "install": install, "uninstall": uninstall}[action]()
