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
CHECKED = 0x2b0                  # checkbox: 1 when ticked
SLIDER_VALUE = 0x2bc             # slider: value, then its minimum and maximum (floats)
HIDDEN, DISABLED = 0x1, 0x2
ROW = 0.012                      # widgets this close in height share a row
SLIDER_WIDTH = 0.205             # the slider track, in screen units
SLIDER_STEP = 0.05               # Left/Right move a slider by 5%
CONTROLS = ("button", "tab", "checkbox", "spinner", "slider")
ROLE = {"button": "button", "tab": "tab", "checkbox": "checkbox",
        "spinner": "spinner", "slider": "slider"}


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
        if self.scroll is None:
            return True
        bottom, top = self.scroll
        return bottom <= self.y <= top

    def action(self, key):
        """The mouse action for a key name, or None. Actions are tuples:
        ("click", x, y) or ("drag", from_x, to_x, y)."""
        y = self.y + self.click[1]
        if key == "right" and self.raise_at:
            return ("click",) + self.raise_at
        if key == "activate" and self.kind in ("option", "button", "tab", "checkbox"):
            return ("click", self.x + self.click[0], y)
        if key in ("left", "right") and self.kind == "spinner" and len(self.arrows) == 2:
            return ("click", self.arrows[key == "right"] + 0.01, self.y + 0.015)
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
        found, stack, seen = [], [(root, None)], set()
        while stack:
            p, scroll = stack.pop()
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
                    continue        # its children (label, arrows) are read by control()
                if kind in ("label", "image"):
                    words = self.text(p)
                    if words:
                        x, y = self.position(p)
                        if kind == "label":
                            found.append(Item("text", words, x, y, scroll=scroll, widget=p))
                        else:   # a picture button with text, e.g. a key binding "W"
                            found.append(Item("button", "", x, y, value=words, click=(0.02, 0.01),
                                              scroll=scroll, widget=p, disabled=self.disabled(p)))
                if name and name.endswith("_vs"):
                    # The list scrolls: its bottom edge is this widget's y.
                    scroll = (self.position(p)[1], scroll_top)
                stack.extend((k, scroll) for k in reversed(kids))
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
                if kk == "label" and self.text(k):
                    texts.append(self.text(k))
                elif kk == "image":
                    images.append(self.position(k)[0])
            except ReadError:
                continue
        if kind in ("button", "tab"):
            item.click = (0.07, 0.02)   # buttons react from x+0 to +0.14, y+0.01 to +0.03
        if kind == "checkbox":
            item.label = item.label or " ".join(texts)
            item.value = "checked" if self.r.u32(p + CHECKED) else "not checked"
            item.click = (0.05, 0.01)
        elif kind == "spinner":
            item.value = " ".join(texts)
            item.arrows = tuple(sorted(images)[:1] + sorted(images)[-1:]) if len(images) >= 2 else ()
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
            first = group[0]
            first.label = " ".join(i.label for i in group)
            result.append(first)
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
    return result


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