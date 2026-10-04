"""MB Access: screen reader support for Mount & Blade games.

    python run.py    wait for Warband or With Fire & Sword, then speak menus
"""
import time

from mbaccess import launcher, process, session, speech
from mbaccess.mem import Reader
from mbaccess.menu_watch import MenuWatcher

POLL_SECONDS = 0.05  # check the game 20 times a second


def play_session(game):
    speech.say(f"Connected to {game.profile.title}.")
    launch = launcher.LauncherWatcher(speech.say)
    address, watcher, menus, next_locate = None, None, {}, 0
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
                watcher = MenuWatcher(Reader(game), address, game.profile.game_offsets,
                                      menus[module], speech.say)
                if not watcher.enabled:
                    speech.say("Menu reading isn't set up for this game version yet. "
                               "Run the discovery tool once.")
        if watcher:
            watcher.poll()
        time.sleep(POLL_SECONDS)


def main():
    speech.say("MB Access started. Waiting for the game.")
    while True:
        game = process.try_attach()
        if game is None:
            time.sleep(1)
            continue
        play_session(game)
        speech.say("Game closed.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
