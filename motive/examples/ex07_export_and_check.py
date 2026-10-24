"""ex07: export and verify.

`.vsqx` for VOCALOID, `.ustx` for OpenUtau.  A syllable sung as several notes
gets its character on the first note and that syllable's vowel on the rest -
VOCALOID needs a lyric on every note.

    python examples/ex07_export_and_check.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import align        # noqa: E402
import export       # noqa: E402
import theory       # noqa: E402
import vsqx_pit     # noqa: E402

os.makedirs("out_examples", exist_ok=True)

# a small hand-made phrase: 我 (1 note), 想 (3 notes = a 转音), 你 (1 note)
slots = [
    dict(syl=0, k=0, first=True),
    dict(syl=1, k=0, first=True), dict(syl=1, k=1, first=False), dict(syl=1, k=2, first=False),
    dict(syl=2, k=0, first=True),
]
chars = ["我", "想", "你"]
finals = [s["final"] for s in align.parse_syllables("我想你")]
lyrics = export.lyrics_for(slots, chars, finals)
print("lyrics:", lyrics, "   <- character first, then the syllable's vowel")

notes = [
    dict(start=0.00, dur=0.50, midi=64, lyric=lyrics[0]),
    dict(start=0.50, dur=0.25, midi=62, lyric=lyrics[1]),
    dict(start=0.75, dur=0.25, midi=60, lyric=lyrics[2]),
    dict(start=1.00, dur=0.25, midi=59, lyric=lyrics[3]),
    dict(start=1.25, dur=1.00, midi=57, lyric=lyrics[4]),
]

v = export.write_vsqx("out_examples/ex07.vsqx", notes, tempo=96.0,
                      portamento=1.5, title="ex07")
u = export.write_ustx("out_examples/ex07.ustx", notes, tempo=96.0)
print("check :", export.check_vsqx(v, expect_notes=len(notes)))

# read it back with our own reader: note count and the F0 the PIT layer implies
info = vsqx_pit.parse_vsqx(v)
samples, ms_per_dot = vsqx_pit.to_samples(info)
print("read back: %d notes, %d PIT points, %.2f ms/dot, first f0 %.1f Hz"
      % (len(info["notes"]), len(samples), ms_per_dot, samples[0][1]))
print("syllables:", "".join(row[0] for row in vsqx_pit.to_syllables(info)))
print("[ok]", v)
print("[ok]", u)
