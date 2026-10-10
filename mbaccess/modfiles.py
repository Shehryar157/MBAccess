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
    door: str = ""   # a passage running this option shows it: "Door to the tavern."


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
            door = file_text(next(words)).strip()
            if not door.strip("."):
                door = ""       # "." or "_": the option has no door
            menu.items.append(MenuItem(item_id, item_text, door))
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


SF_EFFECTS_PARTY = 0x10   # header_skills.py: the party uses its best hero's level


@dataclass
class Skill:
    id: str      # e.g. "skl_pathfinding"
    name: str
    flags: int
    max_level: int
    description: str = ""   # what the Character screen shows on hover
    book: int = None        # item number that gives a hero carrying it +1 (Native: reference books)


def parse_skills(text):
    """Parse skills.txt: a count, then "id name flags max_level description"
    per skill. Index = skill number, as in a troop's packed skill levels."""
    words = iter(text.split())
    skills = []
    for _ in range(int(next(words))):
        skill_id, name, flags, max_level = (next(words) for _ in range(4))
        description = file_text(next(words)).replace("%%", "%")
        skills.append(Skill(skill_id, file_text(name), int(flags), int(max_level), description))
    return skills


def load_skills(module_dir, language="en"):
    """Skills of a module folder, with translated names where available."""
    with open(os.path.join(module_dir, "skills.txt"), encoding="utf-8", errors="replace") as f:
        skills = parse_skills(f.read())
    tr = read_translations(os.path.join(module_dir, "languages", language, "skills.csv"))
    for skill in skills:
        skill.name = tr.get(skill.id, skill.name)
    if any("%d" in skill.description for skill in skills):
        fill_skill_numbers(skills, module_dir)
    for number, item in load_skill_books(module_dir).items():
        if 0 <= number < len(skills):
            skills[number].book = item
    return skills


STORE_MUL = 2122          # header_operations.py: dest = op1 * op2
PLAIN_NUMBER = 1 << 56    # bigger arguments are tagged variables, not numbers

# Descriptions with a %d slot, and the script whose multiply step gives the
# number (Native: prisoners = Prisoner Management level * 5).
SKILL_NUMBER_SCRIPTS = {"skl_prisoner_management": "game_get_party_prisoner_limit"}


TAG_ITEM, TAG_SKILL = 4, 19   # header_common.py: an argument's top byte says what it names


def script_ops(text, script_name):
    """[(opcode, [arguments])] of a script in scripts.txt text; [] if it
    isn't there or is cut short."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:-1]):
        if line.split()[:1] != [script_name]:
            continue
        words, ops = iter(lines[i + 1].split()), []
        try:
            for _ in range(int(next(words))):
                opcode = int(next(words))
                ops.append((opcode, [int(next(words)) for _ in range(int(next(words)))]))
        except (StopIteration, ValueError):
            return []
        return ops
    return []


def script_multiplier(text, script_name):
    """The plain number in a script's first store_mul, from scripts.txt
    text; None if the script or the step isn't there."""
    for opcode, args in script_ops(text, script_name):
        if opcode == STORE_MUL:
            plain = [a for a in args[1:] if 0 <= a < PLAIN_NUMBER]
            if plain:
                return plain[-1]
    return None


def skill_books(text):
    """{skill number: item number}: a hero carrying the item gets +1 in the
    skill (Native: the three reference books). Read from the module's
    game_get_skill_modifier_for_troop: each branch names a skill, then an item."""
    books, skill = {}, None
    for _, args in script_ops(text, "game_get_skill_modifier_for_troop"):
        for a in args:
            if a >> 56 == TAG_SKILL:
                skill = a & (PLAIN_NUMBER - 1)
            elif a >> 56 == TAG_ITEM and skill is not None:
                books[skill] = a & (PLAIN_NUMBER - 1)
                skill = None
    return books


def load_skill_books(module_dir):
    try:
        with open(os.path.join(module_dir, "scripts.txt"), encoding="utf-8", errors="replace") as f:
            return skill_books(f.read())
    except OSError:
        return {}


def fill_skill_numbers(skills, module_dir):
    """Fill the %d slots the game fills when it draws a description."""
    try:
        with open(os.path.join(module_dir, "scripts.txt"), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        text = ""
    for skill in skills:
        if "%d" not in skill.description:
            continue
        script = SKILL_NUMBER_SCRIPTS.get(skill.id)
        number = script_multiplier(text, script) if script else None
        skill.description = skill.description.replace(
            "%d", str(number) if number is not None else "a set number")


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
