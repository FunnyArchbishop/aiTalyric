"""vsqx_tool.py - inspect and transpose a VSQ4 project without an editor.

    python vsqx_tool.py --info out_gui/test1.vsqx
    python vsqx_tool.py --in out_gui/test1.vsqx --out out_gui/test1_p12.vsqx --transpose 12

Transposing only moves the note heights: PIT is stored relative to each note, so
the intonation curve travels with the melody.
"""

import argparse
import os
import re
import xml.etree.ElementTree as ET

import export
import vsqx_pit


def _tag(e):
    return e.tag.split("}")[-1]


def info(path):
    txt = open(path, encoding="utf-8").read()
    root = ET.parse(path).getroot()
    notes = [e for e in root.iter() if _tag(e) == "note"]

    def field(n, t):
        x = [c for c in n if _tag(c) == t]
        return x[0].text if x else None

    tempo = int(re.search(r"<tempo><t>0</t><v>(\d+)</v>", txt).group(1))
    res = int(re.search(r"<resolution>(\d+)</resolution>", txt).group(1))
    ms = 6000000.0 / tempo / res
    ticks = [int(field(n, "t") or 0) for n in notes]
    durs = [int(field(n, "dur") or 0) for n in notes]
    heights = [int(field(n, "n") or 60) for n in notes]
    lyrics = [(field(n, "y") or "") for n in notes]
    ms_durs = sorted(int(round(d * ms)) for d in durs)
    name = re.search(r"<name><!\[CDATA\[([^\]]*)\]\]></name>", txt)
    vid = re.search(r"<id><!\[CDATA\[([A-Za-z0-9_]+)\]\]></id>", txt)

    print("file      :", path)
    print("notes     :", len(notes))
    print("singer    :", (name.group(1) if name else "?"),
          "|", (vid.group(1) if vid else "?"))
    print("tempo     : %.0f bpm   resolution %d   ms/dot %.4f" % (tempo / 100.0, res, ms))
    print("range     : MIDI %d..%d  (%s .. %s)"
          % (min(heights), max(heights),
             __import__("theory").note_name(min(heights)),
             __import__("theory").note_name(max(heights))))
    print("length    : %.2f s" % ((max(t + d for t, d in zip(ticks, durs)) * ms) / 1000.0))
    print("note len  : shortest %d ms, median %d ms, longest %d ms"
          % (ms_durs[0], ms_durs[len(ms_durs) // 2], ms_durs[-1]))
    dist = {}
    for d in ms_durs:
        dist[d] = dist.get(d, 0) + 1
    print("histogram :", ", ".join("%dms x%d" % (k, v) for k, v in sorted(dist.items())))
    print("lyrics    :", "".join(lyrics))
    print("pit points:", len(re.findall('id="P"', txt)))
    over = [h for h in heights if h < 55]
    if over:
        print("NOTE      : %d notes below MIDI 55 - most Chinese female voicebanks "
              "get muddy down there; consider --transpose 12" % len(over))
    fast = [d for d in ms_durs if d < 200]
    if fast:
        print("NOTE      : %d notes shorter than 200 ms - raise min_note or slow "
              "the tempo" % len(fast))
    return dict(notes=len(notes), heights=heights, ticks=ticks, durs=durs,
                lyrics=lyrics, tempo=tempo / 100.0, ms=ms)


def transpose(src, dst, semis):
    inf = vsqx_pit.parse_vsqx(src)
    txt = open(src, encoding="utf-8").read()

    def bump(m):
        return "%s%d%s" % (m.group(1), int(m.group(2)) + semis, m.group(3))

    # only touch <n> heights, never <v>/<dur>/<t>
    txt = re.sub(r"(<n>)(\d+)(</n>)", bump, txt)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="")
    ap.add_argument("--out", dest="dst", default="")
    ap.add_argument("--transpose", type=int, default=0)
    ap.add_argument("--info", dest="info_path", default="")
    a = ap.parse_args()

    if a.info_path:
        info(a.info_path)
        return
    if not a.src or not os.path.exists(a.src):
        raise SystemExit("give --info PATH, or --in PATH --out PATH [--transpose N]")
    if a.transpose == 0:
        info(a.src)
        return
    dst = a.dst or os.path.splitext(a.src)[0] + ("%+d" % a.transpose) + ".vsqx"
    transpose(a.src, dst, a.transpose)
    print("transposed %+d semitones -> %s" % (a.transpose, dst))
    info(dst)


if __name__ == "__main__":
    main()
