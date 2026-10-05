"""MB Access: screen reader support for Mount & Blade games.

    python run.py               wait for Warband or With Fire & Sword, then speak menus
    pythonw run.py --with-game  started by the loader DLL: follow one game session,
                                log to logs\mbaccess.log, and exit when the game closes
"""
import ctypes
import os
import sys
import time

from mbaccess import click, help, keys, launcher, process, session, speech
from mbaccess.mem import Reader
from mbaccess.menu_watch import MenuWatcher

POLL_SECONDS = 0.05  # check the game 20 times a second
STARTUP_WAIT = 120   # --with-game: give up if the game hasn't appeared by then
HERE = os.path.dirname(os.path.abspath(__file__))


def setup_log():
    """pythonw has no console, so print() would go nowhere: use a log file."""
    os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
    log = open(os.path.join(HERE, "logs", "mbaccess.log"), "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log


def only_instance():
    """A named mutex is a system-wide name only one process can own at a time.

    If another MB Access already holds it, we're a second copy and should quit.
    We keep the handle for as long as we run; Windows releases it when we exit.
    """
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "MBAccess.SingleInstance")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def play_session(game):
    speech.say(f"Connected to {game.profile.title}.")
    launch = launcher.LauncherWatcher(speech.say)
    address, menus, next_locate = None, {}, 0
    window = {"hwnd": None, "checked": 0}

    def game_window():
        # Looking the window up costs a little, so do it once a second.
        if time.time() - window["checked"] > 1:
            window["hwnd"], window["checked"] = process.find_window(game.pid), time.time()
        return window["hwnd"]

    key_watch = keys.KeyWatcher(game_window)
    helper = help.Help(speech.say)

    # The main menu needs no campaign, so the watcher starts without one;
    # set_game hands it the campaign object once there is one.
    watcher = MenuWatcher(Reader(game), None, game.profile.game_offsets, [], speech.say,
                          screen=game.profile.screen, mouse=click.Mouse(game_window))
    while game.is_running():
        launch.poll()
        # The game object exists only once a campaign starts, and loading a
        # save replaces it, so look it up again every second (cheap with the
        # known pointer; a slow memory search when the pointer is unknown).
        if time.time() >= next_locate:
            interval = 1 if game.profile.game_offsets.get("cur_game_ptr") else 10
            next_locate = time.time() + interval
            found, module = session.locate(game)
            if found and found != address:
                address = found
                print(f"game object {address:#x}, module {module!r}")
                if module not in menus:
                    menus[module] = session.load_menus(game, module)
                watcher.set_game(address, menus[module])
                if not watcher.enabled:
                    speech.say("Menu reading isn't set up for this game version yet. "
                               "Run the discovery tool once.")
        pressed = key_watch.pressed()
        if helper.handle_keys(pressed):
            pressed = ()             # the help has the keys while it's open
        elif keys.F9 in pressed:
            helper.show("Inventory" if watcher.on_inventory() else "Menus and screens")
            pressed = ()
        watcher.poll(pressed)
        time.sleep(POLL_SECONDS)


def main():
    if not only_instance():
        return  # quietly: the running copy owns the speech
    with_game = "--with-game" in sys.argv
    if with_game:
        setup_log()
    else:
        speech.say("MB Access started. Waiting for the game.")
    started = time.time()
    while True:
        game = process.try_attach()
        if game is None:
            if with_game and time.time() - started > STARTUP_WAIT:
                return
            time.sleep(1)
            continue
        play_session(game)
        if with_game:
            return  # the loader starts us again with the next game launch
        speech.say("Game closed.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
