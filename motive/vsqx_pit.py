"""VvTalk / VOCALOID4 .vsqx  ->  (t_ms, f0_hz) samples + syllable table.

Verified against vvTalk/reliance/output/vsqxWrite.py and
vvTalk/reliance/tyTalk/talker.py:

  * every note is written at one height: <n>65</n>  (65 = F4)
  * PBS  is written as <cc><t>1</t><v id="S">17</v></cc>
  * PIT  is written as <cc><t>tick</t><v id="P">v</v></cc> with
        v = semitones / pbs * 8190
  * <resolution>480</resolution>, <tempo><t>0</t><v>12000</v></tempo>
    (tempo is beats * 100 per minute, so 12000 -> 120 BPM)
  * ms_per_dot = 6000000 / tempo / resolution  (1.0417 ms at 120 BPM)

So the absolute pitch at a PIT point is

    midi = note_height + PIT * pbs / 8190
    hz   = 440 * 2 ** ((midi - 69) / 12)

Usage:
    python vsqx_pit.py out.vsqx --out out_dir
    python vsqx_pit.py out.vsqx --out out_dir --tones 3,3,2,3,4,3,4,3 --solve
"""

import argparse
import csv
import math
import os
import xml.etree.ElementTree as ET


def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}")[-1]
    return root


def parse_vsqx(path):
    root = _strip_ns(ET.parse(path).getroot())
    res_el = root.find(".//resolution")
    resolution = int(res_el.text) if res_el is not None else 480
    tempo_el = root.find(".//tempo/v")
    tempo = int(tempo_el.text) if tempo_el is not None else 12000

    notes = []
    for n in root.findall(".//note"):
        try:
            t = int(float(n.find("t").text))
            dur = int(float(n.find("dur").text))
            height = int(float(n.find("n").text))
        except (AttributeError, TypeError, ValueError):
            continue
        y = n.find("y")
        lyric = (y.text or "").strip() if y is not None else ""
        notes.append(dict(tick=t, dur=dur, height=height, lyric=lyric))

    pits, pbs = [], None
    for cc in root.findall(".//cc"):
        try:
            tick = int(float(cc.find("t").text))
            v = cc.find("v")
            if v is None:
                continue
            val = int(float(v.text))
            vid = v.get("id")
        except (AttributeError, TypeError, ValueError):
            continue
        if vid == "P":
            pits.append((tick, val))
        elif vid == "S":
            pbs = val
    if pbs is None:
        pbs = 17
    return dict(resolution=resolution, tempo=tempo, notes=notes, pits=pits, pbs=pbs)


def to_samples(info):
    """Absolute (t_ms, f0_hz) for every PIT control point."""
    ms_per_dot = 6000000.0 / info["tempo"] / info["resolution"]
    pbs = info["pbs"]
    notes = sorted(info["notes"], key=lambda n: n["tick"])
    out = []
    for (tick, pit) in sorted(info["pits"]):
        base = 65
        for n in notes:
            if n["tick"] <= tick < n["tick"] + max(1, n["dur"]):
                base = n["height"]
                break
        midi = base + pit * pbs / 8190.0
        out.append((tick * ms_per_dot, 440.0 * 2.0 ** ((midi - 69.0) / 12.0)))
    return out, ms_per_dot


def to_syllables(info):
    ms_per_dot = 6000000.0 / info["tempo"] / info["resolution"]
    rows = []
    for n in sorted(info["notes"], key=lambda x: x["tick"]):
        ch = n["lyric"][:1] if n["lyric"] else "-"
        rows.append((ch, n["tick"] * ms_per_dot, (n["tick"] + max(1, n["dur"])) * ms_per_dot))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vsqx")
    ap.add_argument("--out", default="out_vv")
    ap.add_argument("--tones", default="",
                    help="comma separated per-syllable tones, e.g. 3,3,2,3,4,3,4,3")
    ap.add_argument("--solve", action="store_true", help="run the motive pipeline too")
    ap.add_argument("--stretch", type=float, default=1.0)
    ap.add_argument("--smooth", type=int, default=1)
    ap.add_argument("--tonic", type=int, default=60)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    if not os.path.exists(a.vsqx):
        raise SystemExit(
            "no such file: %s\n"
            "  VvTalk does not ship a .vsqx - it writes one when you run it:\n"
            "    cd vvTalk && python main.py            (needs conda + python 3.8,\n"
            "    the misc/ folder extracted from misc_7z, MFA and PyAudio cp38)\n"
            "  Cheaper alternative that needs no VvTalk at all:\n"
            "    python tts_wav.py \"我想和你一起看海\" --out testdata/tts.wav\n"
            "    python f0_from_wav.py --wav testdata/tts.wav --text 我想和你一起看海 \\\n"
            "        --tones 3,3,2,3,1,3,4,3 --solve\n"
            % a.vsqx)

    info = parse_vsqx(a.vsqx)
    samples, ms_per_dot = to_samples(info)
    syls = to_syllables(info)
    print("resolution=%d tempo=%d(rescaled)  pbs=%d  ms_per_dot=%.4f"
          % (info["resolution"], info["tempo"], info["pbs"], ms_per_dot))
    print("notes=%d  pit points=%d  duration=%.0f ms"
          % (len(info["notes"]), len(samples), samples[-1][0] if samples else 0))
    if not samples:
        raise SystemExit("no PIT data (was this written by VvTalk?)")

    f0_path = os.path.join(a.out, "f0.csv")
    with open(f0_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_ms", "f0_hz"])
        for t, hz in samples:
            w.writerow([round(t, 2), round(hz, 2)])

    tones = [int(x) for x in a.tones.split(",")] if a.tones.strip() else []
    syl_path = os.path.join(a.out, "syl.csv")
    with open(syl_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["char", "tone", "onset_ms", "end_ms"])
        for i, (ch, s, e) in enumerate(syls):
            tone = tones[i] if i < len(tones) else 0
            w.writerow([ch, tone, round(s, 1), round(e, 1)])

    print("[ok]", f0_path)
    print("[ok]", syl_path)
    if tones and len(tones) != len(syls):
        print("[warn] --tones has %d values but there are %d syllables"
              % (len(tones), len(syls)))

    if a.solve:
        import f0_from_csv  # noqa: F401  (kept importable for library use)
        os.system('python f0_from_csv.py --syl "%s" --f0 "%s" --tonic %d '
                  '--stretch %s --smooth %d --out "%s"'
                  % (syl_path, f0_path, a.tonic, a.stretch, a.smooth,
                     os.path.join(a.out, "motive")))


if __name__ == "__main__":
    main()
