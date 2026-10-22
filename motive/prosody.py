"""F0 contour  ->  motivic parameters.

Two entry points:

  synth_prosody(chars, tones, durs_ms)   fake but faithful F0 for testing
  extract_params(...)                    the abstraction layer (the point)

The abstraction is deliberately *dimensionless* where it can be:

  contour[i]  in [-1, +1]   shape, no key, no absolute register
  beats[i]    in quarters    rhythm ratios, no tempo
  gesture[i]  {dir, tone, low, mag}

Only later do the musical parameters (key, span, stretch k) turn shape into
actual semitones.  That separation is what lets one intonation motive be
re-instantiated in any key / register / tempo.
"""

import random

from theory import TONE_CONTOUR, TONE_DIR, TONE_LOW, apply_sandhi


# --- 1. synthesis (stand-in for a TTS / VvTalk front end) --------------------

def _lerp(points, x):
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            f = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return y0 + f * (y1 - y0)
    return points[-1][1]


def synth_prosody(chars, tones, durs_ms, step_ms=10, declination=-1.8,
                  final_drop=-1.3, stress_idx=(1,), jitter=0.12, seed=7):
    """Return (samples, bounds) where samples are (t_ms, semitones rel. base)."""
    rng = random.Random(seed)
    tones = apply_sandhi(chars, list(tones))
    n = len(chars)
    total = sum(durs_ms)

    # sentence-level declination + final drop + a little stress lift
    def sentence_component(t_ms, i):
        x = t_ms / total
        v = declination * x
        if i == n - 1:
            v += final_drop
        if i in stress_idx:
            v += 0.9
        return v

    samples, bounds = [], []
    t = 0.0
    # pre-silence so onsets are not glued to 0
    for _ in range(int(60 / step_ms)):
        samples.append((t, -2.0 + rng.gauss(0, jitter * 0.4)))
        t += step_ms
    for i, (ch, dur) in enumerate(zip(chars, durs_ms)):
        tones_here = tones[i]
        pts = TONE_CONTOUR.get(tones_here, TONE_CONTOUR[0])
        start = t
        # attack/release ramps inside the syllable, as real speech has
        while t < start + dur - 1e-9:
            x = (t - start) / dur
            # slight S-curve so medians are stable but edges glide
            sx = min(1.0, max(0.0, x))
            v = _lerp(pts, sx) + sentence_component(t, i)
            v += rng.gauss(0.0, jitter)
            samples.append((t, v))
            t += step_ms
        end = t
        bounds.append((start, end))
        # short inter-syllable transition (no hard jump)
        if i != n - 1:
            gap = 45.0
            v0 = samples[-1][1]
            v1 = _lerp(TONE_CONTOUR.get(tones[i + 1], TONE_CONTOUR[0]), 0.0) \
                + sentence_component(t + gap, i + 1)
            gsteps = max(1, int(gap / step_ms))
            for k in range(1, gsteps + 1):
                samples.append((t, v0 + (v1 - v0) * k / gsteps))
                t += step_ms
    # tail
    for _ in range(int(120 / step_ms)):
        samples.append((t, -2.0 + rng.gauss(0, jitter * 0.4)))
        t += step_ms
    return samples, bounds, tones


# --- 2. the abstraction layer -----------------------------------------------

def _band_mean(vals, lo, hi):
    sel = [v for x, v in vals if lo <= x <= hi]
    return sum(sel) / len(sel) if sel else 0.0


def extract_params(chars, tones_after_sandhi, durs_ms, samples, bounds,
                   tempo=120.0, span_semitones=12.0, stretch=1.0, smooth=1,
                   sub_points=5):
    """Measure the contour per syllable and return a dimension-free motive."""
    n = len(chars)
    med, start_v, end_v = [], [], []
    for (s, e) in bounds:
        vals = [(t, v) for t, v in samples if s <= t < e]
        if not vals:
            vals = [(s, 0.0)]
        ys = sorted(v for _, v in vals)
        med.append(ys[len(ys) // 2])
        w = max(1, int(len(vals) * 0.25))
        start_v.append(sum(v for _, v in vals[:w]) / w)
        end_v.append(sum(v for _, v in vals[-w:]) / w)

    mean = sum(med) / n
    hi, lo = max(med), min(med)
    half = max(0.35, (hi - lo) / 2.0)
    contour_raw = [max(-1.0, min(1.0, (m - mean) / half)) for m in med]

    # The within-syllable shape, in three time-thirds.  This is what makes a
    # syllable splittable into several notes: a 3rd tone shows high-low-higher,
    # a 4th tone shows a big drop, a level tone stays put.
    # The within-syllable shape, sampled at `sub_points` time quantiles.  This is
    # what makes a syllable splittable into several notes, and how finely it can
    # be split: a 3rd tone shows high-low-higher, a 4th tone a big drop.
    npts = max(3, int(sub_points))
    sub_contour = []
    for (s0, e0) in bounds:
        step = max(1e-6, (e0 - s0) / float(npts))
        row = []
        for k in range(npts):
            lo_t, hi_t = s0 + k * step, s0 + (k + 1) * step
            seg = sorted(v for t, v in samples if lo_t <= t < hi_t)
            v = seg[len(seg) // 2] if seg else mean
            row.append(max(-1.0, min(1.0, (v - mean) / half)))
        sub_contour.append(row)

    # Smooth across syllables too, not just within: speech alternates high and
    # low syllables, and if every syllable is expanded from its own unsmoothed
    # shape the melisma zig-zags.  This keeps each syllable's internal turn
    # while removing the inter-syllable jump.
    for _ in range(max(0, int(smooth))):
        cols = []
        for k in range(npts):
            prev = [row[k] for row in sub_contour]
            cols.append([max(-1.0, min(1.0,
                                      (prev[max(0, i - 1)] + 2 * prev[i]
                                       + prev[min(n - 1, i + 1)]) / 4.0))
                         for i in range(n)])
        sub_contour = [[cols[k][i] for k in range(npts)] for i in range(n)]

    # The per-syllable contour jitters at speech rate; a melody should keep the
    # 2-3 syllable trend, not every wobble.  One or two box-filter passes do it,
    # and the smoothing width also decides how many notes the motive can hold.
    contour = list(contour_raw)
    for _ in range(max(0, int(smooth))):
        prev_c = list(contour)
        contour = [max(-1.0, min(1.0,
                                 (prev_c[max(0, i - 1)] + 2 * prev_c[i]
                                  + prev_c[min(n - 1, i + 1)]) / 4.0))
                   for i in range(n)]

    quarter_ms = 60000.0 / tempo
    beats = [max(0.25, round(d / quarter_ms * 4) / 4) for d in durs_ms]

    gestures = []
    for i in range(n):
        measured_slope = end_v[i] - start_v[i]
        arche = TONE_DIR.get(tones_after_sandhi[i], 0)
        gestures.append({
            "tone": tones_after_sandhi[i],
            "dir": arche,                      # what the tone asks for
            "measured_slope": round(measured_slope, 2),
            "low": TONE_LOW.get(tones_after_sandhi[i], False),
            "mag": round(abs(measured_slope), 2),
            "conflict": (arche != 0 and measured_slope * arche < -0.4),
        })

    return {
        "chars": list(chars),
        "tones": list(tones_after_sandhi),
        "contour": contour,                  # what the melody is driven by
        "contour_raw": contour_raw,          # what the voice actually did
        "sub_contour": sub_contour,          # within-syllable shape (3 per syl)
        "smooth": smooth,
        "beats": beats,               # rhythm ratios
        "gestures": gestures,
        "tempo": tempo,
        "span_semitones": span_semitones,
        "stretch": stretch,           # k: 1.0 = faithful, 1.6 = "sung"
        "measured_span": round(hi - lo, 2),
        "measured_mean": round(mean, 2),
    }
