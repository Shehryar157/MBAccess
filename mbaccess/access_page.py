"""The Accessibility tab: a pretend fourth tab on the game's Options screens.

The game's Options screen has three tabs (General Options, Video Options,
Controls) built into the engine, and we can't add a real one. So the menu
reader adds "Accessibility" to the tab row it reads out. Pressing it doesn't
click anything: the reader swaps the game tab's settings for ours. The page
lists the tab row, our settings, then the screen's own buttons (Done...),
which click the real ones. The game's screen stays as it was underneath;
pressing one of the real tabs switches to it, as a click would.

Items here are ordinary form.Item objects with a "virtual" name, so the
reader speaks and moves through them like any other screen.
"""
from .form import Item
from .settings import ITEM_DETAILS

TAB = "Accessibility"


class AccessPage:
    def __init__(self, settings, categories):
        self.settings = settings
        self.categories = categories     # message category names, e.g. "Combat"
        self.open = False

    def tab(self):
        return Item("tab", TAB, 0, 0, value="selected" if self.open else "", virtual="tab")

    def items(self):
        s = self.settings
        found = [checkbox("Speak new game messages", s.get("speak_messages"), "speak_messages")]
        for name in self.categories:
            # Ticked = not muted. "Speak new game messages" switches them all off on top.
            found.append(checkbox(f"Speak {name} messages",
                                  name not in s.get("muted_categories"), "category:" + name))
        found.append(Item("dropdown", "Item details in the inventory", 0, 0,
                          value=s.get("item_details"), virtual="item_details"))
        return found

    def act(self, item, key):
        """Change a setting. The reader notices the new value and speaks it."""
        s, name = self.settings, item.virtual
        if name == "speak_messages" and key == "activate":
            s.set(name, not s.get(name))
        elif name.startswith("category:") and key == "activate":
            s.toggle_category(name.split(":", 1)[1])
        elif name == "item_details" and key in ("activate", "left", "right"):
            n = ITEM_DETAILS.index(s.get(name)) if s.get(name) in ITEM_DETAILS else 0
            if key == "activate":
                n = (n + 1) % len(ITEM_DETAILS)    # Enter goes round
            else:
                n = max(0, min(len(ITEM_DETAILS) - 1, n + (1 if key == "right" else -1)))
            s.set(name, ITEM_DETAILS[n])


def checkbox(label, ticked, virtual):
    return Item("checkbox", label, 0, 0, value="checked" if ticked else "not checked",
                virtual=virtual)
