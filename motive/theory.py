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

# Chord entry: (label, pitch-class offsets from tonic, function,
#               resolution target root offset or None, bass offset, penalty)
# - `bass offset` makes inversions real: the bass note (and therefore the
#   voice leading) differs from the root.
# - `target` marks a secondary dominant: it resolves to that root, and the
#   transition cost enforces it.
# - `penalty` is a small idiomaticity cost (64 chords are unstable, etc.)
CHORD_VOCAB = {
    "major": [
        ("I",    (0, 4, 7),      "T", None, 0,  0.00),
        ("I6",   (0, 4, 7),      "T", None, 4,  0.15),
        ("I64",  (0, 4, 7),      "T", None, 7,  0.40),
        ("ii",   (2, 5, 9),      "S", None, 2,  0.00),
        ("ii6",  (2, 5, 9),      "S", None, 5,  0.15),
        ("ii7",  (2, 5, 9, 0),   "S", None, 2,  0.05),
        ("iii",  (4, 7, 11),     "T", None, 4,  0.20),
        ("IV",   (5, 9, 0),      "S", None, 5,  0.00),
        ("IV6",  (5, 9, 0),      "S", None, 9,  0.15),
        ("IV7",  (5, 9, 0, 4),   "S", None, 5,  0.05),
        ("V",    (7, 11, 2),     "D", None, 7,  0.00),
        ("V6",   (7, 11, 2),     "D", None, 11, 0.15),
        ("V7",   (7, 11, 2, 5),  "D", None, 7,  0.00),
        ("V65",  (7, 11, 2, 5),  "D", None, 11, 0.05),
        ("V43",  (7, 11, 2, 5),  "D", None, 2,  0.25),
        ("vi",   (9, 0, 4),      "T", None, 9,  0.00),
        ("vi7",  (9, 0, 4, 7),   "T", None, 9,  0.05),
        ("vii",  (11, 2, 5),     "D", None, 11, 0.25),
        ("vii7", (11, 2, 5, 9),  "D", None, 11, 0.10),
        ("V/V",  (2, 6, 9),      "D", 7,  2,  0.10),
        ("V7/V", (2, 6, 9, 0),   "D", 7,  2,  0.05),
        ("V/ii", (9, 1, 4),      "D", 2,  9,  0.15),
        ("V/vi", (4, 8, 11),     "D", 9,  4,  0.15),
        ("vii/V", (6, 9, 0),     "D", 7,  6,  0.30),
    ],
    "minor": [
        ("i",    (0, 3, 7),      "T", None, 0,  0.00),
        ("i6",   (0, 3, 7),      "T", None, 3,  0.15),
        ("i64",  (0, 3, 7),      "T", None, 7,  0.40),
        ("ii",   (2, 5, 8),      "S", None, 2,  0.05),
        ("ii6",  (2, 5, 8),      "S", None, 5,  0.20),
        ("III",  (3, 7, 10),     "T", None, 3,  0.00),
        ("III6", (3, 7, 10),     "T", None, 7,  0.15),
        ("iv",   (5, 8, 0),      "S", None, 5,  0.00),
        ("iv6",  (5, 8, 0),      "S", None, 8,  0.15),
        ("IV",   (5, 9, 0),      "S", None, 5,  0.15),
        ("V",    (7, 11, 2),     "D", None, 7,  0.00),
        ("V7",   (7, 11, 2, 5),  "D", None, 7,  0.00),
        ("V65",  (7, 11, 2, 5),  "D", None, 11, 0.05),
        ("VI",   (8, 0, 3),      "T", None, 8,  0.00),
        ("VI6",  (8, 0, 3),      "T", None, 0,  0.15),
        ("VII",  (10, 2, 5),     "D", None, 10, 0.20),
        ("VII6", (10, 2, 5),     "D", None, 2,  0.30),
        ("vii",  (11, 2, 5),     "D", None, 11, 0.25),
        ("vii7", (11, 2, 5, 8),  "D", None, 11, 0.10),
        ("V/iv", (0, 4, 7),      "D", 5,  0,  0.15),
        ("V/VI", (3, 7, 10),     "D", 8,  3,  0.20),
        ("V/VII", (2, 6, 9),     "D", 10, 2,  0.20),
        ("V/III", (10, 2, 5),    "D", 3,  10, 0.20),
        ("N6",   (1, 5, 8),      "S", None, 1,  0.35),
    ],
}
CHORD_VOCAB["penta"] = CHORD_VOCAB["major"]


def voicing(chord, tonic, low=40, high=67, upper=3):
    """MIDI pitches for a chord entry: bass note + a closed upper voicing."""
    label, offs, role, target, bass_off, pen = chord
    pcs = [(tonic + o) % 12 for o in offs]
    bpc = (tonic + bass_off) % 12
    bass = next((q for q in range(low, low + 12) if q % 12 == bpc), low)
    ups = [q for q in range(55, high + 1) if q % 12 in pcs][:upper]
    return [bass] + ups

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
