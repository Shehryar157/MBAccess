"""MB Access: screen reader support for Mount & Blade games.

    python run.py               wait for Warband or With Fire & Sword, then speak menus
    pythonw run.py --with-game  started by the loader DLL: follow one game session,
                                log to logs\mbaccess.log, and exit when the game closes
"""
import ctypes
import os
import sys
import time

from mbaccess import (access_page, click, help, keys, launcher, messages, party_skills, world_map,
                      process, prompts, scanner, session, settings, speech, turning, wall_beeps)
from mbaccess import text as text_mod
from mbaccess.mem import Reader
from mbaccess.menu_watch import MenuWatcher

ACTION_KEY = 0x46   # F: the game's Action key (Options > Controls)
MESSAGE_GRACE = 1.5    # seconds a fresh game message is protected from menu speech
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
    address, menus, skills, skins, next_locate = None, {}, {}, {}, 0
    window = {"hwnd": None, "checked": 0}

    def game_window():
        # Looking the window up costs a little, so do it once a second.
        if time.time() - window["checked"] > 1:
            window["hwnd"], window["checked"] = process.find_window(game.pid), time.time()
        return window["hwnd"]

    key_watch = keys.watcher(game_window)
    helper = help.Help(speech.say)
    prefs = settings.Settings()
    log_address = game.profile.screen.get("message_log")
    # A game message just spoken ("Infantry, hear me!" after pressing 1) shouldn't be
    # cut off by the menu that opens a moment later (the order menu): until the next
    # key press, menu speech queues after it instead of interrupting.
    just_said = {"at": 0.0}

    def message_say(text, interrupt=True):
        if not interrupt:               # a new game message, not a key's answer
            just_said["at"] = time.time()
        speech.say(text, interrupt)

    def menu_say(text, interrupt=True):
        if interrupt and time.time() - just_said["at"] < MESSAGE_GRACE:
            interrupt = False
        speech.say(text, interrupt)

    news = messages.MessageWatcher(Reader(game), log_address, message_say,
                                   settings=prefs) if log_address else None
    # The Accessibility tab lists one "Speak ... messages" box per buffer category.
    categories = [b.name for b in news.buffers[1:]] if news else []
    page = access_page.AccessPage(prefs, categories)

    offsets = game.profile.screen.get("party_skills")
    team = party_skills.PartySkills(Reader(game), offsets) if offsets else None
    map_offsets = game.profile.screen.get("map")
    atlas = world_map.WorldMap(Reader(game), map_offsets, speech.say) if map_offsets else None

    click.use_config(game.profile.config_file)   # where the picture sits in the window
    # The main menu needs no campaign, so the watcher starts without one;
    # set_game hands it the campaign object once there is one.
    watcher = MenuWatcher(Reader(game), None, game.profile.game_offsets, [], menu_say,
                          screen=game.profile.screen, mouse=click.Mouse(game_window),
                          page=page, settings=prefs, party_skills=team, world_map=atlas)
    # Wall beeps run on their own thread at a steady rhythm; this loop only tells
    # them when the player is walking (scene window on top, game in front).
    in_scene = {"now": False}
    try:
        beeper = wall_beeps.WallBeeper(game, lambda: in_scene["now"])
    except Exception as e:      # no sound device, or pygame missing
        print("wall beeps off:", e)
        beeper = None
    def passage_name(variation):
        # A passage (a door to another scene) runs that option of the place's menu,
        # which stays current while walking. The option's door name is what the
        # game shows: "Door to the tavern." (untested in a town)
        try:
            number = watcher.read_state()[0]
            option = watcher.menus[number].items[variation]
            text = option.door or option.text
        except Exception:
            return None
        return text_mod.clean(text).rstrip(".")
    scan = scanner.Scanner(Reader(game), game.profile, speech.say,
                           item_name=lambda kind: watcher.item_name(kind),
                           passage_name=passage_name, turner=turning.Turner(game, speech.say))
    scan.turner.start_spinning(key_watch.is_held, lambda: in_scene["now"], keys.LEFT, keys.RIGHT,
                               speed=lambda: prefs.get("turn_speed"))
    if beeper:
        beeper.scanner = scan           # the tracking ping follows the scanner's choice
    prompt = prompts.Prompts(game, Reader(game), speech.say, scan,
                             mode=lambda: prefs.get("interact_mode"),
                             cue=beeper.cue if beeper else (lambda angle=0.0: None),
                             turner=scan.turner)
    if beeper:
        beeper.name_ahead = lambda: prefs.get("name_ahead")
        page.sounds = beeper            # Learn sounds on the Accessibility tab
    next_launcher = 0
    while game.is_running():
        # Looking for the launcher costs a little; while it's open, follow it
        # every tick, otherwise check twice a second for it to appear.
        if launch.hwnd or time.time() >= next_launcher:
            launch.poll()
            next_launcher = time.time() + 0.5
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
                    skills[module] = session.load_skills(game, module)
                    skins[module] = session.load_skins(game, module)
                watcher.set_game(address, menus[module], skills[module], skins[module])
                if not watcher.enabled:
                    speech.say("Menu reading isn't set up for this game version yet. "
                               "Run the discovery tool once.")
        pressed = key_watch.pressed()
        if pressed:
            just_said["at"] = 0.0       # the player moved on: speech answers them at once
        if keys.CONTROL in pressed:
            # Stop talking, as NVDA does on Ctrl. NVDA and JAWS already do it
            # themselves; this covers the Windows voice (SAPI) fallback.
            speech.silence()
        if helper.handle_keys(pressed):
            pressed = ()             # the help has the keys while it's open
        elif keys.F9 in pressed:
            helper.show("Inventory" if watcher.on_inventory() else
                        "Walking in scenes" if in_scene["now"] else "Menus and screens")
            pressed = ()
        if news:
            news.poll()
            if not watcher.typing():
                news.handle_keys(pressed)    # the menu reader ignores these keys
        if in_scene["now"]:
            try:
                if pressed:
                    scan.handle_keys(pressed)
                if ACTION_KEY in pressed:
                    prompt.on_action_key()      # F on horseback: dismount
                prompt.poll()                   # "Talk to Villager", "Mount: Saddle Horse"
                while beeper and not beeper.spoken.empty():
                    speech.say(beeper.spoken.get_nowait())  # "crude fence" ahead
            except Exception as e:      # a scene half loaded or just closed
                print("scene keys:", e)
        watcher.poll(pressed)
        # Walking in a scene: the scene window on top and the game in front.
        # The wall beeps and the scanner keys both follow this.
        try:
            hwnd = game_window()
            in_scene["now"] = bool(hwnd) and ctypes.windll.user32.GetForegroundWindow() == hwnd \
                and watcher.top_window() == wall_beeps.SCENE_WINDOW
        except Exception:
            in_scene["now"] = False
        # Keys the mod uses on this screen never reach the game: Tab where
        # there are sections, Escape where it presses the screen's way back,
        # letters where they type-search. Everywhere else they're the game's
        # (Tab leaves a scene, Escape opens the pause menu, WASD walks).
        mine = set()
        if watcher.has_sections():
            mine.add(keys.TAB)
        if watcher.back_item() is not None or watcher.search_on:
            mine.add(keys.ESCAPE)
        if watcher.searching():
            mine.update(keys.LETTERS)
        if watcher.search_key():
            mine.add(keys.KEY_F)        # the map: F starts a search
        if in_scene["now"]:
            mine.update((keys.KEY_J, keys.KEY_K, keys.KEY_L, keys.KEY_O, keys.SEMICOLON, keys.QUOTE))
        # Shift+A / D / S turn (S: about-face), Ctrl+A / D face the nearest thing in the
        # scanner's category; plain A, D and S still walk.
        key_watch.swallow_shifted = frozenset((keys.KEY_A, keys.KEY_D, keys.KEY_S)) if in_scene["now"] else frozenset()
        key_watch.swallow_ctrl = frozenset((keys.KEY_A, keys.KEY_D)) if in_scene["now"] else frozenset()
        key_watch.swallow = frozenset(mine)
        # Walking: a held W's auto-repeats would make NVDA cut off "crude fence".
        key_watch.quiet_repeats = in_scene["now"]
        key_watch.wait(POLL_SECONDS)     # wakes at once when a key arrives


def main():
    # Let threads take turns every 2 ms instead of 5: speech, the wall beeps and the
    # main loop answer sooner when they share Python.
    sys.setswitchinterval(0.002)
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
