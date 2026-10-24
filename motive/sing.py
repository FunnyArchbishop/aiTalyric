"""sing.py - turn a .vsqx (or a slots json) into an audible WAV, no editor needed.

VOCALOID / OpenUtau are the real thing, but if neither is installed you still
want to hear the tune.  This is a formant synthesiser: a glottal pulse train at
the note's pitch (plus the PIT curve from the vsqx), shaped by the formants of
that syllable's vowel, with vibrato and an ADSR envelope.

It will not sound like 洛天依.  It does let you judge melody, timing, melisma and
whether a syllable is too short - which is what tuning needs.

    python sing.py out_gui/aiTalyric.vsqx              # -> out_gui/aiTalyric.wav
    python sing.py out_gui/aiTalyric.vsqx --tempo 120  # ignore the file tempo
    python sing.py --from-slots out_gui/slots.json -o out_gui/x.wav
"""

import argparse
import math
import os
import wave

import numpy as np

try:
    from scipy.signal import lfilter
except ImportError:                       # fall back to a crude one-pole formant
    lfilter = None

import export as export_mod
import vsqx_pit

SR = 22050

# F1, F2, F3 in Hz and bandwidths, roughly male speech; enough to tell vowels apart
FORMANTS = {
    "a": [(730, 90), (1090, 110), (2440, 160)],
    "e": [(530, 80), (1840, 100), (2480, 150)],
    "i": [(270, 60), (2290, 100), (3010, 150)],
    "o": [(570, 80), (840, 100), (2410, 160)],
    "u": [(300, 60), (870, 90), (2240, 150)],
    "n": [(300, 70), (1200, 120), (2400, 180)],
    "m": [(280, 70), (1100, 120), (2300, 180)],
}


def vowel_of_lyric(lyric):
    """Chinese lyric -> its vowel; a latin vowel stays as it is."""
    if not lyric:
        return "a"
    ch = lyric[0]
    if ch.lower() in FORMANTS:
        return ch.lower()
    try:
        from pypinyin import lazy_pinyin, Style
        finals = lazy_pinyin(ch, style=Style.FINALS, strict=False)
        return export_mod.vowel_of(finals[0]) if finals else "a"
    except Exception:
        return "a"


def _resonator(freq, bw):
    r = math.exp(-math.pi * bw / SR)
    theta = 2 * math.pi * freq / SR
    a1 = 2 * r * math.cos(theta)
    a2 = -r * r
    b0 = 1 - r
    return [b0], [1.0, -a1, -a2]


def _shape(seg, vowel):
    if lfilter is None:
        return seg
    out = seg
    for (f, bw) in FORMANTS.get(vowel, FORMANTS["a"]):
        b, a = _resonator(f, bw)
        out = lfilter(b, a, out)
    return out


def _glottal(n, f0):
    """Band-limited pulse train: sum of harmonics with a 1/k roll-off."""
    phase = np.cumsum(2 * math.pi * f0 / SR)
    src = np.zeros(n)
    k = 1
    while k * float(np.max(f0)) < 5200 and k <= 40:
        src += np.sin(k * phase) / (k ** 1.15)
        k += 1
    return src


def render(notes, out_wav, tempo=120.0, start=0.0, transpose=0, vibrato=0.28):
    """notes: [{start_beats, dur_beats, midi, vowel}] -> WAV path."""
    if not notes:
        raise SystemExit("no notes to sing")
    beat_s = 60.0 / float(tempo)
    end_beats = max(n["start_beats"] + n["dur_beats"] for n in notes)
    n_total = int((end_beats - start) * beat_s * SR) + int(0.6 * SR)
    buf = np.zeros(n_total)

    for n in notes:
        t0 = (n["start_beats"] - start) * beat_s
        dur = max(0.06, n["dur_beats"] * beat_s)
        a = int(t0 * SR)
        b = min(n_total, a + int(dur * SR))
        if b <= a:
            continue
        m = b - a
        tt = np.arange(m) / SR
        base = 440.0 * 2 ** ((n["midi"] + transpose - 69) / 12.0)
        # vibrato that fades in, like a singer's, not a synth's LFO
        depth = vibrato * np.clip((tt - 0.12) / 0.3, 0, 1) * float(n.get("vib", 1.0))
        f0 = base * 2 ** (depth * np.sin(2 * math.pi * 5.2 * tt) / 12.0)
        if "f0_curve" in n and n["f0_curve"] is not None:
            f0 = np.interp(tt, n["f0_curve"][0], n["f0_curve"][1])
        src = _glottal(m, f0 if np.ndim(f0) else np.full(m, f0))
        src = _shape(src, n.get("vowel", "a"))
        env = np.ones(m)
        atk = max(1, int(0.02 * SR))
        rel = max(1, int(0.05 * SR))
        env[:atk] = np.linspace(0, 1, atk) ** 0.7
        env[-rel:] *= np.linspace(1, 0, rel) ** 1.5
        env *= 0.75 + 0.25 * np.exp(-tt * 1.5)
        gain = 0.5 if n.get("chord") else 1.0
        buf[a:b] += src * env * gain * (n.get("vel", 88) / 96.0)

    peak = float(np.max(np.abs(buf))) or 1.0
    pcm = (buf / peak * 0.9 * 32767).astype("<i2").tobytes()
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)
    return out_wav, n_total / SR


def from_vsqx(path, tempo=None, use_pit=True):
    info = vsqx_pit.parse_vsqx(path)
    ms_per_dot = 6000000.0 / info["tempo"] / info["resolution"]
    t = (tempo or info["tempo"] / 100.0)
    beat_dots = info["resolution"]
    notes = []
    for n in info["notes"]:
        lyric = n["lyric"] or "a"
        notes.append(dict(start_beats=n["tick"] / beat_dots,
                          dur_beats=max(1, n["dur"]) / beat_dots,
                          midi=n["height"], vowel=vowel_of_lyric(lyric),
                          lyric=lyric))
    # attach the PIT curve (absolute Hz) to whichever note covers each point
    if use_pit and info["pits"]:
        pbs = info["pbs"]
        pts = []
        for (tick, pit) in sorted(info["pits"]):
            base = 65
            for n in info["notes"]:
                if n["tick"] <= tick < n["tick"] + max(1, n["dur"]):
                    base = n["height"]
                    break
            hz = 440.0 * 2 ** ((base + pit * pbs / 8190.0 - 69.0) / 12.0)
            pts.append((tick / beat_dots, hz))
        for n in notes:
            seg = [(x - n["start_beats"], hz) for (x, hz) in pts
                   if n["start_beats"] <= x < n["start_beats"] + n["dur_beats"]]
            if len(seg) >= 2:
                n["f0_curve"] = ([s[0] for s in seg], [s[1] for s in seg])
    return notes, t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vsqx", nargs="?", default="")
    ap.add_argument("--from-slots", default="", help="slots json from --dump-slots")
    ap.add_argument("-o", "--out", default="")
    ap.add_argument("--tempo", type=float, default=None)
    ap.add_argument("--transpose", type=int, default=0)
    ap.add_argument("--no-pit", action="store_true")
    a = ap.parse_args()

    if a.from_slots:
        import json
        doc = json.load(open(a.from_slots, encoding="utf-8"))
        rows = doc["notes"] if isinstance(doc, dict) else doc
        notes = []
        for r in rows:
            notes.append(dict(start_beats=r["start"], dur_beats=r["dur"],
                              midi=int(r["midi"]), vowel="a"))
        tempo = a.tempo or 120.0
        out = a.out or os.path.splitext(a.from_slots)[0] + ".wav"
    else:
        if not a.vsqx:
            raise SystemExit("give a .vsqx or --from-slots")
        if not os.path.exists(a.vsqx):
            raise SystemExit("no such file: %s" % a.vsqx)
        notes, tempo = from_vsqx(a.vsqx, a.tempo, use_pit=not a.no_pit)
        out = a.out or os.path.splitext(a.vsqx)[0] + ".wav"

    path, secs = render(notes, out, tempo, transpose=a.transpose)
    print("notes %d   tempo %.0f bpm   %.1f s" % (len(notes), tempo, secs))
    print("[ok]", path)


if __name__ == "__main__":
    main()
