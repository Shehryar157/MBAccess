"""Conversations: what the other person says, and your replies.

The engine keeps one conversation_manager (reference/wse/WarbandLib/
conversation.h) inside its big global game_data object, in the exe's .data:

    int num_sentences; sentence *sentences; int active_token_no;
    int partner_troop_no, partner_party_no, partner_agent_no, speaker_agent_no;
    int cur_sentence_no; int repeat_object; int num_options;
    conversation_option speaker_options[1024];
    conversation_option partner_options[1024];
    bool in_meta_mission;               (padded to 4: game_data is pack(4))
    rgl::string speaker_text;           what was just said to you
    int u15;
    skill skills[42];                   each: description, name, id rgl::strings

A conversation_option is (sentence_no, repeat_object, flags, rgl::string
text): 156 bytes. Nothing in the manager is easy to search for, but the
skill table right after it is: skills[0]'s id is the module's first skill
("skl_trade" in Native). So we find that string and step back.

These are the 1.153 headers; NOT yet verified on 1.174. Which option array
holds your replies isn't known either: tools/probe_conversation.py prints
both during a conversation, and the profile's screen["conversation"]
records the answer ("options": "speaker" or "partner").
"""
import struct

from . import finder
from . import text as text_mod
from .mem import RGL_STRING_SIZE, Reader, ReadError, looks_like_rgl_string

OPTION_SIZE = 12 + RGL_STRING_SIZE    # sentence_no, repeat_object, flags, text
OPTION_TEXT = 12
MAX_OPTIONS = 1024
SKILL_ID = 2 * RGL_STRING_SIZE         # skill: description, name, then id
# Fields relative to speaker_text (all from the layout above).
IN_META_MISSION = -4
PARTNER_OPTIONS = IN_META_MISSION - MAX_OPTIONS * OPTION_SIZE
SPEAKER_OPTIONS = PARTNER_OPTIONS - MAX_OPTIONS * OPTION_SIZE
NUM_OPTIONS = SPEAKER_OPTIONS - 4
PARTNER_TROOP = NUM_OPTIONS - 24
# Where the exe's .data lives in Warband 1.174 (docs/findings/menus.md).
DATA_START, DATA_END = 0x85e000, 0x2db4000


def speaker_text_from_skill_id(skill_id_address):
    """skills[0].id -> conversation_manager.speaker_text."""
    skills = skill_id_address - SKILL_ID
    return skills - 4 - RGL_STRING_SIZE


def plausible(reader, speaker_text):
    """Does the layout around speaker_text look like a conversation manager?"""
    try:
        count = reader.i32(speaker_text + NUM_OPTIONS)
        flag = reader.u32(speaker_text + IN_META_MISSION)
    except ReadError:
        return False
    return 0 <= count <= MAX_OPTIONS and flag in (0, 1) and \
        looks_like_rgl_string(reader, speaker_text)


class DataOnly:
    """Limit a memory search to the exe's .data section (a few seconds
    shorter than searching everything the game has allocated)."""

    def __init__(self, source, start=DATA_START, end=DATA_END):
        self.source, self.start, self.end = source, start, end

    def read(self, address, length):
        return self.source.read(address, length)

    def regions(self):
        found = []
        for start, size in self.source.regions():
            lo, hi = max(start, self.start), min(start + size, self.end)
            if lo < hi:
                found.append((lo, hi - lo))
        return found


def find(source, first_skill_id, whole_memory=False):
    """Address of speaker_text, or None. first_skill_id: e.g. "skl_trade"."""
    reader = Reader(source)
    where = source if whole_memory else DataOnly(source)
    for address in finder.find_rgl_strings(where, first_skill_id):
        candidate = speaker_text_from_skill_id(address)
        if plausible(reader, candidate):
            return candidate
    return None


class Conversation:
    """Reads the conversation manager; config is the profile's
    screen["conversation"]: {"speaker_text": address, "options": "speaker"}."""

    def __init__(self, reader, config, troops=None):
        self.r = reader
        self.text_at = config["speaker_text"]
        side = config.get("options", "partner")
        self.options_at = self.text_at + (SPEAKER_OPTIONS if side == "speaker" else PARTNER_OPTIONS)
        self.troops = troops    # (game, offsets) getter for names: see partner_name

    def line(self):
        """What the other person just said."""
        return text_mod.clean(self.r.rgl_string(self.text_at))

    def options(self):
        """Your replies, in the game's order (top of the screen first)."""
        count = self.r.i32(self.text_at + NUM_OPTIONS)
        if not 0 <= count <= MAX_OPTIONS:
            raise ReadError(f"odd option count {count}")
        found = []
        for n in range(count):
            words = text_mod.clean(self.r.rgl_string(self.options_at + n * OPTION_SIZE + OPTION_TEXT))
            if words:
                found.append(words)
        return found

    def partner_troop(self):
        return self.r.i32(self.text_at + PARTNER_TROOP)

    def partner_name(self, game, offsets):
        """The troop's name ("Count Delinard"), from the troops array the
        party skills use; "" when unknown."""
        if not (game and offsets and "troops" in offsets):
            return ""
        try:
            troop = self.partner_troop()
            if troop < 0:
                return ""
            base = self.r.ptr(game + offsets["troops"])
            count = self.r.i32(game + offsets["troops"] + 4)
            if troop >= count:
                return ""
            return text_mod.clean(self.r.rgl_string(base + troop * offsets["troop_size"] + 4))
        except ReadError:
            return ""
