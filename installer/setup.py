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
boxes, which screen readers read in full.

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

TITLE = "MB Access"
REPO = "Shehryar157/MBAccess"
ASSET = "MBAccess-Setup.exe"
GAME_NAME = "Mount & Blade: Warband"
GAME_FOLDER, GAME_EXE = "MountBlade Warband", "mb_warband.exe"
MOD_FOLDER, MOD_EXE = "MBAccess", "MBAccess.exe"
UNINSTALLER = "Uninstall MB Access.exe"
LOADER = "dinput8.dll"
CONFIG = "MBAccess.txt"
BACKUP = "dinput8.dll.before-mbaccess"
MARKER = "MBAccess.txt".encode("utf-16-le")     # found only in our loader
KEYS = "controls.dat"       # the game's key bindings, in %APPDATA%\Mount&Blade Warband
KEYS_BACKUP = "controls.dat.before-mbaccess"
KEEP = ("settings.json", "learned.json", "logs")    # the player's own: survive an update
HIDDEN = 0x08000000     # CREATE_NO_WINDOW

MB_OK, MB_YESNO, MB_OKCANCEL = 0x0, 0x4, 0x1
MB_ICONINFO, MB_ICONWARN, MB_ICONERROR, MB_ICONQUESTION = 0x40, 0x30, 0x10, 0x20
IDYES, IDOK = 6, 1
SILENT = "--silent" in sys.argv


def message(text, flags=MB_OK | MB_ICONINFO):
    if SILENT:
        print(text)
        return IDYES if flags & MB_YESNO else IDOK
    return ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags | 0x10000)  # 0x10000: in front


def announce(text):
    """Say a line without waiting for an answer (a message box would stop the setup):
    Windows' own voice, through PowerShell, in the background."""
    if SILENT:
        print(text)
        return
    script = ("Add-Type -AssemblyName System.Speech; "
              "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('%s')" % text.replace("'", "''"))
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-Command", script], creationflags=HIDDEN)
    except OSError:
        pass


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


ID_UPDATE, ID_SKIP, ID_NOTES = 1, 2, 100       # 1 and 2 are Windows' own OK and Cancel


def ask_update(version, notes):
    """The "update found" dialog: the two versions, what's new in a read-only multi-line
    box (focus starts there, so a screen reader can arrow through it), and Update and
    Skip buttons. Enter = Update, Escape = Skip. True to update.

    The dialog is described to Windows as a block of bytes (a dialog template: the
    window, then each control with its position, kind and text), the way a program's
    built-in dialogs are stored; Windows then runs it with its usual Tab and Enter keys."""
    if SILENT:
        print(f"update found: {version}\n{notes}")
        return True
    import struct
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    WS_CHILD, WS_VISIBLE, WS_TABSTOP, WS_BORDER, WS_VSCROLL = 0x40000000, 0x10000000, 0x10000, 0x800000, 0x200000
    BUTTON, EDIT, STATIC = 0x80, 0x81, 0x82
    ES_MULTILINE, ES_READONLY, ES_AUTOVSCROLL, BS_DEFPUSHBUTTON = 0x4, 0x800, 0x40, 0x1

    def text(s):
        return (s + "\0").encode("utf-16-le")

    def control(kind, style, x, y, w, h, ident, label):
        return (struct.pack("<IIhhhhHHH", style | WS_CHILD | WS_VISIBLE, 0, x, y, w, h, ident, 0xFFFF, kind)
                + text(label) + b"\0\0")

    heading = f"MB Access {version} is available. You have {VERSION}. What's new:"
    controls = [
        control(STATIC, 0, 7, 7, 286, 10, 101, heading),
        control(EDIT, ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL | WS_VSCROLL | WS_BORDER | WS_TABSTOP,
                7, 20, 286, 130, ID_NOTES, ""),
        control(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 180, 156, 54, 14, ID_UPDATE, "&Update"),
        control(BUTTON, WS_TABSTOP, 239, 156, 54, 14, ID_SKIP, "&Skip"),
    ]
    # Window: font set, modal frame, centred, brought to the front; popup with a title bar.
    style = 0x40 | 0x80 | 0x800 | 0x200 | 0x80000000 | 0xC00000 | 0x80000
    template = (struct.pack("<IIHhhhh", style, 0x8, len(controls), 0, 0, 300, 177) + b"\0\0\0\0"
                + text("MB Access update") + struct.pack("<H", 9) + text("Segoe UI"))
    for item in controls:
        template += b"\0" * (-len(template) % 4) + item      # each control starts on a 4-byte line

    DLGPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetDlgItemTextW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LPCWSTR]
    user32.EndDialog.argtypes = [wintypes.HWND, ctypes.c_ssize_t]
    user32.DialogBoxIndirectParamW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.HWND, DLGPROC, wintypes.LPARAM]
    user32.DialogBoxIndirectParamW.restype = ctypes.c_ssize_t
    body = "\r\n".join((notes or "No notes were written for this version.").splitlines())

    def handle(window, what, wparam, lparam):
        if what == 0x110:                   # the dialog is being set up
            user32.SetDlgItemTextW(window, ID_NOTES, body)
            return 1                        # let Windows focus the first control: the notes
        if what == 0x111 and wparam & 0xFFFF in (ID_UPDATE, ID_SKIP):    # a button, Enter or Escape
            user32.EndDialog(window, wparam & 0xFFFF)
            return 1
        return 0

    proc = DLGPROC(handle)
    return user32.DialogBoxIndirectParamW(None, ctypes.create_string_buffer(template), None, proc, 0) == ID_UPDATE


def newer_installer():
    """(version, download address, what's new) of a released installer newer than this
    one, or None. Any trouble (no internet, no release yet) means None: install what we
    carry. "What's new" is the description written on the GitHub release."""
    answer = os.path.join(tempfile.gettempdir(), "MBAccess-latest.json")
    try:
        download(f"https://api.github.com/repos/{REPO}/releases/latest", answer)
        with open(answer, encoding="utf-8") as f:
            release = json.load(f)
        if numbers(release["tag_name"]) <= numbers(VERSION):
            return None
        for asset in release["assets"]:
            if asset["name"] == ASSET:
                return (release["tag_name"].lstrip("v"), asset["browser_download_url"],
                        release.get("body") or "")
    except (OSError, ValueError, KeyError):
        pass
    return None


def update():
    """Offer a newer installer if there is one, and hand over to it if the player says
    Update. True = it has taken over. Skip installs the version we carry; the offer
    comes back the next time the setup is run."""
    found = newer_installer()
    if found is None:
        return False
    version, address, notes = found
    if not ask_update(version, notes):
        return False
    announce(f"Downloading MB Access {version}. Please wait.")
    target = os.path.join(tempfile.gettempdir(), f"MBAccess-Setup-{version}.exe")
    try:
        download(address, target + ".part")
        os.replace(target + ".part", target)
        subprocess.Popen([target, "--no-update"] + [a for a in sys.argv[1:] if a != "--no-update"])
    except OSError:
        return False        # the download failed: install the version we carry
    return True


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


def install():
    game = chosen_game_dir()
    if not game:
        message("Setup stopped: the game's folder wasn't chosen.", MB_OK | MB_ICONWARN)
        return
    if not wait_for_game_closed():
        return
    announce(f"Installing MB Access {VERSION}.")
    target = os.path.join(game, MOD_FOLDER)
    updating = os.path.exists(os.path.join(target, MOD_EXE))
    os.makedirs(target, exist_ok=True)
    # Replace the program's files; keep the player's settings and logs.
    for name in os.listdir(target):
        if name in KEEP or name == UNINSTALLER:
            continue
        path = os.path.join(target, name)
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    with zipfile.ZipFile(bundled("payload.zip")) as z:
        z.extractall(target)
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
    if not updating:
        install_keys()
    message(f"MB Access {VERSION} is {'updated' if updating else 'installed'}.\n\n"
            f"Start {GAME_NAME} from Steam as usual. The mod starts with it: it reads the "
            f'launcher, and says "MB Access {VERSION}" once the game itself is open.\n\n'
            + ("" if updating else "The game's keys are now set for keyboard play: Up arrow attacks, "
               "Down arrow defends, Page Up and Page Down change weapon and shield. You can "
               "change them on the game's Controls screen.\n\n") +
            "To update later, run this setup again.\n"
            f"To remove the mod, run \"{UNINSTALLER}\" in:\n{target}")


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
    except PermissionError as e:
        message(f"Windows refused to change a file:\n{e}\n\n"
                "Try running the setup again as administrator.", MB_OK | MB_ICONERROR)
    except Exception as e:  # show the problem rather than vanish silently
        message(f"Setup failed:\n{e!r}", MB_OK | MB_ICONERROR)


if __name__ == "__main__":
    main()
