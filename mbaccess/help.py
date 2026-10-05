"""F9: every key the mod adds, as a list read line by line, grouped by screen.

Like FFC Access's help: the cursor starts on the group for the screen you're
on, Up/Down read a line at a time, Control Up/Down jump between groups, and
Enter on a command line (one with an action) closes the help and does it.
F9 or Escape closes it.

We read the keyboard from outside the game, so we can't stop the game seeing
the same keys. Arrows and Enter do nothing on most game screens, but Escape
also reaches the game (it closes the inventory, for example).
"""
from . import keys

# (group name, [(line, action or None), ...]). An action is a function to
# run from Enter; none of our keys are commands yet, so they're all None.
GROUPS = [
    ("Anywhere", [
        ("F9: this help. F9 or Escape closes it.", None),
    ]),
    ("Game messages", [
        ("New messages are read as they appear.", None),
        ("Left and right brackets: previous or next message buffer: All, "
         "then one per category, such as Combat or Money and trade.", None),
        ("Semicolon and apostrophe: previous or next message in the buffer.", None),
        ("Shift with semicolon or apostrophe: oldest or newest message.", None),
    ]),
    ("Menus and screens", [
        ("Up and Down arrows: previous or next item. Home and End: first or last.", None),
        ("Enter or Space: press the item.", None),
        ("Left and Right arrows: change a spinner, slider or drop-down, "
         "or raise a skill or attribute that has a plus button.", None),
        ("In a name box: type as usual, and the letters are read back.", None),
    ]),
    ("Inventory", [
        ("Up and Down arrows: move through the equipment slots, your bag "
         "and the other side's items. Each cell reads its item and price, or empty.", None),
        ("Enter: pick up the item, then Enter on another cell to put it down. "
         "This equips, unequips, discards, loots, buys and sells.", None),
        ("Shift Enter: the item's special action, if it has one: "
         "read a book, or slaughter livestock for food.", None),
    ]),
]


class Help:
    def __init__(self, say):
        self.say = say
        self.open = False
        self.lines = []     # (text, action, group number)
        self.cursor = 0

    def show(self, start_group="Anywhere"):
        self.lines, self.cursor = [], 0
        for number, (name, entries) in enumerate(GROUPS):
            if name == start_group:
                self.cursor = len(self.lines)
            self.lines.append((f"{name}:", None, number))
            self.lines += [(text, run, number) for text, run in entries]
        self.open = True
        self.say(f"Help. {self.lines[self.cursor][0]}")

    def close(self):
        self.open = False
        self.say("Help closed.")

    def handle_keys(self, pressed):
        """Use the keys while the help is open. Returns True if it took them."""
        if not self.open:
            return False
        for key in pressed:
            if key in (keys.F9, keys.ESCAPE):
                self.close()
                return True
            if key == keys.RETURN:
                run = self.lines[self.cursor][1]
                if run is None:
                    self.say("That's a key to use directly.")
                else:
                    self.open = False    # the command may need the screen behind
                    run()
                    return True
                continue
            if key in (keys.UP, keys.DOWN) and keys.is_down(keys.CONTROL):
                self.cursor = self.next_group(-1 if key == keys.UP else 1)
            elif key in (keys.UP, keys.DOWN, keys.HOME, keys.END):
                last = len(self.lines) - 1
                self.cursor = {keys.UP: max(self.cursor - 1, 0),
                               keys.DOWN: min(self.cursor + 1, last),
                               keys.HOME: 0, keys.END: last}[key]
            else:
                continue
            self.say(self.lines[self.cursor][0])
        return True

    def next_group(self, step):
        """Line number of the previous or next group's heading (stays put at
        the ends). Going up from inside a group goes to its own heading first."""
        group = self.lines[self.cursor][2]
        # A heading is the first line of its group.
        on_heading = self.cursor == 0 or self.lines[self.cursor - 1][2] != group
        if step > 0 or on_heading:
            group += step
        for n, (_, _, g) in enumerate(self.lines):
            if g == group:
                return n
        return self.cursor
