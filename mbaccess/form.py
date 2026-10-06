"""Reading any screen by walking its widget tree (found 2026-10-05).

Every screen (the engine calls them game windows) is a tree of widgets, like
nested Python lists: a container widget has a name (an rgl::string at
+0x2d0, e.g. "options" or "invert_mouse") and an stl::vector of pointers to
its children at +0x364. We walk the tree from the window's root and keep
what a player can read or use. The kind of each widget comes from its C++
class: the first 4 bytes of every object point at its class's method table
(the vtable), so that address works like type(obj) in Python. The profile
maps vtable addresses to kinds: label, button, tab, checkbox, spinner,
slider, image.

Then we sort everything into rows by height, so the label "Combat AI:"
joins the spinner on its row and is spoken as "Combat AI: Poor, spinner".
"""
import struct
from dataclasses import dataclass

from . import text as text_mod
from .mem import ReadError

NAME, CHILDREN = 0x2d0, 0x364   # container name and child vector
SIZE = 0x1ac                     # width, height (floats); position is the bottom-left corner
CHECKED = 0x2b0                 # checkbox: 1 when ticked
SLIDER_VALUE = 0x2bc             # slider: value, then its minimum and maximum (floats)
HIDDEN, DISABLED = 0x1, 0x2
ROW = 0.012                      # widgets this close in height share a row
FAR = 0.3                        # text further apart than this on a row is separate
SLIDER_WIDTH = 0.205             # the slider track, in screen units
SLIDER_STEP = 0.05               # Left/Right move a slider by 5%
# Drop-down: its choices are an stl::vector of rgl::strings (0x90 bytes each),
# the chosen index, and the height of one row of the open list.
CHOICES, CHOSEN, LIST_ROW, RGL_STRING = 0x2e8, 0x2b0, 0x320, 0x90
CONTROLS = ("button", "tab", "checkbox", "spinner", "slider", "edit", "dropdown", "slot")
ROLE = {"button": "button", "tab": "tab", "checkbox": "checkbox",
        "spinner": "spinner", "slider": "slider", "edit": "edit box", "dropdown": "drop-down"}


@dataclass
class Item:
    kind: str           # "text" or one of CONTROLS
    label: str          # what it's called; doesn't change while the screen is open
    x: float
    y: float
    value: str = ""     # what it's set to; can change (checked, "Poor", "40%")
    arrows: tuple = ()  # spinner: x of its left and right arrows
    fraction: float = 0.0
    click: tuple = (0.1, 0.01)   # where to click, relative to (x, y)
    scroll: tuple = None         # (bottom, top) of the scroll area it's in, if any
    widget: int = 0              # its address in the game's memory
    disabled: bool = False       # greyed out: shown but can't be used
    raise_at: tuple = None       # (x, y) of its "+" button, if it has one
    choices: tuple = ()          # drop-down: all its choices, in the game's order
    chosen: int = 0              # drop-down: index of the current choice
    list_row: float = 0.0        # drop-down: height of one row of the open list
    group: str = ""              # name of the container it's in, e.g. "inv" (equipment)
    virtual: str = ""            # one of the mod's own items (Accessibility tab), not the game's

    def spoken(self):
        words = self.label
        if self.value and not words:
            words = self.value
        elif self.value:
            words = f"{words} {self.value}" if words.endswith(":") else f"{words}, {self.value}"
        role = ROLE.get(self.kind)   # menu "option"s and plain text have no role
        words = f"{words}, {role}" if role else words
        if self.raise_at:
            words += ", can raise"
        return f"{words}, unavailable" if self.disabled else words

    def visible(self):
        """Is the spot we'd click inside its scroll area? (Its corner isn't
        enough: a cell can poke in at the top with its middle hidden.)"""
        if self.scroll is None:
            return True
        bottom, top = self.scroll
        return bottom <= self.y + self.click[1] <= top

    def wheel_notches(self):
        """Which way to turn the wheel to bring it into view: -1 scrolls down."""
        return -1 if self.y + self.click[1] < self.scroll[0] else 1

    def action(self, key):
        """The mouse action for a key name, or None. Actions are tuples:
        ("click", x, y), ("right click", x, y) or ("drag", from_x, to_x, y)."""
        y = self.y + self.click[1]
        if key == "right" and self.raise_at:
            return ("click",) + self.raise_at
        if key == "activate" and self.kind in ("option", "button", "tab", "checkbox", "edit", "slot"):
            return ("click", self.x + self.click[0], y)
        if key == "special" and self.kind == "slot":
            # The item's one special action: read a book, slaughter livestock.
            return ("right click", self.x + self.click[0], y)
        if key in ("left", "right") and self.kind == "spinner" and len(self.arrows) == 2:
            return ("click", self.arrows[key == "right"] + 0.01, self.y + 0.015)
        if key in ("left", "right") and self.kind == "dropdown" and self.choices:
            target = self.chosen + (1 if key == "right" else -1)
            if not 0 <= target < len(self.choices):
                return None
            # The open list hangs below the box, last choice at the top
            # ("Always, Melee only, Ranged only, Never").
            row = len(self.choices) - 1 - target
            return ("pick", self.x + self.click[0], y,
                    self.x + self.click[0], self.y - (row + 0.5) * self.list_row)
        if key in ("left", "right") and self.kind == "slider":
            step = SLIDER_STEP if key == "right" else -SLIDER_STEP
            target = min(1.0, max(0.0, self.fraction + step))
            return ("drag", self.x + self.fraction * SLIDER_WIDTH,
                    self.x + target * SLIDER_WIDTH, y)
        return None


class TreeReader:
    def __init__(self, reader, screen):
        self.r = reader
        self.s = screen
        # JSON has no hex numbers, so the profile writes vtables as "0x7c4bac".
        self.kinds = {int(k, 16): v for k, v in screen.get("classes", {}).items()}
        self.key = ()

    # --- low level -------------------------------------------------------

    def position(self, p):
        return struct.unpack("<ff", self.r.read(p + self.s["widget_position"], 8))

    def middle(self, p, default=(0.02, 0.01)):
        """Where to click, relative to the widget's corner: the middle of its
        size (+0x1ac, width and height), if it has a sensible one. Wide
        picture buttons with centred text (the Esc menu's "Options") only
        react near their text, far right of the corner."""
        w, h = struct.unpack("<ff", self.r.read(p + SIZE, 8))
        return (w / 2, h / 2) if 0.005 < w < 1 and 0.005 < h < 0.3 else default

    def hidden(self, p):
        return self.r.u32(p + self.s["widget_flags"]) & HIDDEN

    def disabled(self, p):
        return bool(self.r.u32(p + self.s["widget_flags"]) & DISABLED)

    def text(self, p):
        return text_mod.clean(self.r.rgl_string(p + self.s["widget_text"]))

    def kind(self, p):
        return self.kinds.get(self.r.ptr(p))

    def kind_at(self, address):
        """Kind of the object that the pointer at address points to, or None."""
        try:
            p = self.r.ptr(address)
            return self.kind(p) if p > 0x10000 else None
        except ReadError:
            return None

    def children(self, p):
        """(name, child pointers) if p is a container, else (None, [])."""
        try:
            name = self.r.rgl_string(p + NAME)
            start, end, cap = struct.unpack("<III", self.r.read(p + CHILDREN, 12))
        except ReadError:
            return None, []
        if not name or not name.isprintable() or not (start and start <= end <= cap) \
                or end - start > 4000:
            return None, []
        return name, list(struct.unpack(f"<{(end - start) // 4}I", self.r.read(start, end - start)))

    # --- the walk --------------------------------------------------------

    def items(self, root, scroll_top, layout=None):
        found, stack, seen = [], [(root, None, "")], set()
        while stack:
            p, scroll, group = stack.pop()
            if p in seen or p < 0x10000 or len(seen) > 2000:
                continue
            seen.add(p)
            try:
                if self.hidden(p):
                    continue
                kind = self.kind(p)
                name, kids = self.children(p)
                if kind in CONTROLS:
                    found.append(self.control(p, kind, kids, scroll))
                    found[-1].group = group
                    continue        # its children (label, arrows) are read by control()
                if kind in ("label", "image"):
                    words = self.text(p)
                    if words:
                        x, y = self.position(p)
                        if kind == "label":
                            found.append(Item("text", words, x, y, scroll=scroll, widget=p))
                        else:   # a picture button with text, e.g. a key binding "W"
                            found.append(Item("button", "", x, y, value=words, click=self.middle(p),
                                              scroll=scroll, widget=p, disabled=self.disabled(p)))
                if name and name.endswith(("_vs", "_s")):
                    # The list scrolls: its bottom edge is this widget's y,
                    # its top that plus its height, if it has a sensible one.
                    bottom = self.position(p)[1]
                    height = struct.unpack("<f", self.r.read(p + SIZE + 4, 4))[0]
                    scroll = (bottom, bottom + height if 0.05 < height < 1 else scroll_top)
                stack.extend((k, scroll, name or group) for k in reversed(kids))
            except ReadError:
                continue            # a freed or half-built widget; skip it
        # Which screen this is: the widgets' addresses stay put while it's
        # open, unlike their rows, which shift for a moment while scrolling.
        self.key = tuple(sorted(i.widget for i in found))
        if layout:
            found = arrange(found, layout)
            if "columns" in layout:
                # Read each column (split at these x limits) top to bottom.
                limits = layout["columns"] + [99]
                column = lambda i: next(n for n, x in enumerate(limits) if i.x < x)
                return [item for n in range(len(limits))
                        for item in rows([i for i in found if column(i) == n],
                                         layout.get("by_columns", True))]
            return rows(found, layout.get("by_columns", True))
        return rows(found)

    def control(self, p, kind, kids, scroll):
        x, y = self.position(p)
        item = Item(kind, self.text(p), x, y, scroll=scroll, widget=p, disabled=self.disabled(p))
        texts, images = [], []
        for k in kids:
            try:
                if self.hidden(k):
                    continue
                kk = self.kind(k)
                if kk == "label":
                    words = self.text(k)
                    if words:
                        texts.append(words)
                elif kk == "image":
                    images.append(self.position(k)[0])
            except ReadError:
                continue
        if kind == "edit":
            # Its text is what you typed: a value, so typing is spoken as it changes.
            item.label, item.value = "", item.label
            item.click = (0.05, 0.015)
        if kind in ("button", "tab"):
            item.click = (0.07, 0.02)   # buttons react from x+0 to +0.14, y+0.01 to +0.03
        if kind == "slot":
            item.click = self.middle(p, (0.044, 0.044))   # an inventory cell
        if kind == "checkbox":
            item.label = item.label or " ".join(texts)
            item.value = "checked" if self.r.u32(p + CHECKED) else "not checked"
            item.click = (0.05, 0.01)
        elif kind == "spinner":
            item.value = " ".join(texts)
            item.arrows = tuple(sorted(images)[:1] + sorted(images)[-1:]) if len(images) >= 2 else ()
        elif kind == "dropdown":
            start, end = struct.unpack("<II", self.r.read(p + CHOICES, 8))
            if start and 0 < end - start <= 64 * RGL_STRING:
                item.choices = tuple(text_mod.clean(self.r.rgl_string(a))
                                     for a in range(start, end, RGL_STRING))
            item.chosen = self.r.u32(p + CHOSEN)
            item.list_row = struct.unpack("<f", self.r.read(p + LIST_ROW, 4))[0]
            item.label, item.value = "", item.label   # its text is the current choice
            item.click = self.middle(p)
        elif kind == "slider":
            value, low, high = struct.unpack("<3f", self.r.read(p + SLIDER_VALUE, 12))
            # Options sliders run 0-1, Custom Battle's 0-100 or 1-75.
            item.fraction = (value - low) / (high - low) if high > low else 0.0
            item.value = f"{round(item.fraction * 100)}%"
        return item


def rows(found, by_columns=True):
    """Sort top to bottom, left to right, and pair labels with the control on their row.

    A scrolling list stays in one piece: things above it come first, then
    the whole list (even rows scrolled away), then things below it, like a
    Done button. A two-column list reads down one column, then the next.
    """
    top = max((i.scroll[1] for i in found if i.scroll), default=None)

    def section(i):
        if i.scroll or top is None:
            return 1
        return 0 if i.y >= top else 2

    found.sort(key=lambda i: (section(i), -i.y, i.x))
    groups = []
    for item in found:
        if groups and abs(groups[-1][0].y - item.y) <= ROW:
            groups[-1].append(item)
        else:
            groups.append([item])

    result, block = [], []   # block: consecutive rows with several controls

    def flush():
        if by_columns:
            block.sort(key=lambda i: (round(i.x, 2), -i.y))
        result.extend(block)
        block.clear()

    for group in groups:
        group.sort(key=lambda i: i.x)
        group = attach_plus(group)
        controls = [i for i in group if i.kind != "text"]
        # The half-full last row of a two-column list ("Select Order 2")
        # still belongs to the list if it lines up with one of its columns.
        in_block = len(controls) > 1 or (
            len(controls) == 1 and any(abs(i.x - controls[0].x) < 0.005 for i in block))
        if not in_block:
            flush()
        if not controls:
            # Text on one row is one line, unless it's far apart: headings of
            # side-by-side panels ("Party Skills" ... "Company: 1 / 41").
            line = group[0]
            for i in group[1:]:
                if i.x - line.x > FAR:
                    result.append(line)
                    line = i
                else:
                    line.label += " " + i.label
            result.append(line)
            continue
        if len(controls) == 1 and not in_block:
            result.append(single(group, controls[0]))
            continue
        # Going left to right, each control takes the text just before it,
        # except that the text right after a slider is its value ("34%").
        texts, previous = [], None
        for item in group:
            if item.kind == "text":
                if previous is not None and previous.kind == "slider" and not texts \
                        and previous.value.endswith("%") and item.x - previous.x < 0.3:
                    previous.value = item.label
                    previous = None
                else:
                    texts.append(item.label)
                continue
            previous = item
            if texts:
                item.label = " ".join(texts + ([item.label] if item.label else []))
                texts = []
            block.append(item)
        if texts:
            block.append(Item("text", " ".join(texts), group[-1].x, group[-1].y,
                              scroll=group[-1].scroll, widget=group[-1].widget))
    flush()
    # A drop-down with no label on its row is named by the heading just above
    # it ("Overall Quality" over "Custom").
    for n in range(len(result) - 1, 0, -1):
        item, above = result[n], result[n - 1]
        if item.kind == "dropdown" and not item.label and above.kind == "text" \
                and 0 < above.y - item.y < 0.06:
            item.label = above.label if above.label.endswith(":") else above.label + ":"
            del result[n - 1]
    # A heading and a label under it can hold the same words ("Party Skills"),
    # and a heading can name the one thing under it ("Horse" over the Horse slot).
    return [i for n, i in enumerate(result)
            if not (n and i.kind == "text" and result[n - 1].kind == "text"
                    and i.label == result[n - 1].label)
            and not (i.kind == "text" and n + 1 < len(result)
                     and result[n + 1].label == i.label)]


def single(group, control):
    """A row with one control: text before it names it, text after it is its value."""
    before = [i.label for i in group if i.kind == "text" and i.x < control.x]
    after = [i.label for i in group if i.kind == "text" and i.x > control.x]
    if control.kind == "slider" and len(before) > 1 and after:
        # "Character Detail: Low [slider] High": the words are the ends of
        # the range, so keep the percentage as the value.
        before = before[:1]
    elif after:   # e.g. the "71" printed after the battle size slider
        control.label = control.label or control.value   # a picture button keeps its text
        control.value = " ".join(after)
    if before:
        control.label = " ".join(before + ([control.label] if control.label else []))
    return control

def arrange(found, layout):
    """Per-screen help from the profile, for screens whose layout the
    general rules get wrong (Custom Battle):
    - "names": {"0.23": "Infantry"}: names for unlabelled sliders by height,
      where the label is a picture we can't read;
    - "heading_offset": [lo, hi]: a heading names the unlabelled control just
      below it (within 0.05) whose x is lo to hi to the right of the heading's;
    - "sides": [[x_limit, "Player"], ...]: controls left of each x limit get
      that side's name in front of their label.
    """
    controls = [i for i in found if i.kind != "text"]
    name_slots(controls, found, layout)
    for i in controls:
        for y, name in layout.get("names", {}).items():
            if i.kind == "slider" and not i.label and abs(i.y - float(y)) < 0.006:
                i.label = name
    if "heading_offset" in layout:
        lo, hi = layout["heading_offset"]
        used = set()
        for t in [i for i in found if i.kind == "text"]:
            below = [c for c in controls if not c.label and 0 < t.y - c.y <= 0.05
                     and lo <= c.x - t.x <= hi]
            if below:
                below[0].label = t.label if t.label.endswith(":") else t.label + ":"
                used.add(id(t))
        found = [i for i in found if id(i) not in used]
    for i in controls:
        for limit, side in layout.get("sides", []):
            if i.x < limit:
                if side:
                    i.label = f"{side} {i.label}".strip()
                break
    return found

def name_slots(controls, found, layout):
    """Inventory cells are blank pictures, so they need names (the item in
    one is read from the game's tooltip when it's hovered):
    - "slot_names": [[x, y, "Head"], ...]: fixed cells, e.g. the equipment;
    - "slot_groups": {"int": "Inventory"}: a grid, numbered across then down.
      A grid not listed takes the heading above its panel ("Discard", or a
      merchant's name)."""
    fixed = layout.get("slot_names", [])
    grids = {}
    for i in controls:
        if i.kind != "slot":
            continue
        name = next((n for x, y, n in fixed if abs(i.x - x) < 0.01 and abs(i.y - y) < 0.01), None)
        if name:
            i.label = name
        else:
            grids.setdefault(i.group, []).append(i)
    for group, cells in grids.items():
        title = layout.get("slot_groups", {}).get(group)
        if not title:
            left = min(c.x for c in cells)
            headings = [t for t in found if t.kind == "text" and t.y > max(c.y for c in cells)
                        and abs(t.x - left) < 0.15]
            title = max(headings, key=lambda t: t.y).label if headings else "Slot"
        cells.sort(key=lambda c: (-round(c.y, 2), c.x))
        for n, c in enumerate(cells, 1):
            c.label = f"{title} {n}"


def attach_plus(group):
    """A "+" button belongs to the nearest control on its left in the row
    (character screen: "Ironflesh  0  +"). It becomes that control's Right
    arrow action, and the text between them (the level) becomes its value."""
    plus = [i for i in group if i.kind == "button" and (i.value or i.label) == "+"]
    if not plus:
        return group
    drop = set()
    for p in plus:
        owners = [c for c in group if c.kind != "text" and c not in plus and c.x < p.x]
        if not owners:
            continue
        owner = max(owners, key=lambda c: c.x)
        between = [t for t in group if t.kind == "text" and owner.x < t.x < p.x]
        if between:
            owner.label = owner.label or owner.value   # a picture button keeps its text
            owner.value = " ".join(t.label for t in between)
            drop.update(id(t) for t in between)
        owner.raise_at = (p.x + 0.008, p.y + 0.008)
        drop.add(id(p))
    return [i for i in group if id(i) not in drop]