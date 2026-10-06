"""Reading the engine's data types out of raw memory.

Mount & Blade is a 32-bit program, so a pointer (an address that points at
something else) is 4 bytes, read with struct format "<I" (little-endian
unsigned 32-bit int). Our Python is 64-bit; that's fine, it just reads 4-byte
pointers out of the game.

A Reader wraps anything with a read(address, length) -> bytes method: the real
game process, or a FakeMemory in tests (duck typing).
"""
import contextlib
import struct

# rgl::string, from reference/wse/WarbandLib/rgl_string.h:
#   int cursor; char *buffer; size_t buffer_length; size_t str_length;
#   char static_buffer[128];
# Short strings live in static_buffer (buffer points at it); long ones are
# allocated elsewhere and buffer points there.
RGL_STRING_SIZE = 4 + 4 + 4 + 4 + 128
RGL_STRING_BUFFER = 4
RGL_STRING_LENGTH = 12
RGL_STRING_STATIC = 16
MAX_STRING = 64 * 1024  # anything longer is garbage, not a real string


class ReadError(Exception):
    """The address couldn't be read (unmapped, or the game closed)."""


PAGE = 0x1000   # memory comes in 4 KB pages


class Reader:
    def __init__(self, source):
        self.source = source
        self.pages = None       # page address -> bytes, inside cached()
        self.depth = 0

    @contextlib.contextmanager
    def cached(self):
        """Within this block, fetch whole 4 KB pages and keep them.

        Asking Windows for 4 bytes costs about as much as for 4096, and a
        screen read does hundreds of small reads close together, so this
        makes it several times faster. The pages are dropped at the end,
        so the next block sees fresh memory."""
        if self.depth == 0:
            self.pages = {}
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1
            if self.depth == 0:
                self.pages = None

    def read(self, address, length):
        if self.pages is not None and 0 < length <= PAGE:
            first = address - address % PAGE
            try:
                data = self._page(first)
                if address + length > first + PAGE:      # runs into the next page
                    data += self._page(first + PAGE)
                offset = address - first
                return data[offset:offset + length]
            except ReadError:
                pass    # a page we can't read whole: try just the bytes asked for
        return self._direct(address, length)

    def _page(self, address):
        if address not in self.pages:
            try:
                self.pages[address] = self._direct(address, PAGE)
            except ReadError:
                self.pages[address] = None
        if self.pages[address] is None:
            raise ReadError(f"page {address:#x} unreadable")
        return self.pages[address]

    def write(self, address, data):
        """Change the game's memory (a travel order). Rare: only on a key."""
        try:
            self.source.write(address, data)
        except Exception as e:
            raise ReadError(f"{address:#x}+{len(data)}: can't write: {e}") from e
        if self.pages is not None:
            self.pages.clear()      # what we cached is out of date now

    def _direct(self, address, length):
        try:
            return self.source.read(address, length)
        except ReadError:
            raise
        except Exception as e:  # pymem raises its own error types
            raise ReadError(f"{address:#x}+{length}: {e}") from e

    def u32(self, address):
        return struct.unpack("<I", self.read(address, 4))[0]

    def i32(self, address):
        return struct.unpack("<i", self.read(address, 4))[0]

    ptr = u32  # a 32-bit pointer is just an unsigned 32-bit number

    def rgl_string(self, address):
        """Read the rgl::string stored at address; return its text."""
        header = self.read(address, 16)
        _cursor, buffer, _capacity, length = struct.unpack("<iIII", header)
        if length == 0:
            return ""
        if buffer == 0 or length > MAX_STRING:
            raise ReadError(f"not an rgl::string at {address:#x}")
        return self.read(buffer, length).decode("utf-8", errors="replace")

    def vector(self, address, item_size):
        """Addresses of the items in an stl::vector (start, end, max pointers)."""
        start, end, _max = struct.unpack("<III", self.read(address, 12))
        if end < start or (end - start) % item_size:
            raise ReadError(f"not a vector at {address:#x}")
        return [start + i * item_size for i in range((end - start) // item_size)]


def looks_like_rgl_string(reader, address):
    """Cheap sanity check used when searching memory for strings."""
    try:
        _cursor, buffer, capacity, length = struct.unpack("<iIII", reader.read(address, 16))
    except ReadError:
        return False
    if buffer == 0 or length > MAX_STRING:
        return False
    if buffer == address + RGL_STRING_STATIC:
        return length < 128  # short string kept inside the object itself
    return length <= capacity


class FakeMemory:
    """Pretend process memory for tests: {start_address: bytes} blocks."""

    def __init__(self):
        self.blocks = {}

    def write(self, address, data):
        self.blocks[address] = bytearray(data)

    def read(self, address, length):
        for start, data in self.blocks.items():
            if start <= address and address + length <= start + len(data):
                offset = address - start
                return bytes(data[offset:offset + length])
        raise ReadError(f"unmapped {address:#x}+{length}")

    def regions(self):
        return [(start, len(data)) for start, data in self.blocks.items()]


def pack_rgl_string(address, text, heap_address=None):
    """Bytes of an rgl::string at address (test helper, mirrors the engine)."""
    raw = text.encode("utf-8")
    if len(raw) < 128:
        static = raw + b"\0" * (128 - len(raw))
        return struct.pack("<iIII", 0, address + RGL_STRING_STATIC, 128, len(raw)) + static
    if heap_address is None:
        raise ValueError("long strings need a heap_address")
    return struct.pack("<iIII", 0, heap_address, len(raw) + 1, len(raw)) + b"\0" * 128
