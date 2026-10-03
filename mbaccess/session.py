"""Shared setup: find the game object and the loaded module's menus."""
import os

from . import finder, modfiles


def locate(game):
    """Return (game_object_address, module_name), or (None, None).

    We don't know which module is loaded, so we try each folder name in
    <game>\Modules and keep the first that matches a wb::game object.
    """
    offsets = game.profile.game_offsets
    for name in game.module_names():
        for address in finder.find_game(game, name, offsets["module_name"], offsets["savegame_name"]):
            return address, name
    return None, None


def load_menus(game, module_name):
    folder = os.path.join(game.folder, "Modules", module_name)
    try:
        return modfiles.load_menus(folder)
    except (OSError, ValueError) as e:
        print("could not read menus:", e)
        return []
