"""MB Access installer, updater and uninstaller: one file the player runs and waits for.

MBAccess-Setup.exe:
  1. asks GitHub whether a newer installer has been released; if so it shows the new
     version and what's new, and on Update downloads that one and hands over to it (Skip
     installs the version this file carries);
  2. finds Mount & Blade: Warband through Steam (or asks for the folder);
  3. copies the mod into <game>\\MBAccess and puts the small auto-start loader
     (dinput8.dll) and MBAccess.txt next to the game, so the mod starts by itself
     whenever the game does. Settings and logs from an older version are kept;
  4. on a first install, replaces the game's key bindings with the mod's keyboard layout
     (installer/controls.dat), keeping the old ones for the uninstaller to put back.

Running it again later is how you update. The installed copy of this program,
"Uninstall MB Access.exe", removes it all again. Messages are standard Windows message
boxes, which screen readers read in full; downloading and installing show a progress
window with Cancel (installer/ui.py), and the end plays the Windows alert sound and says
"Done. Updated MB Access from <old> to <new>." (version.txt records the installed one).

  --no-update     skip step 1 (the newer installer starts this one with it)
  --game <dir>    install into this folder instead of looking for the game (testing)
  --keys <dir>    put the key layout there instead of the game's settings folder (testing)
  --silent        print messages instead of showing them, answer yes (testing)
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # run from source
from mbaccess import VERSION, steam  # noqa: E402
import ui  # noqa: E402     the installer's windows (installer/ui.py)

TITLE = "MB Access"
REPO = "Shehryar157/MBAccess"
ASSET = "MBAccess-Setup.exe"
GAME_NAME = "Mount & Blade: Warband"
GAME_FOLDER, GAME_EXE = "MountBlade Warband", "mb_warband.exe"
MOD_FOLDER, MOD_EXE = "MBAccess", "MBAccess.exe"
UNINSTALLER = "Uninstall MB Access.exe"
VERSION_FILE = "version.txt"    # in <game>\MBAccess: which version is installed
LOADER = "dinput8.dll"
CONFIG = "MBAccess.txt"
BACKUP = "dinput8.dll.before-mbaccess"
MARKER = "MBAccess.txt".encode("utf-16-le")     # found only in our loader
KEYS = "controls.dat"       # the game's key bindings, in %APPDATA%\Mount&Blade Warband
KEYS_BACKUP = "controls.dat.before-mbaccess"
KEEP = ("settings.json", "learned.json", "logs")    # the player's own: survive an update
HIDDEN = 0x08000000     # CREATE_NO_WINDOW

MB_OK, MB_YESNO, MB_OKCANCEL, MB_DEFBUTTON2 = 0x0, 0x4, 0x1, 0x100   # DEFBUTTON2: Enter = No
MB_ICONINFO, MB_ICONWARN, MB_ICONERROR, MB_ICONQUESTION = 0x40, 0x30, 0x10, 0x20
IDYES, IDOK = 6, 1
SILENT = "--silent" in sys.argv


def message(text, flags=MB_OK | MB_ICONINFO):
    if SILENT:
        print(text)
        return IDYES if flags & MB_YESNO else IDOK
    return ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags | 0x10000)  # 0x10000: in front


def bundled(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def numbers(version):
    """ "v0.10.1" -> (0, 10, 1), so versions compare as numbers, not as text."""
    return tuple(int(part) for part in version.lstrip("v").split(".") if part.isdigit())


def download(address, path):
    """Fetch a web address into a file with Windows' own downloader (urlmon, what
    Explorer uses), so the installer needn't carry Python's 6 MB of encryption code.
    Raises OSError when it fails."""
    ctypes.windll.wininet.DeleteUrlCacheEntryW(address)     # never an old, remembered answer
    if ctypes.windll.urlmon.URLDownloadToFileW(None, address, path, 0, None) != 0:
        raise OSError(f"could not download {address}")


def fetch(address, path, progress):
    """Download a big file in pieces (WinINet, Windows' web library), reporting each
    piece to the progress window and stopping at Cancel. Raises OSError when it fails,
    ui.Cancelled when the player cancels; either way no half file is left behind."""
    from ctypes import wintypes
    net = ctypes.windll.wininet
    net.InternetOpenW.restype = net.InternetOpenUrlW.restype = ctypes.c_void_p
    net.InternetOpenUrlW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                     wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    net.HttpQueryInfoW.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                   ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    net.InternetReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD)]
    net.InternetCloseHandle.argtypes = [ctypes.c_void_p]
    session = net.InternetOpenW("MBAccess-Setup", 0, None, None, 0)
    # Always fresh from the server, not from the cache.
    url = net.InternetOpenUrlW(session, address, None, 0, 0x80000000 | 0x04000000, 0) if session else None
    try:
        if not url:
            raise OSError(f"could not download {address}")
        number, size = wintypes.DWORD(), wintypes.DWORD(4)
        as_number = 0x20000000
        net.HttpQueryInfoW(url, 19 | as_number, ctypes.byref(number), ctypes.byref(size), None)
        if number.value != 200:                                     # 19 = status code
            raise OSError(f"the server answered {number.value} for {address}")
        size.value = 4
        total = number.value if net.HttpQueryInfoW(url, 5 | as_number, ctypes.byref(number),
                                                   ctypes.byref(size), None) else 0   # 5 = length
        piece, got, done = ctypes.create_string_buffer(65536), wintypes.DWORD(), 0
        with open(path, "wb") as out:
            while True:
                progress.check()
                if not net.InternetReadFile(url, piece, len(piece), ctypes.byref(got)):
                    raise OSError(f"the download of {address} broke off")
                if not got.value:
                    break
                out.write(piece.raw[:got.value])
                done += got.value
                megabytes = f"{done / 1e6:.1f}" + (f" of {total / 1e6:.1f}" if total else "")
                progress.update(done / total if total else None, f"Downloaded {megabytes} MB")
    except BaseException:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    finally:
        for handle in (url, session):
            if handle:
                net.InternetCloseHandle(handle)


def current_install():
    """The installed version (from version.txt), found quietly: through --game or Steam,
    never a dialog. None when the mod isn't installed, the game isn't found that way,
    or it was installed by 0.1.1 or earlier (they didn't record their version)."""
    game = (os.path.normpath(sys.argv[sys.argv.index("--game") + 1]) if "--game" in sys.argv
            else steam.find_game(GAME_FOLDER, GAME_EXE))
    return installed_version(os.path.join(game, MOD_FOLDER)) if game else None


def newest(*versions):
    """The highest of these versions (None ones ignored), compared as numbers."""
    return max((v for v in versions if v), key=numbers)


def newer_installer(have):
    """(version, download address, what's new) of a released installer newer than
    `have` (the newer of the installed version and this setup's), or None. Any trouble
    (no internet, no release yet) means None: install what we carry. "What's new" is
    the description written on the GitHub release."""
    answer = os.path.join(tempfile.gettempdir(), "MBAccess-latest.json")
    try:
        download(f"https://api.github.com/repos/{REPO}/releases/latest", answer)
        with open(answer, encoding="utf-8") as f:
            release = json.load(f)
        if numbers(release["tag_name"]) <= numbers(have):
            return None
        for asset in release["assets"]:
            if asset["name"] == ASSET:
                return (release["tag_name"].lstrip("v"), asset["browser_download_url"],
                        (release.get("body") or "").lstrip("\ufeff"))   # no byte-order mark
    except (OSError, ValueError, KeyError):
        pass
    return None


def update():
    """Offer a newer installer if there is one, and hand over to it if the player says
    Update. True = it has taken over. Skip installs the version we carry; the offer
    comes back the next time the setup is run."""
    installed = current_install()
    found = newer_installer(newest(installed, VERSION))
    if found is None:
        return False
    version, address, notes = found
    have = f"You have {installed}." if installed else f"This setup is {VERSION}."
    if SILENT:
        print(f"update found: {version}. {have}\n{notes}")
    elif not ui.ask_update(version, notes, have):
        return False
    target = os.path.join(tempfile.gettempdir(), f"MBAccess-Setup-{version}.exe")
    progress = ui.Progress(f"Downloading MB Access {version}", f"Downloading MB Access {version}",
                           "Stop downloading the update? Nothing has been changed.", SILENT)
    try:
        progress.run(lambda p: fetch(address, target + ".part", p))
        os.replace(target + ".part", target)
        subprocess.Popen([target, "--no-update"] + [a for a in sys.argv[1:] if a != "--no-update"])
    except OSError:
        return False        # the download failed: install the version we carry
    return True             # ui.Cancelled passes through to main(): stop, nothing changed


def is_running(exe):
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"],
                         capture_output=True, text=True, creationflags=HIDDEN).stdout
    return exe.lower() in out.lower()


def wait_for_game_closed():
    while is_running(GAME_EXE):
        if message(f"{GAME_NAME} is running. Please close it, then press OK.\n\n"
                   "Cancel stops the setup.", MB_OKCANCEL | MB_ICONWARN) != IDOK:
            return False
    # The mod closes with the game; stop a copy that's still running anyway.
    subprocess.run(["taskkill", "/F", "/IM", MOD_EXE], capture_output=True, creationflags=HIDDEN)
    return True


def is_game_dir(folder):
    return os.path.exists(os.path.join(folder, GAME_EXE))


def browse_for_folder(title):
    """Windows' standard "Browse for folder" tree; the chosen path, or None."""
    from ctypes import wintypes

    class BROWSEINFO(ctypes.Structure):
        _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p),
                    # A buffer Windows writes into: a pointer field takes a ctypes array,
                    # LPWSTR (c_wchar_p) only takes a str and raised TypeError.
                    ("pszDisplayName", ctypes.POINTER(ctypes.c_wchar)), ("lpszTitle", wintypes.LPCWSTR),
                    ("ulFlags", wintypes.UINT), ("lpfn", ctypes.c_void_p),
                    ("lParam", wintypes.LPARAM), ("iImage", ctypes.c_int)]

    shell32, ole32 = ctypes.windll.shell32, ctypes.windll.ole32
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize(None)
    name = ctypes.create_unicode_buffer(260)
    info = BROWSEINFO(None, None, name, title, 0x1 | 0x40, None, 0, 0)   # folders only, new style
    chosen = shell32.SHBrowseForFolderW(ctypes.byref(info))
    if not chosen:
        return None
    path = ctypes.create_unicode_buffer(1024)
    ok = shell32.SHGetPathFromIDListW(chosen, path)
    ole32.CoTaskMemFree(chosen)
    return os.path.normpath(path.value) if ok else None


def ask_for_game_dir():
    message(f"{GAME_NAME} wasn't found through Steam.\n\n"
            f"Next, choose the game's folder: the one that contains {GAME_EXE}.")
    while True:
        folder = browse_for_folder(f"{GAME_NAME} folder")
        if not folder:
            return None
        if is_game_dir(folder):
            return folder
        if message(f"{GAME_EXE} isn't in that folder. Choose again?", MB_YESNO | MB_ICONWARN) != IDYES:
            return None


def chosen_game_dir():
    if "--game" in sys.argv:
        return os.path.normpath(sys.argv[sys.argv.index("--game") + 1])
    return steam.find_game(GAME_FOLDER, GAME_EXE) or ask_for_game_dir()


def is_our_loader(path):
    try:
        with open(path, "rb") as f:
            return MARKER in f.read()
    except OSError:
        return False


def keys_folder():
    if "--keys" in sys.argv:        # testing: somewhere other than the real one
        return sys.argv[sys.argv.index("--keys") + 1]
    return os.path.join(os.environ["APPDATA"], "Mount&Blade Warband")


def install_keys():
    """Give the game the mod's key layout (attack and defend on Up and Down, next weapon
    and shield on Page Up and Page Down: the keyboard instead of the mouse). Only on a
    first install, so keys the player changes later survive updates; their old layout
    is kept beside it and comes back on uninstall."""
    folder = keys_folder()
    os.makedirs(folder, exist_ok=True)
    keys, backup = os.path.join(folder, KEYS), os.path.join(folder, KEYS_BACKUP)
    if os.path.exists(keys) and not os.path.exists(backup):
        shutil.copy2(keys, backup)
    shutil.copy2(bundled(KEYS), keys)


def restore_keys():
    folder = keys_folder()
    keys, backup = os.path.join(folder, KEYS), os.path.join(folder, KEYS_BACKUP)
    if os.path.exists(backup):
        os.replace(backup, keys)


def installed_version(target):
    """The version an earlier setup installed (it writes VERSION_FILE), or None."""
    try:
        with open(os.path.join(target, VERSION_FILE), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def put_in_place(progress, game, target, updating):
    """Unpack the mod beside the installed one (<game>\\MBAccess.new), the slow part,
    which Cancel can stop without harm: the half-unpacked folder is simply deleted. Then
    swap the new files in and set up the loader: a second's work that Cancel can't break.
    Progress is counted in bytes, so one big file moves the bar as much as it should."""
    staging = target + ".new"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with zipfile.ZipFile(bundled("payload.zip")) as z:
            files = [info for info in z.infolist() if not info.is_dir()]
            total, done = sum(info.file_size for info in files) or 1, 0
            for number, info in enumerate(files, 1):
                status = f"Copying files: {number} of {len(files)}"
                path = os.path.join(staging, *info.filename.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with z.open(info) as source, open(path, "wb") as out:
                    while piece := source.read(1 << 20):
                        out.write(piece)
                        done += len(piece)
                        progress.update(0.95 * done / total, status)
                        progress.check()
        progress.finishing("Finishing")
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    # Replace the program's files; keep the player's settings and logs.
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(target):
        if name in KEEP or name == UNINSTALLER:
            continue
        path = os.path.join(target, name)
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    for name in os.listdir(staging):
        os.replace(os.path.join(staging, name), os.path.join(target, name))
    os.rmdir(staging)
    # The loader goes next to the game, where the game looks for dinput8.dll.
    loader = os.path.join(game, LOADER)
    if os.path.exists(loader) and not is_our_loader(loader):
        shutil.move(loader, os.path.join(game, BACKUP))     # someone else's: keep it
    shutil.move(os.path.join(target, LOADER), loader)
    # The loader starts the command in MBAccess.txt, in the game's folder.
    with open(os.path.join(game, CONFIG), "w", encoding="utf-8") as f:
        f.write(f'"{os.path.join(target, MOD_EXE)}" --with-game\n')
    if getattr(sys, "frozen", False):
        shutil.copy2(sys.executable, os.path.join(target, UNINSTALLER))
    with open(os.path.join(target, VERSION_FILE), "w", encoding="utf-8") as f:
        f.write(VERSION)    # the next update reads it: "Updated from <this> to <that>"
    if not updating:
        install_keys()
    progress.update(0.97, "Making footsteps louder")
    try:        # the mod does it again at every start, so a failure here only delays it
        subprocess.run([os.path.join(target, MOD_EXE), "--footsteps", game], timeout=120,
                       creationflags=HIDDEN)
    except (OSError, subprocess.SubprocessError):
        pass
    progress.update(1.0, "Done")


def install():
    game = chosen_game_dir()
    if not game:
        message("Setup stopped: the game's folder wasn't chosen.", MB_OK | MB_ICONWARN)
        return
    if not wait_for_game_closed():
        return
    target = os.path.join(game, MOD_FOLDER)
    updating = os.path.exists(os.path.join(target, MOD_EXE))
    old_version = installed_version(target) if updating else None
    if old_version and numbers(old_version) > numbers(VERSION):
        if message(f"MB Access {old_version} is installed, and this setup is {VERSION}, an older "
                   f"version.\n\nInstall {VERSION} anyway?",
                   MB_YESNO | MB_ICONWARN | MB_DEFBUTTON2) != IDYES:
            return
    elif old_version == VERSION:
        if message(f"MB Access {VERSION} is already installed and up to date.\n\nInstall it again?",
                   MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES:
            return
    progress = ui.Progress(f"Installing MB Access {VERSION}", f"Installing MB Access {VERSION}",
                           "Stop installing? Nothing has been changed yet.", SILENT)
    progress.run(lambda p: put_in_place(p, game, target, updating))
    if not SILENT:
        ui.alert()      # the player's Windows alert sound: done
    if updating:
        if old_version == VERSION:
            done = f"Done. MB Access {VERSION} was installed again."
        elif old_version and numbers(old_version) > numbers(VERSION):
            done = f"Done. MB Access went back from {old_version} to {VERSION}."
        elif old_version:
            done = f"Done. Updated MB Access from {old_version} to {VERSION}."
        else:       # installed by 0.1.1 or earlier, which didn't record their version
            done = f"Done. Updated MB Access to {VERSION}."
        message(done, MB_OK)        # no icon: the alert above was its sound
        return
    message(f"Done. MB Access {VERSION} is installed.\n\n"
            f"Start {GAME_NAME} from Steam as usual. The mod starts with it: it reads the "
            f'launcher, and says "MB Access {VERSION}" once the game itself is open.\n\n'
            "The game's keys are now set for keyboard play: Up arrow attacks, "
            "Down arrow defends, Page Up and Page Down change weapon and shield. You can "
            "change them on the game's Controls screen.\n\n"
            "To update later, run this setup again.\n"
            f"To remove the mod, run \"{UNINSTALLER}\" in:\n{target}", MB_OK)


def restore_footsteps(game):
    """Undo the mod's louder footsteps (mbaccess/footsteps.py, which this small program
    doesn't carry): each module's original sounds.txt back, the louder copies deleted."""
    import glob
    for sounds in glob.glob(os.path.join(game, "Modules", "*", "sounds.txt")):
        backup = sounds + ".mbaccess-backup"
        try:
            if os.path.exists(backup):
                with open(sounds, encoding="latin-1") as f:
                    ours = "mbaccess_" in f.read()
                if ours:        # else the game already has a fresh original
                    shutil.copyfile(backup, sounds)
                os.remove(backup)
            for place in (os.path.join(game, "Sounds"), os.path.join(os.path.dirname(sounds), "Sounds")):
                for path in glob.glob(os.path.join(place, "mbaccess_*.wav")):
                    os.remove(path)
        except OSError:
            pass


def uninstall():
    game = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
    if "--game" in sys.argv:
        game = chosen_game_dir()
    elif not is_game_dir(game):
        game = steam.find_game(GAME_FOLDER, GAME_EXE)
    if not game:
        message("The game's folder wasn't found, so nothing was removed.", MB_OK | MB_ICONWARN)
        return
    if message(f"Remove MB Access from {GAME_NAME}?\n\nYour MB Access settings are removed too.",
               MB_YESNO | MB_ICONQUESTION) != IDYES:
        return
    if not wait_for_game_closed():
        return
    loader = os.path.join(game, LOADER)
    if is_our_loader(loader):
        os.remove(loader)
    if os.path.exists(os.path.join(game, BACKUP)) and not os.path.exists(loader):
        shutil.move(os.path.join(game, BACKUP), loader)
    for name in (CONFIG, "MBAccess_loader.log"):
        try:
            os.remove(os.path.join(game, name))
        except OSError:
            pass
    restore_keys()
    restore_footsteps(game)
    target = os.path.join(game, MOD_FOLDER)
    message("MB Access has been removed.")
    # This program is inside the folder being deleted: let cmd remove it a moment
    # after we exit.
    subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & rmdir /s /q "{target}"', creationflags=HIDDEN)


def main():
    name = os.path.basename(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
    try:
        if "--uninstall" in sys.argv or name.lower().startswith("uninstall"):
            uninstall()
        elif "--no-update" in sys.argv or not update():
            install()
    except ui.Cancelled:
        pass            # the player confirmed Cancel: nothing was changed, nothing to say
    except PermissionError as e:
        message(f"Windows refused to change a file:\n{e}\n\n"
                "Try running the setup again as administrator.", MB_OK | MB_ICONERROR)
    except Exception as e:  # show the problem rather than vanish silently
        message(f"Setup failed:\n{e!r}", MB_OK | MB_ICONERROR)


if __name__ == "__main__":
    main()
