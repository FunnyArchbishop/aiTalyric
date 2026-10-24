"""Motivic development: one motive -> an 8-bar section.

A motive is only useful once it has been developed.  Development here works on
the *motivic parameters* (the normalised contour and the note durations), not on
ready-made pitches, so every variant is re-decoded by the same joint DP and ends
up with its own harmony.

Transformations: original, transposition (modulation), inversion, retrograde,
augmentation, fragmentation.  Transposition must not destroy the contour, so a
DTW distance and a correlation against the source motive are reported and
checked - that is the "轮廓守护" guard.

    python develop.py                     # 8 bars from phrase A
    python develop.py --bars 16           # longer structure
    python develop.py --wav testdata/tts.wav --text 我想和你一起看海 \
        --tones 3,3,2,3,1,3,4,3
"""

import argparse
import json
import os

import numpy as np

import joint
import midi_io
import realize
import run_demo
import theory

W0 = dict(run_demo.W0)


# ------------------------------------------------------------- transformations

def transform(slots, kind, semis=0, factor=2.0):
    """Return a new slot list (targets and durations), in motive order."""
    out = [dict(s) for s in slots]
    if kind == "orig":
        return out
    if kind == "transpose":
        return out                       # handled by shifting the tonic instead
    if kind == "invert":
        for s in out:
            s["target"] = -s["target"]
        return out
    if kind == "retrograde":
        out.reverse()
        return out
    if kind == "augment":
        for s in out:
            s["dur"] = s["dur"] * factor
        return out
    if kind == "diminish":
        for s in out:
            s["dur"] = max(0.125, s["dur"] / factor)
        return out
    if kind == "fragment":
        half = max(1, len(out) // 2)
        out = out[:half]
        return out * 2                  # state it twice in the bar
    raise SystemExit("unknown transform: %s" % kind)


def section_plan(bars):
    """A A A' A' B B A'' A'' with a harmonic arc T S T S D D T T."""
    kinds = ["orig", "orig", "transpose", "transpose",
             "invert", "invert", "orig", "orig"]
    roles = ["T", "S", "T", "S", "D", "D", "T", "T"]
    return [dict(kind=kinds[i % len(kinds)], role=roles[i % len(roles)])
            for i in range(bars)]


# ------------------------------------------------------------------- contour

def dp_contour(path, world):
    return [float(world["P"][p]) for (_, _, p) in path]


def dtw(a, b):
    n, m = len(a), len(b)
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            c = abs(a[i - 1] - b[j - 1])
            D[i, j] = c + min(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])
    return float(D[n, m] / max(n, m))


def contour_corr(a, b, n=24):
    """Pearson correlation of two contours resampled to the same length."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    x = np.linspace(0, 1, n)
    ya = np.interp(x, np.linspace(0, 1, len(a)), a)
    yb = np.interp(x, np.linspace(0, 1, len(b)), b)
    ya = ya - ya.mean()
    yb = yb - yb.mean()
    den = float(np.linalg.norm(ya) * np.linalg.norm(yb))
    return float(np.dot(ya, yb) / den) if den > 1e-9 else 0.0


# --------------------------------------------------------------------- driver

def build_source(a):
    """The motive: slots from the intonation pipeline (5-point shape etc.)."""
    style = realize.load_style(a.style_file or None)
    if a.melisma is not None:
        style["melisma"] = a.melisma
    style["elongate"] = float(getattr(a, "elongate", 1.0))
    style["min_note"] = float(getattr(a, "min_note", 0.5))
    if a.cell_theme != "none":
        style["cell"] = min(float(style.get("cell", realize.GRID)),
                            max(0.125, style["min_note"] / 2.0))

    if a.wav:
        import f0_from_wav
        import prosody
        import align
        import math
        x, fs = f0_from_wav.read_wav(a.wav)
        tones = [int(t) for t in a.tones.split(",")] if a.tones.strip() else []
        syls = align.parse_syllables(a.text, a.pinyin.strip() or None)
        chars = [s["char"] for s in syls]
        tones = (tones + [1] * len(chars))[:len(chars)]
        bounds, _ = align.align(x, fs, a.text, tones, a.pinyin.strip() or None, adapt=2)
        times, f0, rms, clar = f0_from_wav.f0_track(x, fs)
        f0s = f0_from_wav.repair_octaves(times, f0_from_wav.median_filter(f0, 5))
        samples = [(t, 12.0 * math.log2(v / a.ref_hz) if v > 0 else -2.0)
                   for t, v in zip(times, f0s)]
        params = prosody.extract_params(chars, theory.apply_sandhi(chars, tones),
                                        [e - s for s, e in bounds], samples, bounds,
                                        tempo=a.tempo, span_semitones=a.span,
                                        stretch=a.stretch, smooth=a.smooth,
                                        sub_points=int(style.get("sub_points", 5)))
    else:
        ns = argparse.Namespace(**vars(a))
        params, _ = run_demo.build(ns)
    params["tonic"] = a.tonic
    params["mode"] = a.mode
    slots, chord_at, info = realize.realize(params, style=style,
                                            rhythm_theme=a.cell_theme,
                                            variation_every=a.variation_every)
    return params, slots, chord_at, style


def render_section(params, slots, style, kind, semis, tonic_offset,
                   start_role="T", end_tonic=False, chords_per_bar=2):
    """Decode one section and return (notes, chord_runs, metrics)."""
    p = dict(params)
    p["tonic"] = params["tonic"] + tonic_offset
    p["contour"] = [s["target"] for s in slots]
    p["beats"] = [s["dur"] for s in slots]
    n = len(slots)
    step = max(1, n // max(1, chords_per_bar))
    p["chord_at"] = [(i % step == 0) for i in range(n)]
    p["gestures"] = [dict(tone=0, dir=0, low=False, measured_slope=0.0, conflict=False)
                     for _ in slots]
    p["motion_w"] = [1.0] * len(slots)
    p["start_role"] = start_role
    p["must_end_tonic"] = end_tonic
    p["end_pref"] = bool(end_tonic)   # only the last bar needs a cadence
    path, ev, world = joint.solve_joint(p, W0, step)
    notes, start = [], 0.0
    for (_, c, pi) in path:
        notes.append(dict(start=start, dur=p["beats"][len(notes)],
                          midi=world["P"][pi], chord=world["vocab"][c][0]))
        start += p["beats"][len(notes) - 1]
    runs = []
    for j, (_, c, _) in enumerate(path):
        if j == 0 or path[j][1] != path[j - 1][1]:
            runs.append(dict(chord=world["vocab"][c][0], start=notes[j]["start"]))
    return notes, runs, ev, world


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phrase", default="A", choices=list(run_demo.PHRASES))
    ap.add_argument("--wav", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--tones", default="")
    ap.add_argument("--pinyin", default="")
    ap.add_argument("--tempo", type=float, default=120.0)
    ap.add_argument("--tonic", type=int, default=60)
    ap.add_argument("--mode", default="major", choices=list(theory.SCALES))
    ap.add_argument("--span", type=float, default=12.0)
    ap.add_argument("--stretch", type=float, default=1.0)
    ap.add_argument("--smooth", type=int, default=1)
    ap.add_argument("--ref-hz", type=float, default=220.0)
    ap.add_argument("--melisma", type=int, default=None)
    ap.add_argument("--elongate", type=float, default=1.0,
                    help="stretch each section (1 = one bar per section)")
    ap.add_argument("--min-note", type=float, default=0.5,
                    help="shortest note in beats")
    ap.add_argument("--style-file", default="")
    ap.add_argument("--cell-theme", default="sync", choices=list(__import__("rhythm").THEMES))
    ap.add_argument("--variation-every", type=int, default=4)
    ap.add_argument("--bars", type=int, default=8)
    ap.add_argument("--modulate", type=int, default=2, help="transposition in semitones")
    ap.add_argument("--min-corr", type=float, default=0.80,
                    help="contour guard for transpositions")
    ap.add_argument("--out", default="out_dev")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    params, slots, chord_at, style = build_source(a)
    src_path_notes, _, src_ev, src_world = render_section(params, slots, style,
                                                          "orig", 0, 0,
                                                          start_role="T")
    src_contour = [n["midi"] for n in src_path_notes]
    bar_beats = 4.0 * max(0.25, float(getattr(a, "elongate", 1.0)))

    plan = section_plan(a.bars)
    melody, chords, rows = [], [], []
    t0 = 0.0
    for idx, sec in enumerate(plan):
        kind = sec["kind"]
        offset = a.modulate if kind == "transpose" else 0
        sec_slots = transform(slots, "orig" if kind == "transpose" else kind)
        last = (idx == len(plan) - 1)
        notes, runs, ev, world = render_section(
            params, sec_slots, style, kind, a.modulate, offset,
            start_role=sec["role"], end_tonic=last)
        # fit the section into one bar by scaling if needed
        total = sum(n["dur"] for n in notes)
        scale = (bar_beats / total) if total > 0 else 1.0
        if abs(scale - 1.0) > 1e-9:
            acc = 0.0
            for n in notes:
                n["dur"] *= scale
                n["start"] = acc
                acc += n["dur"]
            for r in runs:
                r["start"] *= scale
        for n in notes:
            melody.append((t0 + n["start"], n["dur"] * 0.95, n["midi"],
                           92 if n["start"] % 1.0 < 1e-6 else 78))
        # chord block for the whole bar
        pcs = None
        if runs:
            label = runs[0]["chord"]
            ci = [j for j, v in enumerate(world["vocab"]) if v[0] == label]
            if ci:
                pcs = theory.voicing(world["vocab"][ci[0]], params["tonic"] + offset)
        if pcs:
            for q in pcs:
                chords.append((t0, bar_beats * 0.92, q, 70 if q < 52 else 62))
        cont = [n["midi"] for n in notes]
        rows.append(dict(bar=idx + 1, kind=kind, semis=offset,
                         notes=len(notes), tonic=theory.note_name(params["tonic"] + offset),
                         dtw=round(dtw(src_contour, cont), 2),
                         corr=round(contour_corr(src_contour, cont), 3),
                         chords="-".join(r["chord"] for r in runs)))
        t0 += bar_beats

    L = ["=" * 86,
         "动机发展：%d 小节（源动机 %d 音，%s %s）"
         % (a.bars, len(slots), theory.note_name(a.tonic), a.mode),
         "=" * 86,
         "小节 变换        移调  音符  主音    DTW   相关  和弦",
         "-" * 86]
    for r in rows:
        L.append("%4d %-12s %+4d %5d  %-4s %6.2f %6.3f  %s"
                 % (r["bar"], r["kind"], r["semis"], r["notes"], r["tonic"],
                    r["dtw"], r["corr"], r["chords"]))
    L.append("")
    transposed = [r for r in rows if r["kind"] == "transpose"]
    if transposed:
        worst = min(r["corr"] for r in transposed)
        L.append("轮廓守护：移调段落与源动机相关度最低 %.3f（阈值 %.2f）→ %s"
                 % (worst, a.min_corr, "通过" if worst >= a.min_corr else "未通过"))
    L.append("说明：每小节内部仍由联合 DP 重新解出旋律与和弦；小节之间只允许在"
             "乐句开头换和弦，故本版每小节 1 个和弦。")

    mid = os.path.join(a.out, "developed.mid")
    midi_io.write_midi(mid, a.tempo, [("melody", 73, melody), ("chords", 0, chords)])
    with open(os.path.join(a.out, "report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    with open(os.path.join(a.out, "structure.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print("[ok]", mid)
    print("[ok]", os.path.join(a.out, "report.txt"))
    for r in rows:
        print("bar %2d %-11s %+d  corr=%+.3f  dtw=%5.2f  %s"
              % (r["bar"], r["kind"], r["semis"], r["corr"], r["dtw"], r["chords"]))


if __name__ == "__main__":
    main()
