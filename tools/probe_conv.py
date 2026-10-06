"""Find the conversation manager and the skills list; print what they hold.

    python tools/probe_conv.py

No game files needed. From reference/wse/WarbandLib/game_data.h (1.153), the
engine's data object has, in this order:
  conversation_manager (319676 bytes), an int of padding, skills[42].
A skill (skill.h) is description, name, id (rgl::strings), then u1, max_level,
u2, u3, flags = 3 * 144 + 20 = 452 bytes. Every module's skill ids start with
"skl_", so we search memory for that text, walk back to skill 0, then step
back over the conversation manager.

conversation_manager (conversation.h):
  +0  num_sentences, +4 sentences*, +8 active_token_no, +12 partner troop,
  +16 partner party, +20 partner agent, +24 speaker agent, +28 cur_sentence_no,
  +32 repeat_object, +36 num_options, +40 speaker_options[1024],
  then partner_options[1024], a bool, then speaker_text (rgl::string).
Each option: sentence_no, repeat_object, flags, text (rgl::string) = 156 bytes.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import process
from mbaccess.mem import Reader, ReadError, RGL_STRING_SIZE, RGL_STRING_STATIC

SKILL_SIZE = 3 * RGL_STRING_SIZE + 20
SKILL_ID = 2 * RGL_STRING_SIZE
NUM_SKILLS = 42
CONV_SIZE = 319676
OPTION_SIZE = 12 + RGL_STRING_SIZE
OPTIONS = 40
PARTNER_OPTIONS = OPTIONS + 1024 * OPTION_SIZE
SPEAKER_TEXT = PARTNER_OPTIONS + 1024 * OPTION_SIZE + 4

game = process.try_attach()
r = Reader(game)


def skill_id(skill):
    try:
        return r.rgl_string(skill + SKILL_ID)
    except ReadError:
        return ""


# 1. Every "skl_" whose rgl::string keeps it in its own static buffer
#    (short strings do): the string starts 16 bytes before the text.
firsts = set()
for start, size in game.regions():
    try:
        data = game.read(start, size)
    except Exception:
        continue
    i = data.find(b"skl_")
    while i != -1:
        skill = start + i - RGL_STRING_STATIC - SKILL_ID
        if skill_id(skill).startswith("skl_"):
            # 2. Walk back to skill 0: the first one in the run.
            while skill_id(skill - SKILL_SIZE).startswith("skl_"):
                skill -= SKILL_SIZE
            firsts.add(skill)
        i = data.find(b"skl_", i + 1)

for skills in sorted(firsts):
    run = [skill_id(skills + n * SKILL_SIZE) for n in range(NUM_SKILLS)]
    print(f"\nskills at {skills:#x}: {sum(s.startswith('skl_') for s in run)} of {NUM_SKILLS} ids look right")
    for n in range(NUM_SKILLS):
        s = skills + n * SKILL_SIZE
        try:
            name = r.rgl_string(s + RGL_STRING_SIZE)
            max_level, flags = r.i32(s + 3 * RGL_STRING_SIZE + 4), r.u32(s + 3 * RGL_STRING_SIZE + 16)
            print(f"  {n:2} {run[n]:24} {name!r} max {max_level} flags {flags:#x}")
        except ReadError as e:
            print(f"  {n:2} unreadable: {e}")

    # 3. Step back over the conversation manager and check it.
    cm = skills - 4 - CONV_SIZE
    try:
        head = struct.unpack("<10i", r.read(cm, 40))
    except ReadError as e:
        print(f"conversation manager {cm:#x} unreadable: {e}")
        continue
    try:
        first_id = r.rgl_string(head[1] + RGL_STRING_SIZE)
    except ReadError:
        first_id = "(unreadable)"
    print(f"\nconversation manager {cm:#x}: {head[0]} sentences, sentence 0 id {first_id!r}")
    print("  token", head[2], "partner troop", head[3], "party", head[4],
          "agent", head[5], "speaker agent", head[6], "cur sentence", head[7],
          "num_options", head[9])
    try:
        print("  speaker_text:", repr(r.rgl_string(cm + SPEAKER_TEXT)))
    except ReadError as e:
        print("  speaker_text unreadable:", e)
    for name, base in (("speaker", OPTIONS), ("partner", PARTNER_OPTIONS)):
        for n in range(min(max(head[9], 0), 12) or 3):
            o = cm + base + n * OPTION_SIZE
            try:
                no, rep, flags = struct.unpack("<iiI", r.read(o, 12))
                print(f"  {name}[{n}] sentence {no} flags {flags:#x}:", repr(r.rgl_string(o + 12)))
            except ReadError as e:
                print(f"  {name}[{n}] unreadable:", e)
