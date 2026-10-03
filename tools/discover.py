"""Discovery tool: learn where this game version keeps the current menu.

Run it, then play normally: start a new game and click through a few menus
(the character creation menus are perfect). It watches quietly and never
presses keys. Each time it recognises a menu's text inside the game object,
it notes which slots hold that menu's number; the slots that are right
every time (a set intersection) are the real cur_menu_no. When only one is
left, it saves the offsets to profiles/<game>.json.

    python -m tools.discover
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mbaccess import finder, process, session, speech, text  # noqa: E402
from mbaccess.mem import Reader, ReadError  # noqa: E402

SCAN_SIZE = 0x10000  # how much of the game object to search (64 KB)
MIN_PREFIX = 12      # ignore menus whose fixed text is too short to be unique


def fixed_prefix(menu_text):
    """The part of a menu's text before the first {variable} or line break."""
    cut = len(menu_text)
    for mark in ("{", "^"):
        if mark in menu_text:
            cut = min(cut, menu_text.index(mark))
    return menu_text[:cut].strip()


def main():
    print("Waiting for the game...")
    game = None
    while game is None:
        game = process.try_attach()
        time.sleep(1)
    print(f"Attached to {game.profile.title} (pid {game.pid}) in {game.folder}")
    address, module = session.locate(game)
    if address is None:
        print("Could not find the game object. Is a module loaded (past the launcher)?")
        return
    print(f"Game object at {address:#x}, module {module!r}")
    menus = session.load_menus(game, module)
    prefixes = [(i, fixed_prefix(m.text)) for i, m in enumerate(menus)]
    prefixes = [(i, p) for i, p in prefixes if len(p) >= MIN_PREFIX]
    reader = Reader(game)
    text_offset, number_slots, seen = None, None, set()
    speech.say("Discovery running. Click through a few menus.")
    while game.is_running():
        time.sleep(0.5)
        try:
            strings = finder.find_string_fields(reader, address, SCAN_SIZE)
        except ReadError:
            continue
        for offset, value in strings.items():
            value = value.replace("\n", "^")
            for index, prefix in prefixes:
                if not value.startswith(prefix) or index in seen:
                    continue
                seen.add(index)
                if text_offset is None:
                    text_offset = offset
                slots = set(finder.find_int_field(reader, address, SCAN_SIZE, index))
                number_slots = slots if number_slots is None else number_slots & slots
                print(f"saw {menus[index].id} (#{index}) text at +{offset:#x}; "
                      f"{len(number_slots)} candidate number slots left")
                if len(number_slots) == 1 and len(seen) >= 2:
                    offsets = game.profile.game_offsets
                    offsets["cur_menu_text"] = text_offset
                    offsets["cur_menu_no"] = number_slots.pop()
                    game.profile.save()
                    msg = (f"Found it: menu text at {offsets['cur_menu_text']:#x}, "
                           f"menu number at {offsets['cur_menu_no']:#x}. Saved.")
                    print(msg)
                    speech.say(msg)
                    return
    print("Game closed before discovery finished.")


if __name__ == "__main__":
    main()
