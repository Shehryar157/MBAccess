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
import re
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
PICKER_GAP = 0.04                # a picker's arrows sit at most this far under its label
PICKER_REACH = 0.06              # ... and at most this far to its left and right
SLIDER_WIDTH = 0.205             # the handle's travel when the slider's size is unreadable
SLIDER_INSET = 0.005             # the handle's centre at 0% sits this far in from the left edge
SLIDER_STEP = 0.05               # Left/Right move a slider by 5%
# Drop-down: its choices are an stl::vector of rgl::strings (0x90 bytes each),
# the chosen index, and the height of one row of the open list.
CHOICES, CHOSEN, LIST_ROW, RGL_STRING = 0x2e8, 0x2b0, 0x320, 0x90
# A text box line that is nothing but one link: "<ip=4>Courtship</>".
WHOLE_LINK = re.compile(r"^<[a-z]+=\d+>[^<]*</>$", re.IGNORECASE)
LINK_NAME = re.compile(r"<[a-z]+=\d+>([^<]*)</>", re.IGNORECASE)   # a link's words
LINK_VECTORS = (0x2d4, 0x2e4, 0x314)   # text box: link boxes' corners, their link numbers
CONTROLS = ("button", "tab", "checkbox", "spinner", "slider", "edit", "dropdown", "slot")
ROLE = {"button": "button", "link": "link", "tab": "tab", "checkbox": "checkbox",
        "spinner": "spinner", "slider": "slider", "edit": "edit box", "dropdown": "drop-down"}


@dataclass
class Item:
    kind: str           # "text" or one of CONTROLS
    label: str          # what it's called; doesn't change while the screen is open
    x: float
    y: float
    value: str = ""     # what it's set to; can change (checked, "Poor", "40%")
    arrows: tuple = ()  # spinner: x of its left and right arrows
    arrow_click: tuple = (0.01, 0.015)   # where to click an arrow, from (its x, y)
    width: float = 0.0           # slider: its own width (size +0x1ac); 0 = unknown
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
    from_textbox: bool = False   # a line, paragraph or link of a multi-line text box
    order: int = 0               # its place within that text box
    links: tuple = ()            # a text line's links (Items of kind "link")

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
        if self.links:
            words += f", {len(self.links)} link" + ("s" if len(self.links) > 1 else "")
        return f"{words}, unavailable" if self.disabled else words

    def visible(self):
        """Is the spot we'd click inside its scroll area? (Its corner isn't
        enough: a cell can poke in at the top with its middle hidden.)"""
        if self.scroll is None:
            return True
        bottom, top = self.scroll
        return bottom <= self.y + self.click[1] <= top

    def wheel_notches(self, step=0.062):
        """How far to turn the wheel to bring it to the middle of its scroll
        area (one notch moves a list about step): negative scrolls down. A
        long list (253 characters in Notes) needs many notches at once."""
        bottom, top = self.scroll
        distance = (bottom + top) / 2 - (self.y + self.click[1])
        notches = min(60, max(1, int(abs(distance) / step)))
        return notches if distance < 0 else -notches

    def action(self, key, steps=1):
        """The mouse action for a key name, or None. Actions are tuples:
        ("click", x, y), ("right click", x, y) or ("drag", from_x, to_x, y)."""
        y = self.y + self.click[1]
        if key == "right" and self.raise_at:
            return ("click",) + self.raise_at
        if key == "activate" and self.kind in ("option", "button", "link", "tab", "checkbox", "edit", "slot"):
            return ("click", self.x + self.click[0], y)
        if key == "special" and self.kind == "slot":
            # The item's one special action: slaughter an animal (the game asks first).
            return ("right click", self.x + self.click[0], y)
        if key == "quick" and self.kind == "slot":
            # Ctrl+click: buy or sell (or take or drop) at once, no carrying.
            return ("ctrl click", self.x + self.click[0], y)
        if key in ("left", "right") and self.kind == "spinner" and len(self.arrows) == 2:
            dx, dy = self.arrow_click
            return ("click", self.arrows[key == "right"] + dx, self.y + dy)
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
            step = SLIDER_STEP * steps if key == "right" else -SLIDER_STEP * steps
            target = min(1.0, max(0.0, self.fraction + step))
            # Grab the handle where it's drawn: at 0% the left edge itself
            # misses it (face editor Age), so allow for its half-width.
            travel = self.width - 2 * SLIDER_INSET if self.width > 0.05 else SLIDER_WIDTH
            start = SLIDER_INSET if self.width > 0.05 else 0.0
            return ("drag", self.x + start + self.fraction * travel,
                    self.x + start + target * travel, y)
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
        found, stack, seen, blanks = [], [(root, None, "")], set(), []
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
                if kind == "textbox":
                    found.extend(self.textbox(p, scroll, name or group))
                if kind in ("label", "image"):
                    words = self.text(p)
                    if not words and kind == "image" and not kids:
                        blanks.append(p)    # maybe a picker's arrow (see pickers())
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
        found = self.pickers(found, blanks)
        # Which screen this is: the widgets' addresses stay put while it's
        # open, unlike their rows, which shift for a moment while scrolling.
        self.key = tuple(sorted(i.widget for i in found))
        # A text box keeps its address when its text changes (a new Notes
        # page), so its words count too: a new page is a new screen.
        self.key += tuple(hash(i.label + i.value) for i in found if i.from_textbox)
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

    def pickers(self, found, blanks):
        """A label with two blank picture buttons just under it, one on each
        side, is a picker: the face editor's Skin, Beard and Hair (previous /
        next style; the game shows no name or number for the style). It
        becomes one spinner item whose arrows Left/Right click."""
        if len(blanks) < 2:
            return found
        arrows = []
        for p in blanks:
            try:
                arrows.append((self.position(p), self.middle(p, (0.01, 0.015))))
            except ReadError:
                continue
        result = []
        for item in found:
            if item.kind == "text" and not item.from_textbox:
                under = [a for a in arrows if 0 < item.y - a[0][1] <= PICKER_GAP
                         and abs(a[0][0] - item.x) <= PICKER_REACH]
                left = [a for a in under if a[0][0] < item.x]
                right = [a for a in under if a[0][0] > item.x]
                if len(left) == 1 and len(right) == 1:
                    (lx, y), click = left[0]
                    (rx, _), _ = right[0]
                    item = Item("spinner", item.label, lx, y, arrows=(lx, rx),
                                arrow_click=click, scroll=item.scroll, widget=item.widget)
            result.append(item)
        return result

    def textbox(self, p, scroll, group):
        """A multi-line text (class 0x819984: the Notes screen's topic list
        and article). A topic list (every line one whole link, "<ip=4>Courtship</>")
        gives one button per line. An article gives one text item per line,
        each followed by its links ("Sanjar Khan, link"). Links are clicked in
        the middle of the box the game keeps for them (link_boxes)."""
        raw = self.r.rgl_string(p + self.s["widget_text"]).replace("^", "\n")
        x, y = self.position(p)
        h = struct.unpack("<f", self.r.read(p + SIZE + 4, 4))[0]
        lines = raw.split("\n")
        boxes = self.link_boxes(p)
        found, link_no = [], 0

        def add(item):
            item.scroll, item.widget, item.group = scroll, p, group
            item.from_textbox, item.order = True, len(found)
            found.append(item)

        # A topic list: every line is one whole link, except the page you're
        # on. Articles have links INSIDE sentences (lords, towns): not a list.
        whole = [bool(WHOLE_LINK.match(line.strip())) for line in lines if line.strip()]
        if whole and whole.count(False) <= 1 and any(whole):
            step = h / len(lines)
            for n, line in enumerate(lines):
                words = text_mod.clean(line)
                if not words:
                    continue
                bottom = y + h - (n + 1) * step     # line n's lower edge
                if WHOLE_LINK.match(line.strip()):
                    item = Item("button", "", x, bottom, value=words, click=(0.02, step / 2))
                    if link_no in boxes:
                        item.x, item.y, item.click = (x + boxes[link_no][0], y + boxes[link_no][1],
                                                      boxes[link_no][2])
                    link_no += 1
                    add(item)
                else:   # the page you're on isn't a link
                    add(Item("text", f"{words}, current", x, bottom))
            return found
        paragraphs = [line for line in lines if text_mod.clean(line)]
        for n, line in enumerate(paragraphs):
            # Their real heights aren't known: spread them down the box (rows()
            # keeps the box's own order anyway).
            # Its links stay inside it (Left/Right pick one, Enter clicks), so
            # a page of 9 lines is 9 items, not 60.
            links = []
            for name in LINK_NAME.findall(line):
                if link_no in boxes and name.strip():
                    bx, by, click = boxes[link_no]
                    links.append(Item("link", "", x + bx, y + by, value=text_mod.clean(name),
                                      click=click, scroll=scroll, widget=p))
                link_no += 1
            add(Item("text", text_mod.clean(line), x, y + h - (n + 0.5) * h / len(paragraphs),
                     links=tuple(links)))
        return found

    def link_boxes(self, p):
        """{link number: (x, y, click offset)} relative to the text box: the
        lower-left corner of the link's first box and the offset to its middle.
        The game keeps one box per piece (a name wrapped over two lines has
        two): lower-left corners at +0x2d4, upper-right at +0x2e4 (16 bytes
        each), and which link each piece belongs to at +0x314 (ints)."""
        try:
            lows, highs, owners = (struct.unpack("<II", self.r.read(p + off, 8))
                                   for off in LINK_VECTORS)
            count = (lows[1] - lows[0]) // 16
            if not (0 < count <= 2000 and (highs[1] - highs[0]) // 16 == count
                    and (owners[1] - owners[0]) // 4 == count):
                return {}
            low = self.r.read(lows[0], count * 16)
            high = self.r.read(highs[0], count * 16)
            owner = struct.unpack(f"<{count}i", self.r.read(owners[0], count * 4))
        except ReadError:
            return {}
        boxes = {}
        for n in range(count):
            if owner[n] in boxes:
                continue        # the second piece of a wrapped name
            x0, y0 = struct.unpack_from("<ff", low, n * 16)
            x1, y1 = struct.unpack_from("<ff", high, n * 16)
            boxes[owner[n]] = (x0, y0, ((x1 - x0) / 2, (y1 - y0) / 2))
        return boxes

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
            width = struct.unpack("<f", self.r.read(p + SIZE, 4))[0]
            item.width = width if 0.05 < width < 1 else 0.0
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
    # A text box's own order wins (a line, then its links): paragraph heights
    # are only estimates, so its items go back into its slots in that order.
    for box in {i.widget for i in found if i.from_textbox}:
        slots = [n for n, i in enumerate(found) if i.from_textbox and i.widget == box]
        for n, item in zip(slots, sorted((found[n] for n in slots), key=lambda i: i.order)):
            found[n] = item
    groups = []
    for item in found:
        # A text box's lines are whole lines: never paired with what sits
        # beside them (a one-line Notes page next to a topic).
        if groups and abs(groups[-1][0].y - item.y) <= ROW \
                and not (item.from_textbox or groups[-1][0].from_textbox):
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
        if group[0].from_textbox:
            flush()
            result.append(group[0])
            continue
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