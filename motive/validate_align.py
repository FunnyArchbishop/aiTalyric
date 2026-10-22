"""Two automatic checks for the lightweight aligner (no human labels needed).

A. controlled test
   Synthesise an utterance with *known* boundaries - harmonic source with tone
   contours for vowels/sonorants, high-passed noise for fricatives, closure +
   burst for stops - align it, and report boundary error in ms.  This tests the
   machinery (state model, durations, DP), not natural-speech performance.

B. self-supervised test on real speech
   A correct alignment makes each syllable's internal F0 slope agree with its
   tone (2nd rises, 4th falls, 1st/3rd stay level).  A wrong alignment mixes
   slopes across syllables and agreement drops.  So tone-slope agreement is a
   usable proxy for alignment quality, and it is exactly the property the
   melody stage depends on.  Compared against the energy-dip baseline.

    python validate_align.py
"""

import math
import os
import wave

import numpy as np

import align
import f0_from_wav
import theory


# ------------------------------------------------------- synthetic audio test

def _env(n, fs, rise_ms=12.0, fall_ms=12.0):
    r = max(1, int(fs * rise_ms / 1000))
    f = max(1, int(fs * fall_ms / 1000))
    e = np.ones(n)
    e[:r] = np.linspace(0, 1, r) ** 0.5
    e[-f:] = np.linspace(1, 0, f) ** 0.5
    return e


def _harmonic(n, fs, f0_hz, nh=14, tilt=1.6, amp=0.30, rng=None):
    t = np.arange(n) / fs
    # instantaneous frequency may vary over the segment
    if np.ndim(f0_hz) == 0:
        f0 = np.full(n, float(f0_hz))
    else:
        f0 = np.asarray(f0_hz, dtype=float)
    phase = 2 * np.pi * np.cumsum(f0) / fs
    x = np.zeros(n)
    for k in range(1, nh + 1):
        if k * float(np.max(f0)) > fs / 2 - 200:
            break
        x += np.sin(k * phase) / (k ** tilt)
    x *= amp / max(1e-9, np.max(np.abs(x)))
    x *= _env(n, fs)
    if rng is not None:
        x = x + rng.normal(0, 0.004, n) * _env(n, fs)
    return x


def _noise(n, fs, amp=0.12, hp=True, rng=None):
    rng = rng or np.random.default_rng(0)
    x = rng.normal(0, 1.0, n)
    if hp:
        x = np.diff(np.concatenate([[0.0], x]))
    x *= amp / max(1e-9, np.max(np.abs(x)))
    return x * _env(n, fs)


def _tone_f0(n, fs, base_hz, tone, decl_st=0.0):
    pts = theory.TONE_CONTOUR.get(tone, theory.TONE_CONTOUR[1])
    xs = np.linspace(0, 1, n)
    off = np.zeros(n)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        m = (xs >= x0) & (xs <= x1)
        if x1 > x0:
            off[m] = y0 + (xs[m] - x0) / (x1 - x0) * (y1 - y0)
    return base_hz * (2.0 ** ((off + decl_st) / 12.0))


def synth_utterance(text, pinyin, tones, fs=22050, base_hz=210.0, seed=3,
                    dur_scale=1.0):
    """Return (audio, truth_bounds_ms, fs); bounds are the real syllable ends."""
    rng = np.random.default_rng(seed)
    syls = align.parse_syllables(text, pinyin)
    parts = []
    t = 0.0
    truth = []

    def add(x):
        nonlocal t
        parts.append(x)
        t += len(x) / fs

    add(_noise(int(0.15 * fs), fs, amp=0.002, rng=rng))          # leading silence
    decl_total = -1.2
    for i, s in enumerate(syls):
        decl = decl_total * (i / max(1, len(syls) - 1))

        def ms(d):
            return int(fs * d / 1000.0 * dur_scale)

        if s["initial"]:
            cls = align.INIT_CLASS.get(s["initial"], "fric")
            if cls == "stop":
                add(_noise(ms(25), fs, amp=0.01, rng=rng))        # closure
                add(_noise(ms(20), fs, amp=0.18, rng=rng))        # burst
            elif cls == "affr":
                add(_noise(ms(55), fs, amp=0.16, rng=rng))
                add(_noise(ms(30), fs, amp=0.10, rng=rng))
            elif cls == "fric":
                add(_noise(ms(90), fs, amp=0.13, rng=rng))
            else:                                                 # sonorant m n l r
                n = ms(75)
                add(_harmonic(n, fs, _tone_f0(n, fs, base_hz, tones[i], decl - 2),
                              nh=6, tilt=2.4, amp=0.18, rng=rng))
        n = ms(215 * (1.15 if tones[i] == 3 else 1.0))
        add(_harmonic(n, fs, _tone_f0(n, fs, base_hz, tones[i], decl), rng=rng))
        truth.append(t * 1000.0)
    add(_noise(int(0.35 * fs), fs, amp=0.002, rng=rng))           # trailing silence

    return np.concatenate(parts), truth, fs


def test_synthetic(repeats=6):
    """Syllable-boundary error against known ground truth."""
    text = "我想和你一起看海"
    pinyin = "wo,xiang,he,ni,yi,qi,kan,hai"
    tones = [3, 3, 2, 3, 1, 3, 4, 3]
    errs = []
    for seed in range(repeats):
        x, truth, fs = synth_utterance(text, pinyin, tones, seed=seed,
                                       dur_scale=0.9 + 0.1 * seed)
        bounds, info = align.align(x, fs, text, tones, pinyin=pinyin)
        got = [e for _, e in bounds]
        # the final syllable's end is close to the trailing silence, skip it
        for g, tt in zip(got[:-1], truth[:-1]):
            errs.append(abs(g - tt))
    errs = np.array(errs)
    return dict(n=len(errs), mean=float(errs.mean()), median=float(np.median(errs)),
                p90=float(np.percentile(errs, 90)),
                within30=float(np.mean(errs <= 30) * 100),
                within60=float(np.mean(errs <= 60) * 100))


# --------------------------------------------------- real speech: tone shapes

def _archetype(tone, n=16):
    pts = theory.TONE_CONTOUR.get(tone, theory.TONE_CONTOUR[1])
    xs = np.linspace(0, 1, n)
    ys = np.zeros(n)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        m = (xs >= x0) & (xs <= x1)
        if x1 > x0:
            ys[m] = y0 + (xs[m] - x0) / (x1 - x0) * (y1 - y0)
    ys = ys - ys.mean()
    return ys / (np.linalg.norm(ys) + 1e-9)


def tone_shape_score(wav, text, tones, bounds, npts=16):
    """Correlate each syllable's F0 shape with its tone archetype.

    A single linear slope cannot describe 3rd tone (the 214 dip), so shape
    correlation is used instead.  If a boundary is misplaced, a syllable
    contains parts of two tones and its correlation drops.
    """
    x, fs = f0_from_wav.read_wav(wav)
    times, f0, _, _ = f0_from_wav.f0_track(x, fs)
    f0 = f0_from_wav.repair_octaves(times, f0_from_wav.median_filter(f0, 5))

    corrs, flat_err, jumps = [], [], []
    prev_med = None
    for i, (s, e) in enumerate(bounds):
        d = e - s
        sel = (times >= s + 0.15 * d) & (times <= e - 0.15 * d) & (f0 > 0)
        if sel.sum() < 4:
            continue
        seg = 12.0 * np.log2(f0[sel] / 220.0)
        xs = np.linspace(0, 1, len(seg))
        grid = np.linspace(0, 1, npts)
        prof = np.interp(grid, xs, seg - seg.mean())
        med = float(np.median(seg))
        if prev_med is not None:
            jumps.append(abs(med - prev_med))
        prev_med = med
        arch = _archetype(tones[i], npts)
        if np.linalg.norm(arch) < 1e-6:          # flat tone: measure flatness
            flat_err.append(float(np.std(prof)))
        else:
            prof = prof - prof.mean()
            corrs.append(float(np.dot(prof, arch) /
                               (np.linalg.norm(prof) + 1e-9) / np.linalg.norm(arch)))
    return dict(shape_mean=float(np.mean(corrs)) if corrs else float("nan"),
                shape_hits=sum(1 for c in corrs if c > 0.5), shape_n=len(corrs),
                flat_err=float(np.mean(flat_err)) if flat_err else float("nan"),
                jump=float(np.mean(jumps)) if jumps else float("nan"))


def voiced_cut_rate(wav, bounds, half=2):
    """Fraction of boundaries that cut through ongoing voicing.

    A boundary with high periodicity and continuous F0 on both sides is very
    likely *inside* a vowel - the failure mode an energy-dip detector has and a
    nucleus-constrained decode is supposed not to have.
    """
    x, fs = f0_from_wav.read_wav(wav)
    times, F = align.features(x, fs)
    per = F[:, 2]
    times, f0, _, _ = f0_from_wav.f0_track(x, fs)
    f0 = f0_from_wav.repair_octaves(times, f0_from_wav.median_filter(f0, 5))
    bad = 0
    for s, _ in bounds[1:]:
        k = int(np.argmin(np.abs(times - s)))
        lo = slice(max(0, k - half), max(1, k))
        hi = slice(k, min(len(per), k + half))
        p_lo, p_hi = float(np.mean(per[lo])), float(np.mean(per[hi]))
        f_lo = f0[lo][f0[lo] > 0]
        f_hi = f0[hi][f0[hi] > 0]
        cont = (f_lo.size and f_hi.size
                and abs(12 * math.log2(np.median(f_hi) / np.median(f_lo))) < 0.8)
        if p_lo > 0.85 and p_hi > 0.85 and cont:
            bad += 1
    return bad, len(bounds) - 1


def test_real():
    cases = [
        ("testdata/tts.wav", "我想和你一起看海", [3, 3, 2, 3, 1, 3, 4, 3],
         "wo,xiang,he,ni,yi,qi,kan,hai"),
        ("testdata/tts2.wav", "春天来了花开了", [1, 1, 2, 0, 1, 1, 0],
         "chun,tian,lai,le,hua,kai,le"),
    ]
    rows = []
    for wav, text, tones, py in cases:
        if not os.path.exists(wav):
            continue
        x, fs = f0_from_wav.read_wav(wav)
        b_forced, _ = align.align(x, fs, text, tones, pinyin=py)
        times, f0, rms, clar = f0_from_wav.f0_track(x, fs)
        f0s = f0_from_wav.repair_octaves(times, f0_from_wav.median_filter(f0, 5))
        b_energy = f0_from_wav.segment_dp(times, rms, f0s, len(text))
        if b_energy is None:
            b_energy = f0_from_wav.segment(times, rms, f0s, len(text))
        s_forced = tone_shape_score(wav, text, tones, b_forced)
        s_energy = tone_shape_score(wav, text, tones, b_energy)
        vc_f, n_f = voiced_cut_rate(wav, b_forced)
        vc_e, n_e = voiced_cut_rate(wav, b_energy)
        drift = float(np.mean([abs(a[0] - b[0]) for a, b in zip(b_forced, b_energy)]))
        rows.append(dict(text=text, drift=drift,
                         forced=s_forced, energy=s_energy,
                         vcut_forced=(vc_f, n_f), vcut_energy=(vc_e, n_e),
                         forced_bounds=[(round(s), round(e)) for s, e in b_forced],
                         energy_bounds=[(round(s), round(e)) for s, e in b_energy]))
    return rows


if __name__ == "__main__":
    print("=" * 78)
    print("A. controlled test (synthetic audio, known boundaries)")
    print("=" * 78)
    r = test_synthetic()
    print("  boundaries=%d  mean |err|=%.1f ms  median=%.1f  p90=%.1f"
          % (r["n"], r["mean"], r["median"], r["p90"]))
    print("  within 30 ms: %.1f%%    within 60 ms: %.1f%%"
          % (r["within30"], r["within60"]))

    print()
    print("=" * 78)
    print("B. real speech: tone-shape correlation (higher = boundaries respect tones)")
    print("=" * 78)
    for row in test_real():
        f, e = row["forced"], row["energy"]
        print("  %s   (aligners differ by %.0f ms on average)" % (row["text"], row["drift"]))
        print("    forced : shape r=%+.2f (%d/%d > 0.5)  flat-err=%.2f  boundary jump=%.2f st"
              % (f["shape_mean"], f["shape_hits"], f["shape_n"], f["flat_err"], f["jump"]))
        print("    energy : shape r=%+.2f (%d/%d > 0.5)  flat-err=%.2f  boundary jump=%.2f st"
              % (e["shape_mean"], e["shape_hits"], e["shape_n"], e["flat_err"], e["jump"]))
        print("    forced bounds %s" % row["forced_bounds"])
        print("    energy bounds %s" % row["energy_bounds"])
        print("    boundaries cutting through voicing: forced %d/%d, energy %d/%d"
              % (row["vcut_forced"][0], row["vcut_forced"][1],
                 row["vcut_energy"][0], row["vcut_energy"][1]))
