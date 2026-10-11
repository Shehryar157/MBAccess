"""Finding the running game (Warband or With Fire & Sword) and reading it.

pymem wraps the Windows functions OpenProcess and ReadProcessMemory, which
let one program read another program's memory with the user's own
permissions. A Game object is a memory "source" for mem.Reader: it has
read(address, length) and regions().
"""
import ctypes
import os
from ctypes import wintypes

import pymem
import pymem.exception
import pymem.process

from . import profiles, regions
from .mem import ReadError

_user32 = ctypes.WinDLL("user32")
_read_memory = ctypes.WinDLL("kernel32").ReadProcessMemory
_read_memory.argtypes = (wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
                         ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
_read_memory.restype = wintypes.BOOL


class Game:
    def __init__(self, pm, exe_name, profile):
        self.pm = pm
        self.profile = profile
        module = pymem.process.module_from_name(pm.process_handle, exe_name)
        self.base = module.lpBaseOfDll
        # The game folder, e.g. ...\steamapps\common\MountBlade Warband
        self.folder = os.path.dirname(module.filename)

    @property
    def pid(self):
        return self.pm.process_id

    def read(self, address, length):
        # ReadProcessMemory directly: pymem's read_bytes does the same with
        # extra checks and conversions, and this is the mod's busiest call.
        buffer = ctypes.create_string_buffer(length)
        got = ctypes.c_size_t()
        if not _read_memory(self.pm.process_handle, address, buffer, length, ctypes.byref(got)) \
                or got.value != length:
            raise ReadError(f"{address:#x}+{length}: unreadable")
        return buffer.raw

    def write(self, address, data):
        """WriteProcessMemory, through pymem (we opened the game with full access)."""
        self.pm.write_bytes(address, bytes(data), len(data))

    def regions(self):
        """(start, size) of the writable memory regions: where game data lives."""
        return [(start, size) for start, size, _ in regions.regions(self.pm.process_handle)]

    def is_running(self):
        try:
            self.read(self.base, 2)
            return True
        except ReadError:
            return False

    def module_names(self):
        """Folders in <game>\Modules: the modules the game can load."""
        path = os.path.join(self.folder, "Modules")
        return sorted(os.listdir(path)) if os.path.isdir(path) else []


_user32.GetForegroundWindow.restype = wintypes.HWND
_seen_windows = set()   # window line-ups already written to the log


def _owner(hwnd):
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _describe(hwnd):
    """A window's class and size, for the log (no title: nothing private)."""
    name = ctypes.create_unicode_buffer(64)
    _user32.GetClassNameW(hwnd, name, 64)
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return f"{name.value} {rect.right - rect.left}x{rect.bottom - rect.top}"


def pick_window(windows, front):
    """Which of the game's visible windows (handle, area) is the game itself?
    The one in front if it's one of them: that's where the keys go. Otherwise
    the biggest. A game process can own other visible windows (an input
    method's little bar, an overlay), and taking simply the first one made the
    mod think the game was never in front. Pure choice, tested."""
    if not windows:
        return None
    if front in [hwnd for hwnd, _ in windows]:
        return front
    return max(windows, key=lambda w: w[1])[0]


def find_window(pid):
    """The process's game window (visible, top-level), or None."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if _owner(hwnd) == pid and _user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append((hwnd, (rect.right - rect.left) * (rect.bottom - rect.top)))
        return True

    _user32.EnumWindows(callback, 0)
    if len(found) > 1:
        # Rare, and the suspected cause of "arrows only work once after Alt+Tab"
        # (a player's report, 2026-10-11, unconfirmed): note each
        # new line-up once, so a player's log shows what the extra windows were.
        line_up = tuple(sorted(_describe(hwnd) for hwnd, _ in found))
        if line_up not in _seen_windows:
            _seen_windows.add(line_up)
            print("game windows:", "; ".join(line_up))
    return pick_window(found, _user32.GetForegroundWindow())


def try_attach():
    """Return a Game for the first supported game with a window, else None."""
    for proc in pymem.process.list_processes():
        exe = proc.szExeFile.decode(errors="replace")
        profile = profiles.for_exe(exe)
        if profile is None or find_window(proc.th32ProcessID) is None:
            continue
        try:
            pm = pymem.Pymem()
            pm.open_process_from_id(proc.th32ProcessID)
            return Game(pm, exe, profile)
        except (pymem.exception.ProcessNotFound, pymem.exception.CouldNotOpenProcess):
            continue
    return None
