"""Words for the face editor (window 31), so a blind player knows what the
face looks like, not just where 27 sliders stand.

Each slider gets a feature noun and words for its two ends: "Nose Size" ->
("nose", "small", "large"). A slider's value is then spoken in five bands
("very small" .. "very large") before its percentage, and the portrait lists
the features furthest from average, top of the head down to the chin:
"Young man, light hair. Wide face, very large hooked nose."

ASSUMED, NOT VERIFIED: slider left = less of the thing. skins.txt gives some
face keys a backwards range (chin size +0.7 .. -0.6), so check a few by
screenshot. Hair colour IS known: each skin's hair colour list in skins.txt
runs light to dark.
"""
from .form import Item

# label: (noun, word at the left end, word at the right end). Order = top to bottom of the face.
FEATURES = {
    "Hair Color": ("hair", "light", "dark"),
    "Face Width": ("face", "narrow", "wide"),
    "Face Ratio": ("face", "short", "long"),
    "Face Depth": ("profile", "flat", "deep"),
    "Temple Width": ("temples", "narrow", "wide"),
    "Eyebrow Shape": ("eyebrows", "straight", "arched"),
    "Eyebrow Depth": ("brow", "flat", "heavy"),
    "Eyebrow Height": ("eyebrows", "low", "high"),
    "Eyebrow Position": ("eyebrows", "set back", "set forward"),
    "Eyelids": ("eyelids", "thin", "heavy"),
    "Eye Depth": ("eyes", "prominent", "deep-set"),
    "Eye Shape": ("eyes", "round", "narrow"),
    "Eye to Eye Dist": ("eyes", "close-set", "wide-set"),
    "Eye Width": ("eyes", "small", "large"),
    "Cheek Bones": ("cheekbones", "low", "high"),
    "Nose Bridge": ("nose bridge", "low", "high"),
    "Nose Height": ("nose", "low-set", "high-set"),
    "Nose Width": ("nose", "narrow", "wide"),
    "Nose Size": ("nose", "small", "large"),
    "Nose Shape": ("nose", "straight", "hooked"),
    "Cheeks": ("cheeks", "hollow", "full"),
    "Mouth Width": ("mouth", "narrow", "wide"),
    "Mouth-Nose Distance": ("upper lip", "short", "long"),
    "Jaw Width": ("jaw", "narrow", "wide"),
    "Jaw Position": ("jaw", "set back", "set forward"),
    "Chin Size": ("chin", "small", "large"),
    "Chin Shape": ("chin", "pointed", "square"),
    "Chin Forward": ("chin", "receding", "jutting"),
}
AGES = ("very young", "young", "middle-aged", "older", "old")
AVERAGE = 0.15          # within this of the middle counts as average
MOST = 6                # features named in the portrait


def band(fraction):
    """0..4: very low, low, average, high, very high."""
    return sum(fraction >= edge for edge in (0.15, 0.35, 0.65, 0.85))


def word(label, fraction):
    """"very large", "small", "average"; "" for an unknown slider."""
    if label == "Age":
        return AGES[band(fraction)]
    if label not in FEATURES:
        return ""
    _, low, high = FEATURES[label]
    middle = "medium-shade" if label == "Hair Color" else "average"
    return ("very " + low, low, middle, high, "very " + high)[band(fraction)]


def portrait(sliders, gender="", skin=""):
    """sliders: {label: fraction}; skin: a tone word. A short description of the face."""
    age = AGES[band(sliders["Age"])] if "Age" in sliders else ""
    who = " ".join(w for w in (age, gender or "person") if w)
    hair = sliders.get("Hair Color")
    first = who[:1].upper() + who[1:] + (f", {skin} skin" if skin else "") + \
        (f", {word('Hair Color', hair)} hair" if hair is not None else "")
    notable = sorted((abs(f - 0.5), label) for label, f in sliders.items()
                     if label in FEATURES and label != "Hair Color" and abs(f - 0.5) > AVERAGE)
    chosen = {label for _, label in notable[-MOST:]}
    nouns = {}          # noun -> adjectives, in face order
    for label in FEATURES:
        if label in chosen:
            nouns.setdefault(FEATURES[label][0], []).append(word(label, sliders[label]))
    if not nouns:
        return first + ". An average face."
    parts = [", ".join(adjectives) + " " + noun for noun, adjectives in nouns.items()]
    text = "; ".join(parts)
    return f"{first}. {text[:1].upper() + text[1:]}."


SKIN_TONES = ((0.88, "fair"), (0.8, "light"), (0.65, "tan"), (0.55, "brown"), (0.0, "dark"))


def tone(colour):
    """A skin texture's colour (0xAARRGGBB in skins.txt) as a word, by brightness."""
    brightness = sum((colour >> shift) & 0xFF for shift in (0, 8, 16)) / 765
    return next(word for edge, word in SKIN_TONES if brightness >= edge)


def styles(skin, beard, hair, face_no):
    """The pickers' values from the editor's numbers (counted from 0) and
    the player's skin (modfiles.Skin): {"Skin": "6 of 8, light", ...}."""
    def place(n, total):
        return f"{n + 1} of {total}" if 0 <= n < total else "none"
    found = {"Hair": place(hair, len(skin.hairs))}
    if skin.beards:
        found["Beard"] = place(beard, len(skin.beards))
    if 0 <= face_no < len(skin.faces):
        found["Skin"] = f"{place(face_no, len(skin.faces))}, {tone(skin.faces[face_no][1])}"
    return found


def dress(items, gender="", picked=None):
    """Give the face editor's sliders words and its pickers their style
    (picked: from styles()), and put the portrait first."""
    picked = picked or {}
    for i in items:
        if i.kind == "spinner" and i.label in picked:
            i.value = picked[i.label]
    sliders = {}
    for i in items:
        if i.kind == "slider" and (i.label in FEATURES or i.label == "Age"):
            sliders[i.label] = i.fraction
            w = word(i.label, i.fraction)
            if w:
                i.value = f"{w}, {i.value}"
    if not sliders:
        return items
    skin = picked.get("Skin", "").split(", ")[-1] if "," in picked.get("Skin", "") else ""
    return [Item("text", "Portrait", 0.0, 1.0, value=portrait(sliders, gender, skin),
                 virtual="portrait")] + items
