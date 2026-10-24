"""ex03: add your own rhythmic theme.

A theme is just a dict in `rhythm.THEMES`:
    cells   : list of cells, each cell a list of sixteenth counts (sum 4 = 1 beat)
    pattern : letters over the syllables, A = cells[0], B = cells[1] ...
Adding one at runtime is enough - no registry, no restart.

    python examples/ex03_add_rhythm_theme.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import realize      # noqa: E402
import rhythm       # noqa: E402
import run_demo     # noqa: E402

rhythm.THEMES["threes"] = dict(
    cells=[[2, 1, 1], [1, 1, 1, 1], [3, 1], [1, 2, 1]],
    pattern="A B A C",
    note="custom: a 2-1-1 figure answered by a 16th run",
)

a = type("A", (), dict(phrase="A", tempo=120.0, tonic=60, mode="major",
                       span=12.0, stretch=1.0, smooth=1))()
params, _ = run_demo.build(a)
st = realize.load_style(None)
st["cell"] = 0.125                      # so a 4-sixteenth cell fits in a syllable

for name in ("none", "sync", "threes"):
    slots, _, info = realize.realize(params, style=st, rhythm_theme=name)
    spans = [max(1, int(round(b / st["cell"]))) for b in params["beats"]]
    s = rhythm.stats(rhythm.plan(spans, name, 4))
    print("%-8s notes=%2d reuse=%.2f  %s"
          % (name, len(slots), s["reuse"], s["pattern"] or "-"))

print()
print(rhythm.describe(rhythm.plan([max(1, int(round(b / st["cell"])))
                                   for b in params["beats"]], "threes", 4),
                      params["chars"]))
