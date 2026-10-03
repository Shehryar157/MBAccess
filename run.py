"""MB Access: screen reader support for Mount & Blade games.

    python run.py    wait for Warband or With Fire & Sword, then speak menus
"""
import time

from mbaccess import process, session, speech
from mbaccess.mem import Reader
from mbaccess.menu_watch import MenuWatcher

POLL_SECONDS = 0.05  # check the game 20 times a second


def play_session(game):
    speech.say(f"Connected to {game.profile.title}.")
    address = None
    while address is None and game.is_running():
        # The game object only exists once a module has loaded.
        address, module = session.locate(game)
        if address is None:
            time.sleep(2)
    if address is None:
        return
    print(f"game object {address:#x}, module {module!r}")
    watcher = MenuWatcher(Reader(game), address, game.profile.game_offsets,
                          session.load_menus(game, module), speech.say)
    if not watcher.enabled:
        speech.say("Menu reading isn't set up for this game version yet. "
                   "Run the discovery tool once.")
    while game.is_running():
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
