"""Explore screens through the mod's own reader.

    python tools/drive.py                 print what the mod reads on the top screen
    python tools/drive.py "Load Game"     press that item first (brings the game to
                                          the front and clicks it), then print

The label match is a case-insensitive prefix of the item's spoken text.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, r"E:\code\mods\CFCAccess\tools")
from mbaccess import click, keys, process, session
from mbaccess.mem import Reader
from mbaccess.menu_watch import MenuWatcher

game = process.try_attach()
hwnd = process.find_window(game.pid)
said = []
w = MenuWatcher(Reader(game), None, game.profile.game_offsets, [], said.append,
                screen=game.profile.screen, mouse=click.Mouse(lambda: hwnd))
found, module = session.locate(game)
if found:
    w.set_game(found, session.load_menus(game, module))
w.poll()

if len(sys.argv) > 1:
    import win
    win.focus(hwnd)
    time.sleep(0.3)
    want = sys.argv[1].lower()
    match = [n for n, i in enumerate(w.options) if i.spoken().lower().startswith(want)]
    if not match:
        sys.exit(f"no item starting with {sys.argv[1]!r}")
    w.cursor = match[0]
    w.poll([keys.RETURN])
    for _ in range(40):
        w.poll()
        time.sleep(0.05)
    time.sleep(0.5)
    said.clear()
    w.last = None
    w.poll()
    click.Mouse(lambda: hwnd).hover(0.99, 0.74)   # park the mouse in a corner

print("top window:", w.top_window())
print("SAY:", said[-1] if said else None)
for n, item in enumerate(w.options, 1):
    print(f"{n:3} {item.spoken()}{'' if item.visible() else '  (scrolled away)'}")
