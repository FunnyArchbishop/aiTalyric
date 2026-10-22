"""WAV -> (t_ms, f0_hz) + syllable boundaries.  stdlib wave + numpy only.

This replaces the whole "render, then pitch-track with RMVPE/GAME" step for the
front end: it takes any recording or TTS output and produces the same CSV
contract the rest of the pipeline already eats.

    python f0_from_wav.py --wav testdata/tts.wav --text 我想和你一起看海 \
        --tones 3,3,2,3,1,3,4,3 --solve

F0: normalised autocorrelation per 40 ms frame / 10 ms hop, parabolic peak
interpolation, voicing decided by clarity x energy.  Segmentation: energy
valleys, taking the N-1 deepest so that N syllables come out, as Chinese read
speech has a clear amplitude dip at every syllable boundary.
"""

import argparse
import os
import wave

import numpy as np


def read_wav(path):
    with wave.open(path, "rb") as w:
        fs = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(n)
    if sw == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    elif sw == 1:
        x = (np.frombuffer(raw, dtype="<u1").astype(np.float64) - 128.0) / 128.0
    else:
        raise SystemExit("unsupported sample width %d" % sw)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, fs


def f0_track(x, fs, fmin=70.0, fmax=420.0, win_ms=40.0, hop_ms=10.0,
             yin_thresh=0.16, octave_fix=True):
    """YIN (de Cheveigne & Kawahara) F0 track.

    Plain autocorrelation with an argmax peak picker makes octave errors on
    telephone-band TTS voices (83 Hz and 514 Hz in the same 3 s phrase), so the
    cumulative-mean-normalised difference function is used instead: it picks the
    *first* lag that is aperiodic enough, not the deepest correlation peak.
    """
    win = int(fs * win_ms / 1000.0)
    hop = int(fs * hop_ms / 1000.0)
    if len(x) < win:
        raise SystemExit("wav too short")
    nframes = 1 + (len(x) - win) // hop
    w = np.hanning(win)
    lag_min = max(2, int(fs / fmax))
    lag_max = min(win - 2, int(fs / fmin))
    nlag = lag_max + 1

    f0 = np.zeros(nframes)
    rms = np.zeros(nframes)
    clarity = np.zeros(nframes)

    for k in range(nframes):
        seg = (x[k * hop:k * hop + win] - x[k * hop:k * hop + win].mean()) * w
        rms[k] = float(np.sqrt(np.mean(seg ** 2)))
        W = len(seg)
        # fast difference function via FFT autocorrelation + prefix energies
        spec = np.fft.rfft(seg, n=2 * W)
        acf = np.fft.irfft(np.abs(spec) ** 2, n=2 * W)[:nlag]
        sq = np.concatenate(([0.0], np.cumsum(seg ** 2)))
        tot = sq[W]
        taus = np.arange(nlag)
        head = sq[np.minimum(taus, W)]
        tail = sq[W] - sq[np.maximum(W - taus, 0)]
        d = (tot - tail) + (tot - head) - 2.0 * acf
        d[0] = 0.0
        # cumulative mean normalised difference
        cmnd = np.ones(nlag)
        run = 0.0
        for tau in range(1, nlag):
            run += d[tau]
            cmnd[tau] = d[tau] * tau / run if run > 0 else 1.0
        band = cmnd[lag_min:lag_max]
        if band.size == 0:
            continue
        below = np.where(band < yin_thresh)[0]
        if below.size:
            j = int(below[0])
            while j + 1 < band.size and band[j + 1] < band[j]:
                j += 1
        else:
            j = int(np.argmin(band))
        lag = lag_min + j
        clarity[k] = 1.0 - float(band[j])
        if lag > 0 and lag + 1 < nlag:
            a, b, c = cmnd[lag - 1], cmnd[lag], cmnd[lag + 1]
            denom = a - 2 * b + c
            if abs(denom) > 1e-12:
                lag = lag + 0.5 * (a - c) / denom
        if clarity[k] >= 0.55 and lag > 0:
            f0[k] = fs / lag

    if octave_fix:
        for k in range(1, nframes):
            a, b = f0[k - 1], f0[k]
            if a <= 0 or b <= 0:
                continue
            ratio = b / a
            for f in (2.0, 0.5, 3.0, 1.0 / 3.0):
                if abs(ratio / f - 1.0) < 0.06:
                    f0[k] = b / f
                    break
    times = (np.arange(nframes) * hop + win / 2.0) / fs * 1000.0
    return times, f0, rms, clarity


def repair_octaves(times, f0, half_window_ms=150.0, max_resid=0.75):
    """Snap octave errors back to the utterance's median octave.

    A TTS voice with a weak fundamental (/h/, /k/ onsets) produces clean octave
    errors: 395 Hz in a syllable whose neighbours sit at ~195 Hz.  Snapping
    against a *local* median fails when a whole tail of frames is wrong - the
    local median follows the error - so the anchor is the utterance median and
    only the residual is checked against the local context.
    """
    logf = np.where(f0 > 0, np.log2(np.maximum(f0, 1e-9)), np.nan)
    if not np.any(np.isfinite(logf)):
        return np.array(f0, dtype=float)
    g = float(np.median(logf[np.isfinite(logf)]))
    out = np.array(f0, dtype=float)
    for k in range(len(f0)):
        if not np.isfinite(logf[k]):
            continue
        shift = int(round(float(logf[k]) - g))
        val = f0[k] / (2.0 ** shift) if shift else f0[k]
        # keep it only if it now sits a plausible distance from the local median
        lo = int(np.searchsorted(times, times[k] - half_window_ms))
        hi = int(np.searchsorted(times, times[k] + half_window_ms))
        win = logf[lo:hi]
        win = win[np.isfinite(win)]
        c = float(np.median(win)) if win.size >= 3 else g
        c = min(max(c, g - max_resid * 0.5), g + max_resid * 0.5)
        if abs(np.log2(val) - c) > max_resid:
            out[k] = 0.0
        else:
            out[k] = val
    return out


def median_filter(v, k=5):
    if k <= 1:
        return v
    pad = k // 2
    out = np.array(v, dtype=float)
    for i in range(len(v)):
        lo, hi = max(0, i - pad), min(len(v), i + pad + 1)
        sel = v[lo:hi]
        if np.any(sel > 0):
            out[i] = float(np.median(sel[sel > 0]))
    return out


def segment_dp(times, rms, f0, n_syllables, edge_ms=30.0,
               dur_lo=0.55, dur_hi=1.85, w_dur=0.35, w_env=1.0):
    """Place the n-1 syllable boundaries by DP.

    Deepest-dip-first mis-splits connected speech (a vowel can dip between its
    onset and nucleus), so the placement is instead a small constrained
    optimisation: maximise dip depth at boundaries while keeping every syllable
    near the mean duration.  Exactly the same idea as the melody decode, one
    level down.
    """
    voiced = f0 > 0
    if not np.any(voiced):
        raise SystemExit("no voiced frames detected")
    first, last = int(np.argmax(voiced)), len(voiced) - int(np.argmax(voiced[::-1]))
    t0, t1 = times[first], times[min(last, len(times) - 1)]
    if t1 <= t0:
        raise SystemExit("degenerate voiced span")

    idx = [i for i in range(len(times)) if t0 - 1e-9 <= times[i] <= t1 + 1e-9]
    if len(idx) < n_syllables + 2:
        raise SystemExit("stitched span too short for %d syllables" % n_syllables)
    T = np.array([times[i] for i in idx])
    env = np.convolve(rms, np.ones(5) / 5.0, mode="same")[idx]
    emax = float(env.max()) or 1.0
    en = env / emax
    mean_dur = (t1 - t0) / n_syllables
    lo, hi = dur_lo * mean_dur, dur_hi * mean_dur
    INF = 1e18

    # dp[k][i]: best cost for k segments ending at candidate frame i
    F = len(T)
    dp = np.full((n_syllables + 1, F), INF)
    bp = np.zeros((n_syllables + 1, F), dtype=np.int32)
    dp[0, 0] = 0.0
    for k in range(1, n_syllables + 1):
        for i in range(1, F):
            if k == n_syllables and i != F - 1:
                continue
            ti = T[i]
            lo_j = np.searchsorted(T, ti - hi, side="left")
            hi_j = np.searchsorted(T, ti - lo, side="right")
            if hi_j <= lo_j:
                continue
            js = np.arange(lo_j, min(hi_j, i))
            if js.size == 0:
                continue
            durs = ti - T[js]
            costj = dp[k - 1, js]
            total = costj + w_dur * np.abs(durs - mean_dur) / mean_dur
            j = int(js[np.argmin(total)])
            best = float(np.min(total))
            if k < n_syllables:
                best += w_env * en[i]
            dp[k, i] = best
            bp[k, i] = j
    if dp[n_syllables, F - 1] >= INF:
        return None
    cuts, i = [], F - 1
    for k in range(n_syllables, 0, -1):
        i = int(bp[k, i])
        cuts.append(float(T[i]))
    cuts.reverse()
    bounds = [float(T[0])] + cuts[1:] + [float(T[-1])]
    return [(bounds[i], bounds[i + 1]) for i in range(n_syllables)]


def segment(times, rms, f0, n_syllables, min_gap_ms=90.0, edge_ms=30.0):
    """Split at the n-1 deepest energy valleys inside the voiced span."""
    voiced = f0 > 0
    if not np.any(voiced):
        raise SystemExit("no voiced frames detected")
    first, last = int(np.argmax(voiced)), len(voiced) - int(np.argmax(voiced[::-1]))
    t0, t1 = times[first], times[min(last, len(times) - 1)]
    if t1 <= t0:
        raise SystemExit("degenerate voiced span")

    env = np.convolve(rms, np.ones(5) / 5.0, mode="same")
    in_span = (times >= t0 + edge_ms) & (times <= t1 - edge_ms)
    region = env[in_span]
    if region.size == 0:
        raise SystemExit("empty voiced region")
    med = float(np.median(region[region > 0])) if np.any(region > 0) else 0.0

    # every local minimum inside the span, deepest first; the threshold only
    # has to be loose, because the gap constraint does the real selection
    cand = []
    for i in range(1, len(env) - 1):
        if not (t0 + edge_ms < times[i] < t1 - edge_ms):
            continue
        if env[i] <= env[i - 1] and env[i] <= env[i + 1]:
            cand.append((env[i], float(times[i])))
    cand.sort()
    print("  segmentation: %d local minima inside span, median energy %.4f"
          % (len(cand), med))

    cuts = []
    for val, t in cand:
        if all(abs(t - c) >= min_gap_ms for c in cuts):
            cuts.append(t)
        if len(cuts) == n_syllables - 1:
            break
    cuts.sort()
    if len(cuts) != n_syllables - 1:
        print("  [warn] only %d/%d valleys found, falling back to equal division"
              % (len(cuts), n_syllables - 1))
        bounds = list(np.linspace(t0, t1, n_syllables + 1))
    else:
        bounds = [t0] + cuts + [t1]
    return [(bounds[i], bounds[i + 1]) for i in range(n_syllables)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--text", required=True, help="lyrics, one char per syllable")
    ap.add_argument("--tones", default="", help="comma separated, e.g. 3,3,2,3")
    ap.add_argument("--out", default="testdata")
    ap.add_argument("--clarity", type=float, default=0.16)
    ap.add_argument("--solve", action="store_true")
    ap.add_argument("--stretch", type=float, default=1.0)
    ap.add_argument("--smooth", type=int, default=1)
    ap.add_argument("--tonic", type=int, default=60)
    ap.add_argument("--ref-hz", type=float, default=220.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    x, fs = read_wav(a.wav)
    times, f0, rms, clar = f0_track(x, fs, yin_thresh=a.clarity)
    f0s = median_filter(f0, 5)
    before = f0s.copy()
    f0s = repair_octaves(times, f0s)
    fixed = int(np.sum((before > 0) & (f0s != before)))
    if fixed:
        print("  octave repair touched %d frames" % fixed)

    chars = list(a.text)
    print("wav: %.2fs @ %d Hz, %d frames, voiced %.0f%%"
          % (len(x) / fs, fs, len(times), 100.0 * np.mean(f0s > 0)))
    bounds = segment_dp(times, rms, f0s, len(chars))
    if bounds is None:
        print("  [warn] DP segmentation infeasible, using dip-greedy")
        bounds = segment(times, rms, f0s, len(chars))
    print("  syllable durations (ms):",
          [int(round(e - s)) for s, e in bounds])

    tones = [int(t) for t in a.tones.split(",")] if a.tones.strip() else [0] * len(chars)
    f0_path = os.path.join(a.out, "f0.csv")
    with open(f0_path, "w", encoding="utf-8", newline="") as f:
        f.write("t_ms,f0_hz\n")
        for t, v in zip(times, f0s):
            f.write("%.2f,%.2f\n" % (t, v))          # 0 Hz marks unvoiced

    syl_path = os.path.join(a.out, "syl.csv")
    with open(syl_path, "w", encoding="utf-8", newline="") as f:
        f.write("char,tone,onset_ms,end_ms\n")
        for i, (s, e) in enumerate(bounds):
            ch = chars[i] if i < len(chars) else "-"
            tn = tones[i] if i < len(tones) else 0
            f.write("%s,%d,%.1f,%.1f\n" % (ch, tn, s, e))

    print("boundaries:", ["%.0f-%.0f" % (s, e) for s, e in bounds])
    print("[ok]", f0_path)
    print("[ok]", syl_path)

    if a.solve:
        import f0_from_csv  # noqa: F401
        os.system('python f0_from_csv.py --syl "%s" --f0 "%s" --ref-hz %s '
                  '--tonic %d --stretch %s --smooth %d --out "%s"'
                  % (syl_path, f0_path, a.ref_hz, a.tonic, a.stretch, a.smooth,
                     os.path.join(a.out, "motive")))


if __name__ == "__main__":
    main()

