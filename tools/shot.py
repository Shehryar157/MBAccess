import sys; sys.path.insert(0, r"E:\code\mods\CFCAccess\tools"); sys.path.insert(0, r"E:\code\mods\MBAccess")
import win
from mbaccess import process
g = process.try_attach(); h = process.find_window(g.pid)
win.screenshot(h, sys.argv[1])
