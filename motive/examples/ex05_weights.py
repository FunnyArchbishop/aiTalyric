"""ex05: the objective's weights are the real artistic controls.

W = dict(w_contour, sigma, w_tone, w_harmony, w_motion)
  w_contour  how hard the melody tracks the intonation contour
  sigma      how forgiving that tracking is (in semitones)
  w_tone     how strictly Mandarin tone directions must survive (倒字)
  w_harmony  how much a melody note must belong to the chord
  w_motion   how much leaps are discouraged

Not every weight bites on every phrase - that is the point of printing both.

    python examples/ex05_weights.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import joint        # noqa: E402
import run_demo     # noqa: E402
import theory       # noqa: E402

VARIANTS = [
    ("baseline",           dict(run_demo.W0)),
    ("tone strict x2.5",   dict(run_demo.W0, w_tone=3.0)),
    ("tone loose /6",      dict(run_demo.W0, w_tone=0.2)),
    ("contour dominates",  dict(run_demo.W0, w_contour=3.0, w_harmony=0.3)),
    ("harmony dominates",  dict(run_demo.W0, w_harmony=3.0, w_contour=0.3)),
    ("no leap penalty",    dict(run_demo.W0, w_motion=0.0)),
]

for phrase in ("A", "B"):
    a = type("A", (), dict(phrase=phrase, tempo=120.0, tonic=60, mode="major",
                           span=12.0, stretch=1.0, smooth=1))()
    params, _ = run_demo.build(a)
    print("=== phrase %s : %s ===" % (phrase, "".join(params["chars"])))
    print("%-20s %10s %6s %8s %9s  %s"
          % ("weights", "contourRMS", "倒字", "非和弦", "最大音程", "melody"))
    for name, W in VARIANTS:
        path, ev, world = joint.solve_joint(params, W, 2)
        mel = " ".join(theory.note_name(world["P"][p]) for (_, _, p) in path)
        print("%-20s %10.2f %6d %8d %9d  %s"
              % (name, ev["contour_rms"], ev["tone_violations"],
                 ev["harmony_violations"], ev["max_leap"], mel))
    print()

print("读法：w_tone 在 A 句上完全不敏感（旋律本来就在下行、不冲突），"
      "在 B 句上放松到 0.2 就出现 3 处倒字，换来更贴轮廓。")
