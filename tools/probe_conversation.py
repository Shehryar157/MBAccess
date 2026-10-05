"""Passive probe: find the conversation manager and check it against the screen.

    python tools/probe_conversation.py          print what it finds
    python tools/probe_conversation.py --save   also record it in the profile

Run it while a conversation is open (talk to anyone, e.g. a tavern keeper)
so the replies are on screen. It finds skills[0]'s id ("skl_trade") in the
exe's .data, steps back to conversation_manager.speaker_text (layout in
mbaccess/conversation.py), prints both option arrays, and says which one
matches the reply texts shown in window 12. It never presses anything.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbaccess import conversation as conv  # noqa: E402
from mbaccess import process, session  # noqa: E402
from mbaccess import text as text_mod  # noqa: E402
from mbaccess.mem import Reader, ReadError  # noqa: E402
from mbaccess.menu_watch import MenuWatcher  # noqa: E402

CONVERSATION_WINDOW = 12


def show_options(r, base, count, label):
    print(f"{label} options at {base:#x}:")
    texts = []
    for n in range(min(count, 20)):
        at = base + n * conv.OPTION_SIZE
        try:
            sentence, repeat, flags = (r.i32(at), r.i32(at + 4), r.u32(at + 8))
            words = r.rgl_string(at + conv.OPTION_TEXT)
        except ReadError as e:
            print(f"  {n}: unreadable ({e})")
            continue
        print(f"  {n}: sentence {sentence}, repeat {repeat}, flags {flags:#x}: {words!r}")
        texts.append(words)
    return texts


def main():
    game = process.try_attach()
    if game is None:
        print("The game isn't running.")
        return
    r = Reader(game)
    address, module = session.locate(game)
    print(f"game object {address:#x}, module {module!r}" if address else "no campaign yet")
    skills = session.load_skills(game, module or "Native")
    first = skills[0].id if skills else "skl_trade"
    text_at = conv.find(game, first)
    if text_at is None:
        print(f"Not in .data; searching all memory for {first!r} (a few seconds)...")
        text_at = conv.find(game, first, whole_memory=True)
    if text_at is None:
        print(f"No {first!r} skill id with a plausible conversation manager before it.")
        print("The live layout may differ from the WSE headers: tell Claude, with this output.")
        return
    count = r.i32(text_at + conv.NUM_OPTIONS)
    print(f"speaker_text at {text_at:#x}: {r.rgl_string(text_at)!r}")
    print(f"num_options {count}, partner troop {r.i32(text_at + conv.PARTNER_TROOP)}, "
          f"in_meta_mission {r.u32(text_at + conv.IN_META_MISSION)}")
    sides = {"speaker": show_options(r, text_at + conv.SPEAKER_OPTIONS, count, "speaker"),
             "partner": show_options(r, text_at + conv.PARTNER_OPTIONS, count, "partner")}

    w = MenuWatcher(r, None, game.profile.game_offsets, [], print, screen=game.profile.screen)
    top = w.top_window()
    print("top window:", top)
    if top != CONVERSATION_WINDOW:
        print("No conversation on screen, so the option arrays can't be checked. "
              "Run this again while talking to someone.")
        return
    on_screen = w.tree.texts(w.root(top))
    print("texts in the conversation window:")
    for words, p in on_screen.items():
        x, y = w.tree.position(p)
        print(f"  ({x:.3f}, {y:.3f}) class {r.ptr(p):#x}: {words[:70]!r}")
    scores = {side: sum(text_mod.clean(t) in on_screen for t in texts if t)
              for side, texts in sides.items()}
    print("replies found on screen:", scores)
    side = max(scores, key=scores.get)
    if not scores[side]:
        print("Neither array's texts are on screen: tell Claude, with this output.")
        return
    line = text_mod.clean(r.rgl_string(text_at))
    print(f"use options = {side!r}; spoken line on screen: {line in on_screen}")
    if "--save" in sys.argv:
        game.profile.screen["conversation"] = {"speaker_text": text_at, "options": side}
        game.profile.save()
        print("saved to", game.profile.path)


if __name__ == "__main__":
    main()
