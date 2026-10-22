"""Real-intonation adapter: plug any F0 source into the motive pipeline.

Two CSV inputs, nothing else:

    syllables.csv   char,tone,dur_ms            (or char,tone,onset_ms,end_ms)
    f0.csv          t_ms,f0_hz                  (10 ms hop is fine)

Then:

    python f0_from_csv.py --syl syl.csv --f0 f0.csv --tonic 60 --stretch 1.3

The F0 source can be a TTS (CosyVoice2 / GPT-SoVITS / IndexTTS ...), a VvTalk
render, a human 示读 recording, anything that yields (time, Hz).  Unvoiced
frames may be 0 or NaN; they are skipped and never break a syllable's median.
"""

import argparse
import csv
import json
import math
import os

import joint
import midi_io
import prosody
import theory
import run_demo

W = dict(w_contour=1.0, sigma=2.0, w_tone=1.2, w_harmony=1.0, w_motion=0.8)


def read_syllables(path):
    chars, tones, durs, bounds, t = [], [], [], [], 0.0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ch = row["char"].strip()
            tone = int(row.get("tone") or 0)
            if "dur_ms" in row and row["dur_ms"]:
                d = float(row["dur_ms"])
                s, e = t, t + d
            else:
                s, e = float(row["onset_ms"]), float(row["end_ms"])
                d = e - s
            chars.append(ch)
            tones.append(tone)
            durs.append(d)
            bounds.append((s, e))
            t = e
    return chars, tones, durs, bounds


def read_f0(path, ref_hz=220.0):
    """Return [(t_ms, semitones relative to ref)] with unvoiced frames dropped."""
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            t = float(row["t_ms"])
            try:
                hz = float(row["f0_hz"])
            except (TypeError, ValueError):
                continue
            if not hz or hz <= 0 or math.isnan(hz):
                continue
            out.append((t, 12.0 * math.log2(hz / ref_hz)))
    if not out:
        raise SystemExit("no voiced frames in %s" % path)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syl", required=True)
    ap.add_argument("--f0", required=True)
    ap.add_argument("--ref-hz", type=float, default=220.0,
                    help="reference pitch for the semitone conversion (A3=220)")
    ap.add_argument("--tonic", type=int, default=60)
    ap.add_argument("--mode", default="major", choices=list(theory.SCALES))
    ap.add_argument("--tempo", type=float, default=120.0)
    ap.add_argument("--span", type=float, default=12.0)
    ap.add_argument("--stretch", type=float, default=1.0)
    ap.add_argument("--smooth", type=int, default=1)
    ap.add_argument("--chord-rate", type=int, default=2)
    ap.add_argument("--out", default="out_real")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    chars, tones, durs, bounds = read_syllables(a.syl)
    samples = read_f0(a.f0, a.ref_hz)
    # tone sandhi happens before extraction, as it does in speech
    tones2 = theory.apply_sandhi(chars, tones)

    params = prosody.extract_params(chars, tones2, durs, samples, bounds,
                                    tempo=a.tempo, span_semitones=a.span,
                                    stretch=a.stretch, smooth=a.smooth)
    params["tonic"] = a.tonic
    params["mode"] = a.mode

    path, ev, world = joint.solve_joint(params, W, a.chord_rate)
    melody, chords = run_demo.chord_tracks(path, params, world, a.chord_rate)
    midi_io.write_midi(os.path.join(a.out, "motive.mid"), a.tempo,
                       [("melody", 73, melody), ("chords", 0, chords)])
    with open(os.path.join(a.out, "motive_params.json"), "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)

    print("syllables :", "".join(chars))
    print("tones     :", tones2)
    print("contour   :", [round(x, 2) for x in params["contour"]])
    print("melody    :", [theory.note_name(world["P"][p]) for (_, _, p) in path])
    print("chords    :", run_demo.progression(path, world, a.chord_rate))
    print("contourRMS=%.2f  toneViol=%d  nonChord=%d  stepwise=%.2f" %
          (ev["contour_rms"], ev["tone_violations"], ev["harmony_violations"],
           ev["stepwise_ratio"]))
    print("[ok] wrote", os.path.join(a.out, "motive.mid"))


if __name__ == "__main__":
    main()
