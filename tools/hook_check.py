"""Check the key hook process starts, takes key ownership flags, and stops.

    python tools/hook_check.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import keys

if __name__ == "__main__":
    t = time.perf_counter()
    w = keys.watcher(lambda: 0)
    print(type(w).__name__, w.ok, "started in %.2f s" % (time.perf_counter() - t))
    w.swallow = {keys.KEY_J}
    w.swallow_shifted = {keys.KEY_A}
    print("flags J, A:", w.flags[keys.KEY_J], w.flags[keys.KEY_A])
    w.swallow = set()
    print("J after release:", w.flags[keys.KEY_J], "pressed:", w.pressed())
