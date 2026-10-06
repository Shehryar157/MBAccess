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


def find_window(pid):
    """The process's visible top-level window, or None."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and _user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    _user32.EnumWindows(callback, 0)
    return found[0] if found else None


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
