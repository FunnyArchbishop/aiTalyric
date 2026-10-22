"""Melisma + groove version of the generator.

    python run_groove.py                          # synthetic phrase A, 转音 + 16th grid
    python run_groove.py --melisma 1 --style even
    python run_groove.py --wav testdata/tts.wav --text 我想和你一起看海 \
        --tones 3,3,2,3,1,3,4,3 --melisma 3 --swing 0.5 --push 0,1,0,-1

Everything about the expansion is editable:

    python run_groove.py --dump-style style.json     # write a documented default
    python run_groove.py --style-file style.json     # use it
    python run_groove.py --override 5:3,7:4          # force note counts (1-based)
    python run_groove.py --grace                     # allow 倚音
    python run_groove.py --dump-slots slots.json     # export realized notes (+pitch, +chord)
    python run_groove.py --from-slots slots.json     # render a hand-edited file

One syllable is no longer one note.  Syllables whose own F0 curve turns get
2-3 stepwise notes, the line sits on a 16th grid, and the joint decoder still
chooses melody and chords together.
"""

import argparse
import json
import os

import align
import joint
import midi_io
import realize
import rhythm
import run_demo
import theory

W0 = dict(run_demo.W0)


def load_params(a, style):
    if a.wav:
        import f0_from_wav
        import prosody
        x, fs = f0_from_wav.read_wav(a.wav)
        tones = [int(t) for t in a.tones.split(",")] if a.tones.strip() else []
        syl_in = align.parse_syllables(a.text, a.pinyin.strip() or None)
        chars = [s["char"] for s in syl_in]
        tones = (tones + [1] * len(chars))[:len(chars)]
        bounds = None
        bounds, _ = align.align(x, fs, a.text, tones, a.pinyin.strip() or None,
                                adapt=a.adapt)
        times, f0, rms, clar = f0_from_wav.f0_track(x, fs)
        f0s = f0_from_wav.repair_octaves(times, f0_from_wav.median_filter(f0, 5))
        import math
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
    return params


def parse_override(text):
    out = {}
    if not text:
        return out
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        k, v = part.split(":")
        out[int(k)] = int(v)
    return out


def chord_runs(path, world):
    """Contiguous runs of one chord: [(first_slot, last_slot, chord_index)]."""
    runs, j = [], 0
    while j < len(path):
        c = path[j][1]
        k = j
        while k + 1 < len(path) and path[k + 1][1] == c:
            k += 1
        runs.append((j, k, c))
        j = k + 1
    return runs


def chords_from_runs(runs, slots, params, world):
    out = []
    for (j0, j1, c) in runs:
        start = slots[j0]["start"]
        end = slots[j1]["start"] + slots[j1]["dur"]
        pcs = {(params["tonic"] + o) % 12 for o in world["vocab"][c][1]}
        for q in [q for q in range(52, 68) if q % 12 in pcs][:3]:
            out.append((start, end - start, q))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phrase", default="A", choices=list(run_demo.PHRASES))
    ap.add_argument("--wav", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--tones", default="")
    ap.add_argument("--pinyin", default="")
    ap.add_argument("--adapt", type=int, default=2)
    ap.add_argument("--tempo", type=float, default=120.0)
    ap.add_argument("--tonic", type=int, default=60)
    ap.add_argument("--mode", default="major", choices=list(theory.SCALES))
    ap.add_argument("--span", type=float, default=12.0)
    ap.add_argument("--stretch", type=float, default=1.0)
    ap.add_argument("--smooth", type=int, default=1)
    ap.add_argument("--ref-hz", type=float, default=220.0)
    # style controls
    ap.add_argument("--melisma", type=int, default=None, help="max extra notes")
    ap.add_argument("--style", default=None, help="duration pattern name")
    ap.add_argument("--swing", type=float, default=None)
    ap.add_argument("--push", default=None)
    ap.add_argument("--chord-every", type=int, default=None)
    ap.add_argument("--grace", action="store_true", help="allow 倚音 grace notes")
    ap.add_argument("--cell-theme", default="none",
                    choices=list(rhythm.THEMES), help="rhythmic cell theme")
    ap.add_argument("--variation-every", type=int, default=4,
                    help="augment one cell every N syllables (0 = never)")
    ap.add_argument("--override", default="", help="force note counts, e.g. 5:3,7:4")
    ap.add_argument("--style-file", default="")
    ap.add_argument("--dump-style", default="")
    ap.add_argument("--dump-slots", default="")
    ap.add_argument("--from-slots", default="")
    ap.add_argument("--out", default="out_groove")
    a = ap.parse_args()

    if a.dump_style:
        print("[ok] wrote", realize.dump_style(a.dump_style))
        return

    os.makedirs(a.out, exist_ok=True)
    style = realize.load_style(a.style_file or None)
    if a.melisma is not None:
        style["melisma"] = a.melisma
    if a.swing is not None:
        style["swing"] = a.swing
    if a.push is not None:
        style["push"] = a.push
    if a.chord_every is not None:
        style["chord_every"] = a.chord_every
    if a.grace:
        style["grace"]["enabled"] = True
    pattern = a.style or "tail"
    overrides = parse_override(a.override)

    params = load_params(a, style)

    # A rhythmic cell is 4 sixteenths; a syllable measured at ~0.5 beat only has
    # room for 2 sixteenths, so the cell would be truncated and never heard.
    # Refine the grid until the cell fits inside a typical syllable.
    if a.cell_theme != "none":
        cell = float(style.get("cell", realize.GRID))
        med_beats = sorted(params["beats"])[len(params["beats"]) // 2]
        need = max(sum(c) for c in rhythm.THEMES[a.cell_theme]["cells"])
        while med_beats / cell < need and cell > 0.0625:
            cell /= 2.0
        if abs(cell - float(style.get("cell", realize.GRID))) > 1e-9:
            print("[grid] cell %.3f -> %.3f beats so a %d-sixteenth cell fits the syllables"
                  % (float(style.get("cell", realize.GRID)), cell, need))
        style["cell"] = cell

    slots, chord_at, info = realize.realize(params, style=style,
                                            pattern=pattern, overrides=overrides,
                                            rhythm_theme=a.cell_theme,
                                            variation_every=a.variation_every)
    rp = rhythm.plan([max(1, int(round(b / float(style.get("cell", realize.GRID)))))
                      for b in params["beats"]], a.cell_theme, a.variation_every) \
        if a.cell_theme != "none" else None
    rstats = rhythm.stats(rp)
    p2 = realize.to_params(params, slots, chord_at)

    if a.from_slots:
        doc = realize.load_slots(a.from_slots)
        melody, runs, world = [], [], None
        for row in doc:
            melody.append((row["start"], row["dur"],
                           int(row["midi"]),
                           realize.accent_velocity(dict(start_cell=row["start_cell"]), style)))
        path, ev = None, None
        world = joint.build_world(params)
        # chords: use the labels written by --dump-slots if present
        prev = None
        for row in doc:
            label = row.get("chord")
            if label and label != prev:
                runs.append([label, row["start"]])
                prev = label
        chord_notes = []
        for idx, (label, start) in enumerate(runs):
            end = runs[idx + 1][1] if idx + 1 < len(runs) else melody[-1][0] + melody[-1][1]
            ci = [j for j, v in enumerate(world["vocab"]) if v[0] == label]
            if not ci:
                continue
            pcs = {(params["tonic"] + o) % 12 for o in world["vocab"][ci[0]][1]}
            for q in [q for q in range(52, 68) if q % 12 in pcs][:3]:
                chord_notes.append((start, end - start, q))
        lines = ["# rendered from %s (%d notes)" % (a.from_slots, len(melody))]
        prog = [r[0] for r in runs]
    else:
        path, ev, world = joint.solve_joint(p2, W0, style.get("chord_every", 2))
        melody = [(s["start"], s["dur"] * 0.95, world["P"][p],
                   realize.accent_velocity(s, style))
                  for s, (i, c, p) in zip(slots, path)]
        runs = chord_runs(path, world)
        chord_notes = chords_from_runs(runs, slots, params, world)
        prog = [world["vocab"][c][0] for (_, _, c) in runs]

    _, ppath, _ = None, None, None
    plain_path, pev, _ = joint.solve_joint(params, W0, style.get("chord_every", 2))

    L = []
    L.append("=" * 88)
    L.append("A. 逐音节转音决策（音节内声调形状 → 音符数）")
    L.append("=" * 88)
    L.append(realize.describe(params, slots, info))
    L.append("")
    if rstats["top"]:
        L.append("=" * 88)
        L.append("A2. 节奏型（%s）：复用率 %.2f，最高频型出现 %d 次，变化 %d 处"
                 % (a.cell_theme, rstats["reuse"], rstats["top"], rstats["varied"]))
        L.append("=" * 88)
        L.append("型序列 : %s" % rstats["pattern"])
        L.append(rhythm.describe(rp, params.get("chars")))
        L.append("")
    L.append("=" * 88)
    L.append("B. 展开后的旋律（16 分格）")
    L.append("=" * 88)
    L.append(" start  字  起 音高  和弦   音节.音  时值  力度")
    for j, s in enumerate(slots):
        sy = s["syl"]
        ch = params["chars"][sy] if sy < len(params.get("chars", [])) else "?"
        if path is not None:
            _, c, p = path[j]
            nm, cl, v = theory.note_name(world["P"][p]), world["vocab"][c][0], melody[j][3]
        else:
            nm = theory.note_name(int(s.get("midi", 60)))
            cl, v = (s.get("chord") or "-"), melody[j][3]
        L.append("%5.2f  %-2s %-2s %-4s %-4s  %d.%d   %.2f  %3d"
                 % (s["start"], ch, ">" if s["first"] else "",
                    nm, cl, sy + 1, s["k"] + 1, s["dur"], v))
    L.append("")
    L.append("和弦进行 : %s   (每 %s 个音节换一次)"
             % ("-".join(prog), style.get("chord_every", 2)))
    L.append("")
    L.append("=" * 88)
    L.append("C. 单音版 vs 转音版")
    L.append("=" * 88)
    L.append("%-10s %6s %8s %10s %8s %9s" %
             ("", "音符数", "每音节", "轮廓RMS", "最大音程", "级进比"))
    L.append("%-10s %6d %8.2f %10.2f %8d %9.2f" %
             ("单音版", len(plain_path), 1.0, pev["contour_rms"],
              pev["max_leap"], pev["stepwise_ratio"]))
    if ev is not None:
        L.append("%-10s %6d %8.2f %10.2f %8d %9.2f" %
                 ("转音版", len(path), len(path) / max(1, len(plain_path)),
                  ev["contour_rms"], ev["max_leap"], ev["stepwise_ratio"]))
    L.append("")
    L.append("参数：melisma=%s pattern=%s cell-theme=%s swing=%s push=%s grace=%s override=%s"
             % (style.get("melisma"), pattern, a.cell_theme,
                style.get("swing"), style.get("push") or "-",
                style["grace"].get("enabled"), a.override or "-"))

    mid = os.path.join(a.out, "groove.mid")
    midi_io.write_midi(mid, a.tempo, [("melody", 73, melody), ("chords", 0, chord_notes)])

    if a.dump_slots:
        rows = []
        for j, s in enumerate(slots):
            row = dict(syl=s["syl"] + 1, note=s["k"], char=params["chars"][s["syl"]],
                       start=round(s["start"], 4), dur=round(s["dur"], 4),
                       start_cell=s["start_cell"], cells=s["cells"],
                       target=round(s["target"], 4), grace=bool(s.get("grace")),
                       midi=int(melody[j][2]))
            if path is not None:
                row["chord"] = world["vocab"][path[j][1]][0]
            rows.append(row)
        with open(a.dump_slots, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print("[ok]", a.dump_slots)

    with open(os.path.join(a.out, "report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    with open(os.path.join(a.out, "params_groove.json"), "w", encoding="utf-8") as f:
        json.dump(dict(style=style, per_syllable=info), f, ensure_ascii=False, indent=2)

    print("[ok]", mid)
    print("[ok]", os.path.join(a.out, "report.txt"))
    print("notes: %d (single-note version: %d)" % (len(slots), len(plain_path)))
    print("melody:", [theory.note_name(int(m[2])) for m in melody])
    print("chords:", "-".join(prog))


if __name__ == "__main__":
    main()
