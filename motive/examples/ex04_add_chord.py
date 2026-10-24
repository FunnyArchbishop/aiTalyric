"""ex04: add chords - and see why a bigger vocabulary can only help.

A chord entry is a tuple:
    (label, pitch-class offsets from the tonic, function,
     resolution target or None, bass offset, idiomaticity penalty)

Growing the vocabulary cannot hurt the joint decoder: the old optimum is still
in the search space, so total energy can only stay equal or go down.

    python examples/ex04_add_chord.py
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import joint        # noqa: E402
import run_demo     # noqa: E402
import theory       # noqa: E402

W = dict(run_demo.W0)
a = type("A", (), dict(phrase="A", tempo=120.0, tonic=60, mode="major",
                       span=12.0, stretch=1.0, smooth=1))()
params, _ = run_demo.build(a)


def run(tag):
    path, ev, world = joint.solve_joint(params, W, 2)
    prog = "-".join(world["vocab"][c][0] for (i, c, _) in path if i % 2 == 0)
    print("%-22s chords=%2d  total=%.3f  %s"
          % (tag, len(world["vocab"]), ev["total"], prog))
    return ev["total"]


base = run("stock vocabulary")

# borrowed bVII and a V9: chromatic colour the DP could not reach before
theory.CHORD_VOCAB["major"] = list(theory.CHORD_VOCAB["major"]) + [
    ("bVII", (10, 2, 5),  "S", None, 10, 0.35),
    ("V9",   (7, 11, 2, 5, 9), "D", None, 7, 0.15),
]
bigger = run("+ bVII and V9")

print()
print("energy %s (%.3f -> %.3f): a bigger vocabulary can never make the "
      "optimum worse, but it is only used when it actually pays"
      % ("improved" if bigger < base - 1e-9 else "unchanged", base, bigger))

# prove the new chord is really in the search space: shrink the vocabulary to
# I / bVII / V, so a four-chord progression has to use it
theory.CHORD_VOCAB["major"] = [
    ("I",    (0, 4, 7),   "T", None, 0,  0.0),
    ("bVII", (10, 2, 5),  "S", None, 10, 0.0),
    ("V",    (7, 11, 2),  "D", None, 7,  0.0),
]
run("vocabulary = I/bVII/V")

print()
print("the entry you add:", ("bVII", (10, 2, 5), "S", None, 10, 0.35))
print("its bass + upper voicing in C:", theory.voicing(("bVII", (10, 2, 5), "S", None, 10, 0.35), 60))
