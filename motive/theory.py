"""Pitch / scale / chord / Mandarin-tone primitives.

Pure stdlib, no numpy.  This is the "vocabulary" layer: what pitches and
chords exist, and what a Mandarin tone *wants* to do melodically.
"""

TONE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(n):
    """66 -> 'F#4' (MIDI note number convention)."""
    return f"{TONE_NAMES[n % 12]}{n // 12 - 1}"


SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "penta": [0, 2, 4, 7, 9],          # 宫 商 角 徵 羽
}

# Functional harmony cost: (from_role, to_role) -> cost, lower is more idiomatic.
ROLE_COST = {
    ("T", "T"): 0.7, ("T", "S"): 0.4, ("T", "D"): 0.3,
    ("S", "T"): 1.2, ("S", "S"): 0.8, ("S", "D"): 0.3,
    ("D", "T"): 0.0, ("D", "S"): 1.4, ("D", "D"): 1.0,
}

# (label, pitch-class offsets from tonic, function)
CHORD_VOCAB = {
    "major": [
        ("I",   (0, 4, 7),     "T"),
        ("ii",  (2, 5, 9),     "S"),
        ("iii", (4, 7, 11),    "T"),
        ("IV",  (5, 9, 0),     "S"),
        ("V",   (7, 11, 2),    "D"),
        ("vi",  (9, 0, 4),     "T"),
        ("vii", (11, 2, 5),    "D"),
        ("V7",  (7, 11, 2, 5), "D"),
        ("ii7", (2, 5, 9, 0),  "S"),
    ],
    "minor": [
        ("i",   (0, 3, 7),     "T"),
        ("ii",  (2, 5, 8),     "S"),
        ("III", (3, 7, 10),    "T"),
        ("iv",  (5, 8, 0),     "S"),
        ("V",   (7, 11, 2),    "D"),
        ("VI",  (8, 0, 3),     "T"),
        ("VII", (10, 2, 5),    "D"),
        ("V7",  (7, 11, 2, 5), "D"),
    ],
}
CHORD_VOCAB["penta"] = CHORD_VOCAB["major"]

# --- Mandarin tone archetypes -------------------------------------------------
# Semitone offsets across the syllable, used to *synthesise* test prosody and to
# define what each tone "asks for" melodically.
TONE_CONTOUR = {
    1: [(0.00, 2.0), (1.00, 2.0)],                    # 55 high level
    2: [(0.00, -2.2), (1.00, 2.2)],                   # 35 rise
    3: [(0.00, -0.8), (0.55, -3.2), (1.00, -1.6)],    # 214 dip
    4: [(0.00, 3.2), (1.00, -3.2)],                   # 51 fall
    0: [(0.00, 0.4), (1.00, -0.2)],                   # neutral
}

TONE_LABEL = {1: "T1-flat", 2: "T2-rise", 3: "T3-dip", 4: "T4-fall", 0: "T0-neut"}
TONE_ZH = {1: "一声", 2: "二声", 3: "三声", 4: "四声", 0: "轻声"}

# The melodic *direction* a tone asks for when it is squeezed into one note.
# T1 = level, T2 = up, T3 = low/level (its dip cannot fit in one note),
# T4 = down.
TONE_DIR = {1: 0, 2: +1, 3: 0, 4: -1, 0: 0}
# Tones that want to sit low in the phrase register.
TONE_LOW = {1: False, 2: False, 3: True, 4: False, 0: False}


def apply_sandhi(chars, tones):
    """Minimal Mandarin tone sandhi: 3+3 -> 2+3, 不 -> 2 before 4th, 一 rules."""
    t = list(tones)
    for i in range(len(t) - 1):
        if t[i] == 3 and t[i + 1] == 3:
            t[i] = 2
    for i, ch in enumerate(chars):
        if i + 1 >= len(t):
            continue
        nxt = t[i + 1]
        if ch == "不" and nxt == 4:
            t[i] = 2
        elif ch == "一":
            if nxt == 4:
                t[i] = 2
            elif nxt in (1, 2, 3):
                t[i] = 4
    return t
