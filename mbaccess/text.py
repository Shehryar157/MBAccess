"""Turning engine text into something pleasant to hear."""
import re

PLACEHOLDER = re.compile(r"\{[!]?[a-z]+\d*\}|\{reg\d+\}", re.IGNORECASE)


def clean(text):
    """'^' is the engine's line break; unfilled {s1}-style slots are dropped."""
    text = text.replace("^", "\n")
    text = PLACEHOLDER.sub("", text)
    lines = (" ".join(line.split()) for line in text.split("\n"))
    return "\n".join(line for line in lines if line)
