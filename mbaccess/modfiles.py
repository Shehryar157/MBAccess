"""Reading a module's compiled text files (menus.txt and its translations).

These files are made by TaleWorlds' Module System (see
reference/module_system, process_game_menus.py). Everything is separated by
whitespace, and spaces inside texts are written as underscores. So we split
the file into words and walk through them with an iterator, taking each word
with next(), like a conveyor belt.

Scripts (conditions and consequences) are stored as blocks of numbers:
    count, then for each operation: opcode, argument count, arguments...
We don't run scripts; we only need to skip past them.
"""
import csv
import os
from dataclasses import dataclass, field


@dataclass
class MenuItem:
    id: str      # e.g. "mno_town_1"
    text: str    # e.g. "join a caravan to Praven, in the Kingdom of Swadia."


@dataclass
class Menu:
    id: str      # e.g. "menu_start_phase_2"
    flags: int
    text: str
    items: list = field(default_factory=list)


def file_text(word):
    """A text as stored in the files: underscores stand for spaces."""
    return word.replace("_", " ")


def skip_block(words):
    for _ in range(int(next(words))):
        next(words)  # opcode
        for _ in range(int(next(words))):
            next(words)  # argument


def parse_menus(text):
    """Parse menus.txt; returns a list where index = menu number."""
    words = iter(text.split())
    if [next(words), next(words), next(words)] != ["menusfile", "version", "1"]:
        raise ValueError("not a menus.txt (version 1)")
    menus = []
    for _ in range(int(next(words))):
        menu = Menu(id=next(words), flags=int(next(words)), text=file_text(next(words)))
        next(words)  # mesh name
        skip_block(words)  # operations run when the menu opens
        for _ in range(int(next(words))):
            item_id = next(words)
            skip_block(words)  # conditions: when to show the option
            item_text = file_text(next(words))
            skip_block(words)  # consequences: what clicking it does
            next(words)  # door name
            menu.items.append(MenuItem(item_id, item_text))
        menus.append(menu)
    return menus


def read_translations(path):
    """A language csv (id|text per line) as a dict. Missing file: {}."""
    if not os.path.exists(path):
        return {}
    result = {}
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for row in csv.reader(f, delimiter="|", quoting=csv.QUOTE_NONE):
            if len(row) >= 2:
                result[row[0].strip()] = row[1]
    return result


def load_menus(module_dir, language="en"):
    """Menus of a module folder, with translated texts where available."""
    with open(os.path.join(module_dir, "menus.txt"), encoding="utf-8", errors="replace") as f:
        menus = parse_menus(f.read())
    tr = read_translations(os.path.join(module_dir, "languages", language, "game_menus.csv"))
    for menu in menus:
        menu.text = tr.get(menu.id, menu.text)
        for item in menu.items:
            item.text = tr.get(item.id, item.text)
    return menus
