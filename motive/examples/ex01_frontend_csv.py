"""ex01: bring your own F0 (any TTS / recording / VvTalk render).

The only contract for the front end is:
    f0.csv : t_ms, f0_hz          (0 or NaN = unvoiced)
    syl.csv: char, tone, dur_ms   (or: char, tone, onset_ms, end_ms)
Everything downstream is unchanged.

    python examples/ex01_frontend_csv.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import f0_from_csv          # noqa: E402
import joint                # noqa: E402
import midi_io              # noqa: E402
import prosody              # noqa: E402
import theory               # noqa: E402

W = dict(w_contour=1.0, sigma=2.0, w_tone=1.2, w_harmony=1.0, w_motion=0.8)

# stand-in for a real front end: four syllables built from the tone archetypes,
# 200 ms each at a 10 ms hop, base pitch 210 Hz
chars = ["我", "想", "看", "海"]
tones = [3, 3, 4, 3]
samples, boundaries = [], []
t = 0.0
for tone in tones:
    start = t
    pts = theory.TONE_CONTOUR[tone]
    for k in range(20):
        x = k / 19.0
        y = pts[0][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= x <= x1:
                y = y0 + (x - x0) / (x1 - x0) * (y1 - y0) if x1 > x0 else y0
        samples.append((t, y))
        t += 10.0
    boundaries.append((start, t - 10.0))

import math
samples = [(tt, 12.0 * math.log2(210.0 * 2 ** (y / 12.0) / 220.0)) for tt, y in samples]
durs = [e - s for s, e in boundaries]

params = prosody.extract_params(chars, theory.apply_sandhi(chars, tones), durs,
                               samples, boundaries, tempo=120.0,
                               span_semitones=12.0, stretch=1.2, smooth=1)
params["tonic"] = 60
params["mode"] = "major"

path, ev, world = joint.solve_joint(params, W, 2)
print("contour :", [round(c, 2) for c in params["contour"]])
print("melody  :", [theory.note_name(world["P"][p]) for (_, _, p) in path])
print("chords  :", "-".join(world["vocab"][c][0] for (i, c, _) in path if i % 2 == 0))
print("metrics :", {k: round(ev[k], 2) for k in ("total", "contour_rms",
                                                 "harmony_violations")})

os.makedirs("out_examples", exist_ok=True)
midi_io.write_midi("out_examples/ex01.mid", 120.0,
                   [("m", 73, [(float(i), params["beats"][i] * 0.95, world["P"][p])
                               for i, (_, _, p) in enumerate(path)])])
print("[ok] out_examples/ex01.mid")
