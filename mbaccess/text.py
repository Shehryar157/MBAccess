"""Turning engine text into something pleasant to hear."""
import functools
import re

PLACEHOLDER = re.compile(r"\{[!]?[a-z]+\d*\}|\{reg\d+\}", re.IGNORECASE)
# Link tags around names in messages: <p=158>Ibdeles</> (place), <trp=314>Count Trimbau</>
# (troop). The game makes them clickable; we keep the name and drop the tags.
LINK_TAG = re.compile(r"<[a-z]+=\d+>|</>", re.IGNORECASE)


@functools.lru_cache(maxsize=4096)   # the same labels come back every tick
def clean(text):
    """'^' is the engine's line break; unfilled {s1}-style slots and link tags are dropped."""
    text = text.replace("^", "\n")
    text = PLACEHOLDER.sub("", text)
    text = LINK_TAG.sub("", text)
    lines = (" ".join(line.split()) for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def spoken(title, *parts):
    """Join for speech: "Main menu: Play Tutorial, 1 of 8".

    Synths (eSpeak especially) read straight through line breaks, so each
    line becomes a sentence: we add a full stop where it has no ending
    punctuation. The title, if any, gets a colon.
    """
    sentences = []
    for part in parts:
        for line in part.split("\n"):
            line = line.strip()
            if line:
                sentences.append(line if line[-1] in ".!?:;" else line + ".")
    body = " ".join(sentences)
    if title:
        return f"{title}: {body}" if body else title
    return body
