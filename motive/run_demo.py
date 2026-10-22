"""End-to-end demo: intonation -> motivic parameters -> joint melody+chord decode.

    python run_demo.py                    # phrase A, write midi + report
    python run_demo.py --phrase B
    python run_demo.py --stretch 1.6      # "sung" rather than "spoken"
    python run_demo.py --tone-strict      # never allow 倒字, whatever it costs
    python run_demo.py --sweep            # contour / harmony trade-off curve

Stdlib + numpy only. No pip installs required.
"""

import argparse
import json
import os

import numpy as np

import joint
import midi_io
import prosody
import theory

PHRASES = {
    "A": ("我想和你一起看海",
          [("我", 3), ("想", 3), ("和", 2), ("你", 3), ("一", 1), ("起", 3), ("看", 4), ("海", 3)],
          [200, 240, 210, 230, 180, 200, 250, 330]),
    "B": ("你有没有想过为什么",
          [("你", 3), ("有", 3), ("没", 2), ("想", 3), ("过", 4), ("为", 4), ("什", 2), ("么", 0)],
          [190, 210, 180, 200, 230, 240, 200, 180]),
    "C": ("春天来了花开了",
          [("春", 1), ("天", 1), ("来", 2), ("了", 0), ("花", 1), ("开", 1), ("了", 0)],
          [260, 240, 280, 200, 250, 250, 320]),
}

W0 = dict(w_contour=1.0, sigma=2.0, w_tone=1.2, w_harmony=1.0, w_motion=0.8)


def build(a, smooth=None, w_tone=None):
    _, syll, durs = PHRASES[a.phrase]
    chars = [c for c, _ in syll]
    tones = [t for _, t in syll]
    samples, bounds, tones2 = prosody.synth_prosody(chars, tones, durs)
    params = prosody.extract_params(
        chars, tones2, durs, samples, bounds, tempo=a.tempo,
        span_semitones=a.span, stretch=a.stretch,
        smooth=a.smooth if smooth is None else smooth)
    params["tonic"] = a.tonic
    params["mode"] = a.mode
    W = dict(W0)
    if w_tone is not None:
        W["w_tone"] = w_tone
    return params, W


def fmt_table(params, path, world):
    P = world["P"]
    rows, prev = [], None
    for (i, c, p) in path:
        g = params["gestures"][i]
        leap = "" if prev is None else f"{P[p]-prev:+d}"
        rows.append(
            f"{i+1:>2}  {params['chars'][i]}  {theory.TONE_ZH[g['tone']]:<4}"
            f"{theory.TONE_LABEL[g['tone']]:<9}"
            f"{g['dir']:+d}      {g['measured_slope']:+5.2f}   "
            f"{params['contour'][i]:+6.2f}  {theory.note_name(P[p]):<5}"
            f"{world['vocab'][c][0]:<5}{leap:<5}{params['beats'][i]:>4.2f}")
        prev = P[p]
    head = "序号 字 声调 类型      需求向 实测斜率  归一化 选中音 和弦 音程  拍长"
    return "\n".join([head, "-" * 92] + rows)


def summary(tag, ev):
    return (f"{tag:<16} 轮廓RMS={ev['contour_rms']:.2f}  倒字={ev['tone_violations']}"
            f"  非和弦音={ev['harmony_violations']}  最大音程={ev['max_leap']}"
            f"  级进比={ev['stepwise_ratio']:.2f}  总能量={ev['total']:.2f}")


def progression(path, world, chord_rate):
    return "-".join(world["vocab"][c][0] for (i, c, _) in path if i % chord_rate == 0)


def chord_tracks(path, params, world, chord_rate):
    P, beats = world["P"], params["beats"]
    start, melody = 0.0, []
    for (i, c, p) in path:
        melody.append((start, beats[i] * 0.95, P[p]))
        start += beats[i]
    chords, acc = [], 0.0
    for i, (_, c, _) in enumerate(path):
        if i % chord_rate == 0:
            dur = sum(beats[i:i + chord_rate])
            pcs = {(params["tonic"] + o) % 12 for o in world["vocab"][c][1]}
            for q in [q for q in range(52, 68) if q % 12 in pcs][:3]:
                chords.append((acc, dur * 0.92, q))
        acc += beats[i]
    return melody, chords


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phrase", default="A", choices=list(PHRASES))
    ap.add_argument("--tempo", type=float, default=120.0)
    ap.add_argument("--tonic", type=int, default=60)
    ap.add_argument("--mode", default="major", choices=list(theory.SCALES))
    ap.add_argument("--span", type=float, default=12.0)
    ap.add_argument("--stretch", type=float, default=1.0)
    ap.add_argument("--smooth", type=int, default=1)
    ap.add_argument("--tone-strict", action="store_true")
    ap.add_argument("--chord-rate", type=int, default=2)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.sweep:
        return do_sweep(a)

    params, W = build(a, w_tone=3.0 if a.tone_strict else None)
    jpath, jev, world = joint.solve_joint(params, W, a.chord_rate)
    tpath, tev, _ = joint.solve_two_step(params, W, a.chord_rate)

    L = []
    L.append("=" * 92)
    L.append("A. 动机参数对象 —— 调性无关的那一层（形状 / 节奏比例 / 手势）")
    L.append("=" * 92)
    L.append(f"字串             : {''.join(params['chars'])}")
    L.append(f"声调(变调后)      : {params['tones']}")
    L.append(f"实测轮廓 c_raw    : {[round(x, 2) for x in params['contour_raw']]}")
    L.append(f"驱动旋律的 c      : {[round(x, 2) for x in params['contour']]}"
             f"   (smooth={params['smooth']})")
    L.append(f"节奏比例(拍)      : {params['beats']}   合计 {sum(params['beats'])} 拍")
    L.append(f"实测语调跨度      : {params['measured_span']} 半音"
             f" -> 音乐跨度 {params['span_semitones']} 半音, stretch k={params['stretch']}")
    cf = [i + 1 for i, g in enumerate(params["gestures"]) if g["conflict"]]
    L.append(f"声调与测量冲突    : {cf if cf else '无'}")
    L.append("")
    L.append("=" * 92)
    L.append("B. 联合解码（旋律与和弦同时决定）")
    L.append("=" * 92)
    L.append(fmt_table(params, jpath, world))
    L.append("")
    L.append(f"和弦进行 : {progression(jpath, world, a.chord_rate)}"
             f"   ({theory.note_name(a.tonic)} {a.mode}, 每 {a.chord_rate} 音节换一次)")
    L.append("")
    L.append("=" * 92)
    L.append("C. 联合优化 vs 两步法（先量化轮廓，再给固定旋律配和弦）")
    L.append("=" * 92)
    L.append(summary("联合解码", jev))
    L.append(summary("两步基线", tev))
    L.append(f"{'-> 总能量':<14} 联合 {jev['total']:.2f} vs 两步 {tev['total']:.2f}"
             f"   降低 {(tev['total'] - jev['total']) / max(1e-9, tev['total']) * 100:.1f}%"
             f"；轮廓RMS {jev['contour_rms']:.2f} vs {tev['contour_rms']:.2f}"
             f"，非和弦音 {jev['harmony_violations']} vs {tev['harmony_violations']}")
    L.append("")
    L.append("D. 能量分解（联合解码）: " + "  ".join(
        f"{k}={jev[k]:.2f}" for k in ("contour", "tone", "harmony", "motion", "function")))
    L.append("")
    L.append("=" * 92)
    L.append("E. 旋钮对照（同一句语调，只改一个参数）")
    L.append("=" * 92)
    configs = [
        ("逐字忠实 smooth0", dict(smooth=0), None, None),
        ("平滑 smooth1", dict(smooth=1), None, None),
        ("平滑 smooth2", dict(smooth=2), None, None),
        ("严格依字 w_tone3", dict(smooth=1), 3.0, None),
        ("夸张 k=1.6", dict(smooth=1), None, 1.6),
        ("夸张 k=2.0", dict(smooth=1), None, 2.0),
    ]
    for tag, kw, wt, st in configs:
        p2, W2 = build(a, w_tone=wt, **kw)
        if st:
            p2["stretch"] = st
        path2, ev2, w2 = joint.solve_joint(p2, W2, a.chord_rate)
        L.append(summary(tag, ev2) + f"  {progression(path2, w2, a.chord_rate)}")

    melody, chords = chord_tracks(jpath, params, world, a.chord_rate)
    mid = os.path.join(a.out, "motive.mid")
    midi_io.write_midi(mid, a.tempo, [("melody", 73, melody), ("chords", 0, chords)])
    with open(os.path.join(a.out, "motive_params.json"), "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    print("[ok] mid    :", mid)
    print("[ok] params :", os.path.join(a.out, "motive_params.json"))
    print("[ok] report :", os.path.join(a.out, "report.txt"))
    print("melody :", [theory.note_name(world["P"][p]) for (_, _, p) in jpath])
    print("chords :", progression(jpath, world, a.chord_rate))
    print("joint  : total=%.2f  contourRMS=%.2f  toneViol=%d  nonChord=%d  stepwise=%.2f"
          % (jev["total"], jev["contour_rms"], jev["tone_violations"],
             jev["harmony_violations"], jev["stepwise_ratio"]))
    print("2step  : total=%.2f  contourRMS=%.2f  toneViol=%d  nonChord=%d  stepwise=%.2f"
          % (tev["total"], tev["contour_rms"], tev["tone_violations"],
             tev["harmony_violations"], tev["stepwise_ratio"]))


def do_sweep(a):
    L = ["stretch  w_harmon  contourRMS  toneViol  nonChord  maxLeap  stepwise  progression",
         "-" * 92]
    for stretch in (1.0, 1.3, 1.6, 2.0):
        for wh in (0.5, 1.0, 2.0, 4.0):
            params, W = build(a)
            params["stretch"] = stretch
            W["w_harmony"] = wh
            path, ev, world = joint.solve_joint(params, W, a.chord_rate)
            L.append(f"{stretch:>5.1f}   {wh:>8.1f}  {ev['contour_rms']:>10.2f}"
                     f"  {ev['tone_violations']:>8d}  {ev['harmony_violations']:>8d}"
                     f"  {ev['max_leap']:>7d}  {ev['stepwise_ratio']:>8.2f}"
                     f"  {progression(path, world, a.chord_rate)}")
    with open(os.path.join(a.out, "sweep.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
