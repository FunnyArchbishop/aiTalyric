"""ex02: the style knobs - change what a syllable expands into.

`realize.DEFAULT_STYLE` is the whole surface: note-count rules, duration
patterns, grace notes, grid, swing, accents.  You can edit the dict in memory,
write a JSON file, or override single keys from the CLI.

    python examples/ex02_style_knobs.py
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import realize      # noqa: E402
import run_demo     # noqa: E402


def build():
    a = type("A", (), dict(phrase="A", tempo=120.0, tonic=60, mode="major",
                           span=12.0, stretch=1.0, smooth=1))()
    params, _ = run_demo.build(a)
    return params


params = build()
base = realize.load_style(None)

variants = {
    "default (2 extra notes)": base,
    "one note per syllable": {**copy.deepcopy(base), "melisma": 0},
    "four notes per syllable": {**copy.deepcopy(base), "melisma": 3,
                                "note_rules": {**base["note_rules"],
                                               "two_above": 0.2, "three_above": 0.3}},
    "always 2 notes": {**copy.deepcopy(base),
                       "note_rules": {**base["note_rules"], "two_above": 0.0}},
    "32nd grid": {**copy.deepcopy(base), "cell": 0.125},
}

print("%-26s %6s %8s  %s" % ("style", "notes", "beats", "why per syllable"))
for name, st in variants.items():
    slots, chord_at, info = realize.realize(params, style=st)
    why = " ".join("%d" % i["notes"] for i in info)
    total = sum(s["dur"] for s in slots)
    print("%-26s %6d %8.2f  %s" % (name, len(slots), total, why))

print()
print("write the default out, edit it, load it back:")
p = realize.dump_style("out_examples/style.json")
st = realize.load_style(p)
st["grace"]["enabled"] = True
st["grace"]["rise_above"] = 0.02
slots, _, info = realize.realize(params, style=st)
print("  with grace enabled :", len(slots), "notes")
print("[ok]", p)
