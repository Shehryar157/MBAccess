"""Finding the engine's objects in memory without hard-coded addresses.

Every game version puts things at different addresses, so instead of storing
addresses we search for something recognisable. The global wb::game object
(reference/wse/WarbandLib/game.h) starts like this:

    int savegame_slot;          +0
    int seed;                   +4
    rgl::string savegame_name;  +8   (144 bytes)
    int u1;                     +152
    bool u2;                    +156 (padded to 4 bytes)
    rgl::string module_name;    +160 e.g. "Native"

So we search memory for the module's name, check that it sits inside an
rgl::string (whose buffer pointer points right back at it), and step back
to the start of the object. The offsets above come from Warband 1.153 and
are checked again with the real game; a profile can override them.
"""
import struct

from .mem import RGL_STRING_STATIC, Reader, ReadError, looks_like_rgl_string

CHUNK = 1 << 20  # read big regions a megabyte at a time


def find_bytes(source, needle):
    """Yield every address where needle occurs, in all readable regions.

    source.regions() lists (start, size) pairs; for the real game it comes
    from VirtualQueryEx (see process.py).
    """
    for start, size in source.regions():
        pos = start
        while pos < start + size:
            length = min(CHUNK + len(needle), start + size - pos)
            try:
                data = source.read(pos, length)
            except Exception:
                break
            i = data.find(needle)
            while i != -1:
                yield pos + i
                i = data.find(needle, i + 1)
            pos += CHUNK


def find_rgl_strings(source, text):
    """Addresses of rgl::string objects holding exactly text (short strings)."""
    raw = text.encode("utf-8") + b"\0"
    reader = Reader(source)
    for hit in find_bytes(source, raw):
        address = hit - RGL_STRING_STATIC
        try:
            _c, buffer, _cap, length = struct.unpack("<iIII", reader.read(address, 16))
        except ReadError:
            continue
        if buffer == hit and length == len(raw) - 1:
            yield address


def find_game(source, module_name, module_name_offset=160, savegame_name_offset=8):
    """Candidate addresses of the wb::game object."""
    reader = Reader(source)
    for string_address in find_rgl_strings(source, module_name):
        game = string_address - module_name_offset
        if looks_like_rgl_string(reader, game + savegame_name_offset):
            yield game


def find_string_fields(reader, base, size):
    """{offset: text} for every rgl::string inside [base, base+size).

    We read the whole object once (one big read is far faster than thousands
    of small ones) and only go back to the game for the texts themselves.
    """
    data = reader.read(base, size)
    found = {}
    for offset in range(0, size - 15, 4):
        _c, buffer, capacity, length = struct.unpack_from("<iIII", data, offset)
        if buffer == 0 or length == 0 or length > 8192:
            continue
        if buffer == base + offset + RGL_STRING_STATIC:
            if length >= 128 or offset + 16 + length > size:
                continue
            raw = data[offset + 16:offset + 16 + length]
        elif length <= capacity and capacity < 1 << 20:
            try:
                raw = reader.read(buffer, length)
            except ReadError:
                continue
        else:
            continue
        found[offset] = raw.decode("utf-8", errors="replace")
    return found


def find_string_field(reader, base, size, text):
    """Offsets of rgl::strings in [base, base+size) whose text starts with text."""
    return [o for o, t in find_string_fields(reader, base, size).items() if t.startswith(text)]


def find_int_field(reader, base, size, value):
    """Offsets within [base, base+size) holding the 32-bit int value."""
    data = reader.read(base, size)
    want = struct.pack("<i", value)
    return [o for o in range(0, size - 3, 4) if data[o:o + 4] == want]
