"""One command, all the regressions.

    python selftest.py          # exits non-zero if anything regressed

Checks, in order:

  1 decode      joint decoding beats the two-step baseline
  2 alignment   synthetic-audio boundary error stays under budget
  3 melisma     a syllable can become several notes
  4 rhythm      a cell comes back at least 3 times, and not at all when disabled
  5 development 8 bars, transposition keeps the contour (correlation guard)
  6 export      .vsqx round-trips through our own parser; .ustx is well formed
  7 midi        the written files are valid SMF

No pytest, no network, nothing outside this folder except the optional TTS wav.
"""

import io
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np

import develop
import export
import joint
import midi_io
import realize
import rhythm
import run_demo
import theory

W0 = dict(run_demo.W0)
FAILS = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


def demo_params(phrase="A"):
    a = type("A", (), dict(phrase=phrase, tempo=120.0, tonic=60, mode="major",
                           span=12.0, stretch=1.0, smooth=1))()
    params, _ = run_demo.build(a)
    return params


def t_decode():
    p = demo_params()
    path, ev, _ = joint.solve_joint(p, W0, 2)
    plain_path, plain_ev, _ = joint.solve_two_step(p, W0, 2)
    check("decode: 8 notes", len(plain_path) == 8, "%d" % len(plain_path))
    check("decode: joint <= two-step", ev["total"] <= plain_ev["total"] + 1e-9,
          "%.2f vs %.2f" % (ev["total"], plain_ev["total"]))
    check("decode: contour RMS < 1.2", ev["contour_rms"] < 1.2, "%.2f" % ev["contour_rms"])


def t_align():
    import validate_align
    r = validate_align.test_synthetic(repeats=3)
    check("align: mean error < 40 ms", r["mean"] < 40.0, "%.1f ms" % r["mean"])
    check("align: 70% within 30 ms", r["within30"] >= 70.0, "%.0f%%" % r["within30"])


def t_melisma():
    p = demo_params()
    st = realize.load_style(None)
    slots, ca, info = realize.realize(p, style=st)
    check("melisma: more notes than syllables", len(slots) > len(p["beats"]),
          "%d notes / %d syllables" % (len(slots), len(p["beats"])))
    # every chord change must sit on a syllable's first note
    bad = [j for j in range(len(slots)) if ca[j] and not slots[j]["first"]]
    check("melisma: chords stay on syllable boundaries", not bad, "%d boundaries" % sum(ca))


def t_rhythm():
    p = demo_params()
    st = realize.load_style(None)
    on, _, info_on = realize.realize(p, style=st, rhythm_theme="sync")
    off, _, info_off = realize.realize(p, style=st, rhythm_theme="none")
    spans = [max(1, int(round(b / 0.125))) for b in p["beats"]]
    rp = rhythm.plan(spans, "sync", 4)
    s = rhythm.stats(rp)
    none_stats = rhythm.stats(rhythm.plan(spans, "none", 4))
    check("rhythm: a cell repeats >= 3 times", s["at_least_3"], s["pattern"])
    check("rhythm: disabled means zero reuse", none_stats["reuse"] == 0.0,
          "reuse=%.2f" % none_stats["reuse"])
    check("rhythm: theme still produces notes", len(on) > 0, "%d" % len(on))


def t_develop():
    import argparse
    a = argparse.Namespace(phrase="A", wav="", text="", tones="", pinyin="",
                           tempo=120.0, tonic=60, mode="major", span=12.0,
                           stretch=1.0, smooth=1, ref_hz=220.0, melisma=None,
                           style_file="", cell_theme="sync", variation_every=4)
    params, slots, ca, style = develop.build_source(a)
    src, _, _, _ = develop.render_section(params, slots, style, "orig", 0, 0,
                                          start_role="T")
    src_c = [n["midi"] for n in src]
    tr, _, _, _ = develop.render_section(params, slots, style, "transpose", 2, 2,
                                         start_role="T")
    corr = develop.contour_corr(src_c, [n["midi"] for n in tr])
    inv, _, _, _ = develop.render_section(params, develop.transform(slots, "invert"),
                                          style, "invert", 0, 0, start_role="T")
    corr_inv = develop.contour_corr(src_c, [n["midi"] for n in inv])
    check("develop: transposition keeps contour", corr >= 0.80, "corr=%.3f" % corr)
    check("develop: inversion flips contour", corr_inv < -0.5, "corr=%.3f" % corr_inv)


def t_export():
    notes = [dict(start=0.0, dur=0.5, midi=64, lyric="\u6211"),
             dict(start=0.5, dur=0.25, midi=62, lyric="o"),
             dict(start=0.75, dur=0.75, midi=60, lyric="\u4f60")]
    d = tempfile.mkdtemp()
    v = os.path.join(d, "t.vsqx")
    u = os.path.join(d, "t.ustx")
    export.write_vsqx(v, notes, portamento=1.0)
    export.write_ustx(u, notes)
    chk = export.check_vsqx(v, expect_notes=3)
    check("export: vsqx structure", chk["ok"], str(chk["notes"]) + " notes")
    check("export: vsqx lyrics complete", all(chk["lyrics"]), str(chk["lyrics"]))
    check("export: pit within range", chk["pit_in_range"])
    # round trip through our own reader
    import vsqx_pit
    info = vsqx_pit.parse_vsqx(v)
    samples, _ = vsqx_pit.to_samples(info)
    check("export: vsqx round-trip", len(info["notes"]) == 3 and len(samples) > 0,
          "%d notes, %d pit points" % (len(info["notes"]), len(samples)))
    txt = open(u, encoding="utf-8").read()
    check("export: ustx has notes", txt.count("tone:") == 3 and "ustxVersion" in txt)


def t_midi():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.mid")
    midi_io.write_midi(p, 120.0, [("m", 73, [(0, 1, 60, 90)]), ("c", 0, [(0, 1, 48, 70)])])
    b = open(p, "rb").read()
    check("midi: valid header", b[:4] == b"MThd" and int.from_bytes(b[10:12], "big") == 3,
          "%d bytes" % len(b))


if __name__ == "__main__":
    print("=" * 60)
    print("aiTalyric selftest")
    print("=" * 60)
    for fn in (t_decode, t_align, t_melisma, t_rhythm, t_develop, t_export, t_midi):
        print("[%s]" % fn.__name__[2:])
        fn()
    print("=" * 60)
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("all checks passed")
