"""Where the mod's own files are: run from source, or as the installed MBAccess.exe.

PyInstaller unpacks the files packed with the program into sys._MEIPASS (the _internal
folder), which the installer replaces on every update. What the player's copy writes
(settings, what it learned about screens, logs) lives next to MBAccess.exe instead.
"""
import os
import sys

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    DATA = sys._MEIPASS
    USER = os.path.dirname(sys.executable)
else:
    DATA = USER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
