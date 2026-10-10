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
        ("Control: stop speech, as in NVDA.", None),
    ]),
    ("Game messages", [
        ("New messages are read as they appear, each waiting for the one before to finish.", None),
        ("Left and right brackets: previous or next message buffer: All, "
         "then one per category, such as Combat or Money and trade.", None),
        ("Comma and period: previous or next message in the buffer.", None),
        ("Shift with comma or period: oldest or newest message.", None),
    ]),
    ("Menus and screens", [
        ("Up and Down arrows: previous or next item. Home and End: first or last. "
         "Hold an arrow to keep moving.", None),
        ("Tab and Shift Tab, or Control Right and Control Left: next or previous section, "
         "on screens that have them, "
         "like the columns of the party and character screens. Each section remembers "
         "where you were. Up and Down stay inside a section.", None),
        ("Enter or Space: press the item.", None),
        ("Escape: go back. It presses the screen's own way out, like Go back, Leave, "
         "Resume travelling or Done. Where there's none, as on the map, "
         "Escape is the game's: the pause menu.", None),
        ("Letters and numbers: jump to the next item starting with them. Type quickly "
         "to spell more of a name; the same letter again goes to the next one.", None),
        ("Left and Right arrows: change a spinner, slider or drop-down, "
         "or raise a skill or attribute that has a plus button.", None),
        ("In a name box: type as usual, and the letters are read back.", None),
        ("On the Options screens, an Accessibility tab follows Controls: the mod's own "
         "settings, then the screen's own buttons. Press a game tab to switch to it, "
         "as a sighted player clicks it. Escape closes Options as usual.", None),
    ]),
    ("Inventory", [
        ("The inventory is grids: your equipment, your bag, and the other side's items "
         "(Discard, a merchant, or loot). Tab and Shift Tab, or Control Right and "
         "Control Left, move between them.", None),
        ("All four arrows move around a grid, cell by cell, as it looks on screen. "
         "Home and End: first or last cell. Each cell reads its item and price, or empty.", None),
        ("Enter: pick up the item, then Enter on another cell to put it down. "
         "This equips, unequips, discards, loots, buys and sells.", None),
        ("Shift Enter: the item's special action, if it has one: "
         "slaughter a horse or other animal for food (the game asks first). "
         "Books are read from the Camp menu instead.", None),
        ("Control Enter: move the item to the other side at once, without carrying it: "
         "quick buy or sell when trading, quick take when looting.", None),
    ]),
    ("Walking in scenes", [
        ("The scanner lays things around you on two lines through you. O and L: the "
         "ahead and behind line; O steps further ahead, L further back. K and semicolon: "
         "the left and right line; K steps further left, semicolon further right. "
         "The first press gives the nearest thing on that side. Ahead means within "
         "45 degrees of straight ahead.", None),
        ("Shift K and Shift L: previous or next category: All, People, Exits, "
         "Items, Objects, Animals.", None),
        ("J: where the thing you last heard is now: distance, direction, "
         "and how far up or down.", None),
        ("Shift J: track the thing you last heard, or stop tracking. A ping plays from "
         "where it is, lower when it's behind you, quicker as you get close.", None),
        ("Apostrophe: compass, the way you're facing.", None),
        ("H: your health, and your horse's when you're riding.", None),
        ("On foot, hold Left or Right arrow: turn on the spot, as moving the mouse "
         "does. Press Apostrophe to hear where you now face. The speed is set on the "
         "Accessibility tab of the Options screen.", None),
        ("The game's prompts are read when they appear: Talk to someone, Mount a horse. "
         "Press F to do it, as usual.", None),
        ("Coming close to something ahead says what it is, like crude fence or village "
         "house. It can be turned off on the Accessibility tab.", None),
        ("A rising two-note sound means you can use something: talk, mount, pick up, go "
         "through. By default it plays when you face it as the game needs. With "
         "Use cue plays when set to Close enough on the Accessibility tab, it plays "
         "when you are near it whichever way you face, from its direction, and F turns "
         "you to it and uses it, on foot.", None),
        ("F on horseback, looking at nothing: dismount. The mod looks down at the horse "
         "for you, as the game needs, and looks ahead again.", None),
        ("Shift A and Shift D: turn 45 degrees left or right. On horseback the mod "
         "steers the horse with A or D for you.", None),
        ("Shift S: turn right round, 180 degrees, then the compass direction is read.", None),
        ("Control A and Control D: turn to the next thing round on your left or right, "
         "in the scanner's current category. Its name and distance are read, and J and "
         "Shift J then work on it. Press again for the next one round.", None),
        ("A two-note slur, once, from where it is: a way up (rising) or a way down or "
         "drop (falling) in that direction, like stairs or a ledge. After climbing, how "
         "far you went up or down is said.", None),
        ("To learn the mod's sounds, open the Accessibility tab on the Options screen: "
         "the Learn sound buttons at the bottom play each one.", None),
    ]),
    ("World map", [
        ("To reach the map: in a town or village scene, press Tab to leave it; "
         "in the place's menu, choose Leave.", None),
        ("The map opens on Places: towns, castles and villages, and moving parties "
         "while you can see them, nearest first, with distance and direction.", None),
        ("Enter on a place: travel there, as clicking it would. The mod says when you arrive.", None),
        ("Shift+Enter on a place: its right-click menu: Move here, View notes (the notes "
         "page on that place, or on the lord leading that party) and, for a friendly party "
         "or a caravan, Accompany. Up and Down choose, Enter presses, Escape closes.", None),
        ("Tab: the map's buttons: Camp, Reports, Notes, Inventory, Character and Party.", None),
        ("Letters search the places, so the game's letter shortcuts (I, P, C) don't work "
         "here: use the map buttons instead.", None),
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
