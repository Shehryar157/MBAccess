"""Passive probe: why does the player keep moving after a movement key is let go?

For each release of W/A/S/D it prints three times:
- finger up: our own low-level hook. The newest hook runs FIRST, so this sees the key
  before the mod's hook does.
- passed on: when Windows' key state shows the key up, i.e. every hook (the mod's
  included) has let the release through. The gap = the mod's delay.
- stopped: when the player's position stops changing (game momentum).

    python tools/move_probe.py [seconds, default 40]
"""
import ctypes
import math
import os
import sys
import threading
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process, walls
from mbaccess.mem import Reader

user32 = ctypes.WinDLL("user32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = LRESULT
user32.GetAsyncKeyState.restype = ctypes.c_short
MOVE = {0x57: "W", 0x41: "A", 0x53: "S", 0x44: "D"}
releases = []                       # (key, time the finger came up)


def on_key(code, wparam, lparam):
    if code == 0 and wparam == 0x101:   # WM_KEYUP
        vk = ctypes.cast(lparam, ctypes.POINTER(ctypes.c_uint32))[0]
        if vk in MOVE:
            releases.append((vk, time.perf_counter()))
    return user32.CallNextHookEx(None, code, wparam, lparam)


proc = HOOKPROC(on_key)


def pump():
    user32.SetWindowsHookExW(13, proc, None, 0)     # WH_KEYBOARD_LL
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        pass


threading.Thread(target=pump, daemon=True).start()
game = process.try_attach()
r = Reader(game)
mission = walls.mission_address(r, game.profile)
end = time.time() + (float(sys.argv[1]) if len(sys.argv) > 1 else 40)
pending = []        # [key, up time, passed time or None, last pos, last moved time]
last = None
print("recording: walk or ride, press and release W/A/S/D a few times")
while time.time() < end:
    now = time.perf_counter()
    p = walls.find_player(r, mission)
    while releases:
        vk, t = releases.pop(0)
        pending.append([vk, t, None, p, now])
    for item in list(pending):
        vk, t_up, t_pass, pos0, moved = item
        if t_pass is None and not (user32.GetAsyncKeyState(vk) & 0x8000):
            item[2] = t_pass = now
        if p and last and math.hypot(p[0] - last[0], p[1] - last[1]) > 0.005:
            item[4] = now                   # still moving
        if t_pass is not None and now - item[4] > 0.3:     # still for 0.3 s: stopped
            gone = math.hypot(last[0] - pos0[0], last[1] - pos0[1]) if pos0 and last else 0
            print("%s: mod passed the release after %4.0f ms; moving stopped %4.0f ms after "
                  "the finger came up, %.2f m further%s" % (
                      MOVE[vk], (t_pass - t_up) * 1000, (item[4] - t_up) * 1000, gone,
                      " (horse)" if p and p[4] else ""))
            pending.remove(item)
    last = p
    time.sleep(0.01)
