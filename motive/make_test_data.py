"""Generate a pair of CSVs that mimic a real F0 front end (TTS / VvTalk / 示读).

Writes testdata/f0.csv (t_ms,f0_hz with 0 in silence) and
testdata/syl.csv (char,tone,onset_ms,end_ms), taken from the same synthetic
prosody the demo uses, so the adapter path can be verified end to end.
"""

import csv
import os

import prosody
import run_demo

os.makedirs("testdata", exist_ok=True)
_, syll, durs = run_demo.PHRASES["A"]
chars = [c for c, _ in syll]
tones = [t for _, t in syll]
samples, bounds, tones2 = prosody.synth_prosody(chars, tones, durs)


def voiced(t):
    return any(s <= t < e for (s, e) in bounds)


with open("testdata/f0.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["t_ms", "f0_hz"])
    for t, v in samples:
        hz = 220.0 * (2.0 ** (v / 12.0)) if voiced(t) else 0.0
        w.writerow([round(t, 1), round(hz, 2)])

with open("testdata/syl.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["char", "tone", "onset_ms", "end_ms"])
    for ch, tn, (s, e) in zip(chars, tones, bounds):
        w.writerow([ch, tn, round(s, 1), round(e, 1)])

print("[ok] testdata/f0.csv + testdata/syl.csv")
