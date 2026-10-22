"""Lightweight forced alignment for Mandarin, with no acoustic model download.

Same idea as the melody decoder, one level down: the phone sequence is *known*
(pinyin gives every syllable's initial and final), so alignment is not
recognition - it is a constrained decode.

    states = sil, ([initial_i]?, final_i) * N, sil
    cost   = sum_states  (weighted feature-profile distance) + duration prior
    solver = exact segmental DP: each state spans one contiguous frame run

Emissions are hand-written class profiles over four cheap features
(log energy, zero-crossing rate, periodicity, spectral flux), robustly
standardised per utterance. Nothing is trained, so this will not beat MFA - but
it needs no models, no phonemiser, no conda, and unlike an energy-dip detector
it *cannot* split a vowel in two, because the number of nuclei is fixed by the
syllable sequence.

    python align.py --wav testdata/tts.wav --text 我想和你一起看海 \
        --tones 3,3,2,3,1,3,4,3 --solve
"""

import argparse
import json
import math
import os

import numpy as np

import f0_from_wav

INF = 1e18

# ---------------------------------------------------------------- phone model

INIT_CLASS = {}
for _c in "b p d t g k".split():
    INIT_CLASS[_c] = "stop"
for _c in "z c zh ch j q".split():
    INIT_CLASS[_c] = "affr"
for _c in "f s sh x h".split():
    INIT_CLASS[_c] = "fric"
for _c in "m n l r".split():
    INIT_CLASS[_c] = "son"

# class -> (log energy, ZCR, periodicity, spectral flux), robust z units
PROFILE = {
    "sil":   (-1.9, -0.4, -1.3, -0.5),
    "stop":  (-1.0, 0.3, -0.9, 1.3),
    "affr":  (-0.4, 1.1, -0.9, 0.9),
    "fric":  (-0.5, 1.2, -1.0, 0.5),
    "son":   (0.4, -0.4, 0.9, -0.3),
    "vowel": (0.9, -0.5, 1.1, -0.4),
}
PROFILE_SIGMA = 0.95
FEATURE_W = np.array([1.0, 0.8, 1.0, 0.5])

# class -> (min ms, mean ms, max ms), scaled by the measured speaking rate
DUR = {
    "sil":   (0, 20, 4000),      # edge silence: max is tokens, not biology
    "stop":  (20, 65, 110),
    "affr":  (40, 95, 160),
    "fric":  (45, 110, 180),
    "son":   (30, 80, 140),
    "vowel": (90, 210, 400),
}
TONE_LEN = {1: 1.00, 2: 0.95, 3: 1.15, 4: 1.10, 0: 0.70}
SKIP_COST = 0.8          # price of realising a written initial as nothing


# ------------------------------------------------------------------- features

def features(x, fs, win_ms=25.0, hop_ms=10.0, fmin=70.0, fmax=450.0):
    win = int(fs * win_ms / 1000.0)
    hop = int(fs * hop_ms / 1000.0)
    n = 1 + (len(x) - win) // hop
    w = np.hanning(win)
    lag_lo = max(2, int(fs / fmax))
    lag_hi = min(win - 2, int(fs / fmin))
    F = np.zeros((n, 4))
    prev_mag = None
    for k in range(n):
        seg = x[k * hop:k * hop + win]
        seg = seg - seg.mean()
        F[k, 0] = 10.0 * math.log10(float(np.mean(seg ** 2)) + 1e-10)
        sb = np.signbit(seg)
        F[k, 1] = float(np.mean(sb[1:] != sb[:-1]))
        spec = np.fft.rfft(seg * w, n=2 * win)
        acf = np.fft.irfft(np.abs(spec) ** 2, n=2 * win)
        if acf[0] > 0 and lag_hi > lag_lo:
            F[k, 2] = float(np.max(acf[lag_lo:lag_hi]) / acf[0])
        mag = np.abs(np.fft.rfft(seg * w))
        if prev_mag is not None:
            F[k, 3] = float(np.sum(np.maximum(0.0, mag - prev_mag)) / len(mag))
        prev_mag = mag
    times = (np.arange(n) * hop + win / 2.0) / fs * 1000.0
    return times, F


def robust_standardise(F):
    med = np.median(F, axis=0)
    p25, p75 = np.percentile(F, 25, axis=0), np.percentile(F, 75, axis=0)
    scale = np.maximum((p75 - p25) / 1.349, 1e-3)
    return (F - med) / scale


# --------------------------------------------------------------- state model

def parse_syllables(text, pinyin=None):
    chars = list(text)
    if pinyin:
        inits, finals = [], []
        for p in [q.strip().lower() for q in pinyin.split(",")]:
            ini = ""
            for cand in ("zh", "ch", "sh"):
                if p.startswith(cand):
                    ini = cand
                    break
            if not ini and p[:1] in "bpmfdtnlgkhjqxrzcsyw" and len(p) > 1:
                ini = p[:1]
            inits.append(ini)
            finals.append(p[len(ini):])
    else:
        try:
            from pypinyin import lazy_pinyin, Style
        except ImportError:
            raise SystemExit("need pypinyin (pip install pypinyin) "
                             "or pass --pinyin \"wo,xiang,he,ni\"")
        inits = lazy_pinyin(text, style=Style.INITIALS, strict=False)
        finals = lazy_pinyin(text, style=Style.FINALS, strict=False)
    rows = []
    for ch, ini, fin in zip(chars, inits, finals):
        ini = (ini or "").strip()
        if ini in ("y", "w"):
            ini = ""                     # spelling for zero-initial syllables
        rows.append(dict(char=ch, initial=ini, final=(fin or "").strip()))
    return rows


def build_states(syls, tones, rate_scale, hop_ms=10.0):
    fpm = 1.0 / hop_ms             # frames per millisecond (0.1 at a 10 ms hop)

    def d(cls, extra=1.0):
        lo, mean, hi = DUR[cls]
        return (int(round(lo * rate_scale * fpm)),
                max(1, int(round(mean * rate_scale * extra * fpm))),
                max(1, int(round(hi * rate_scale * fpm))))

    states = [dict(cls="sil", syl=None, optional=True, durs=d("sil"))]
    for i, s in enumerate(syls):
        cls = INIT_CLASS.get(s["initial"])
        if cls:
            states.append(dict(cls=cls, syl=i, optional=True, durs=d(cls)))
        tone = tones[i] if i < len(tones) else 1
        extra = TONE_LEN.get(tone, 1.0)
        if s["final"][-1:] in ("n", "g"):
            extra *= 1.12
        lo, mean, hi = d("vowel", extra)
        states.append(dict(cls="vowel", syl=i, optional=False,
                           durs=(max(1, lo), mean, hi)))
    states.append(dict(cls="sil", syl=None, optional=True, durs=d("sil", 0.6)))
    return states


def default_model():
    """class -> (mu, var) in robust z units, from the hand-set profiles."""
    return {c: (np.array(v, dtype=float), np.full(4, PROFILE_SIGMA ** 2))
            for c, v in PROFILE.items()}


def emission_costs(Fstd, states, model=None):
    model = model or default_model()
    S, T = len(states), Fstd.shape[0]
    emit = np.zeros((S, T))
    for j, st in enumerate(states):
        mu, var = model[st["cls"]]
        d = (Fstd - mu) ** 2 / var
        emit[j] = np.sum(d * FEATURE_W, axis=1)
    return emit


def adapt_model(Fstd, states, spans, model, k_prior=18.0, var_floor=0.16,
                var_cap=4.0):
    """One Viterbi-style re-estimation step (segment then refit the profiles).

    The hand-set profiles cannot know this speaker's feature distribution, so
    after each decode the per-class means and variances are recomputed from the
    frames that class was given, shrunk toward the prior so that 8 syllables
    cannot overfit.
    """
    new = {}
    for cls in set(st["cls"] for st in states):
        frames = [Fstd[a:b] for st, (a, b) in zip(states, spans)
                  if st["cls"] == cls and b > a]
        mu0, var0 = model[cls]
        if not frames:
            new[cls] = (mu0, var0)
            continue
        X = np.concatenate(frames, axis=0)
        n = X.shape[0]
        mu_d = X.mean(axis=0)
        var_d = X.var(axis=0)
        w = n / (n + k_prior)
        mu = (1 - w) * mu0 + w * mu_d
        var = (1 - w) * var0 + w * var_d
        new[cls] = (mu, np.clip(var, var_floor, var_cap))
    return new


def seg_dp(emit, states, T, dur_w=0.5):
    S = len(states)
    pref = np.zeros((S, T + 1))
    pref[:, 1:] = np.cumsum(emit, axis=1)
    dp = np.full((S, T + 1), INF)
    bp = np.zeros((S, T + 1), dtype=np.int32)
    dp[0, 0] = 0.0
    for j in range(1, S):
        st = states[j]
        lo, meanf, hi = st["durs"]
        lo, hi, meanf = max(0, lo), max(1, hi), max(1, meanf)
        dv = np.arange(0, hi + 1, dtype=float)
        dcost = np.full(hi + 1, INF)
        ok = dv >= lo
        if st["cls"] == "sil":
            # edge silence can be arbitrarily long; keep it cheap but not free
            dcost[ok] = 0.02 * dv[ok]
        else:
            dcost[ok] = dur_w * ((np.log(dv[ok] + 1.0) - np.log(meanf + 1.0)) / 0.45) ** 2
        if st["optional"]:
            dcost[0] = 0.0 if st["cls"] == "sil" else SKIP_COST
        prev = dp[j - 1]
        for t in range(1, T + 1):
            top = min(hi, t)
            if top < lo:
                continue
            ds = np.arange(lo, top + 1)
            aa = t - ds
            cand = prev[aa] + (pref[j, t] - pref[j, aa]) + dcost[ds]
            k = int(np.argmin(cand))
            if cand[k] < INF:
                dp[j, t] = cand[k]
                bp[j, t] = ds[k]
    if dp[S - 1, T] >= INF:
        return None, None
    spans = [None] * S
    t = T
    for j in range(S - 1, 0, -1):
        d = int(bp[j, t])
        spans[j] = (t - d, t)
        t -= d
    spans[0] = (0, t)
    return float(dp[S - 1, T]), spans


# ------------------------------------------------------------------- aligner

def align(x, fs, text, tones=None, pinyin=None, want_report=False, hop_ms=10.0,
          adapt=0):
    syls = parse_syllables(text, pinyin)
    tones = list(tones or []) + [1] * max(0, len(syls) - len(tones or []))

    times, F = features(x, fs, hop_ms=hop_ms)
    Fstd = robust_standardise(F)
    T = Fstd.shape[0]

    logE = F[:, 0]
    gate = np.percentile(logE, 60) - 12.0
    idx = np.where(logE > gate)[0]
    span_ms = (times[idx[-1]] - times[idx[0]]) if idx.size else float(times[-1])
    rate_scale = float(np.clip(span_ms / len(syls) / 230.0, 0.65, 1.6))

    states = build_states(syls, tones, rate_scale, hop_ms)
    model = default_model()
    n_iter = 1 + max(0, int(adapt))
    for it in range(n_iter):
        emit = emission_costs(Fstd, states, model)
        cost, spans = seg_dp(emit, states, T)
        if spans is None:
            raise SystemExit("alignment infeasible: durations do not fit the audio "
                             "(try another --wav or check the syllable count)")
        if it + 1 < n_iter:
            model = adapt_model(Fstd, states, spans, model)

    def t_start(j):
        a = spans[j][0]
        return float(times[min(a, T - 1)])

    def t_end(j):
        b = spans[j][1]
        return float(times[min(max(b - 1, 0), T - 1)])

    bounds, splits = [], []
    for i in range(len(syls)):
        js = [j for j, st in enumerate(states) if st["syl"] == i]
        bounds.append((t_start(js[0]), t_end(js[-1])))
        if len(js) > 1 and spans[js[0]][1] > spans[js[0]][0]:
            splits.append((t_start(js[0]), t_end(js[0])))
        else:
            splits.append(None)

    info = dict(rate_scale=round(rate_scale, 3), total_cost=round(cost, 1),
                n_states=len(states), n_frames=T,
                syllables=[dict(char=s["char"], initial=s["initial"],
                                final=s["final"], tone=tones[i],
                                onset_ms=round(bounds[i][0], 1),
                                end_ms=round(bounds[i][1], 1),
                                dur_ms=round(bounds[i][1] - bounds[i][0], 1),
                                initial_end_ms=None if splits[i] is None
                                else round(splits[i][1], 1))
                           for i, s in enumerate(syls)],
                states=[dict(cls=st["cls"], syl=st["syl"], frames=spans[j][1] - spans[j][0],
                             ms=round(t_end(j) - t_start(j), 1) if spans[j][1] > spans[j][0] else 0.0,
                             logE=round(float(F[spans[j][0]:max(spans[j][1], spans[j][0] + 1), 0].mean()), 1),
                             zcr=round(float(F[spans[j][0]:max(spans[j][1], spans[j][0] + 1), 1].mean()), 3),
                             per=round(float(F[spans[j][0]:max(spans[j][1], spans[j][0] + 1), 2].mean()), 2))
                        for j, st in enumerate(states)])
    return bounds, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--tones", default="")
    ap.add_argument("--pinyin", default="", help="comma separated: wo,xiang,he,ni")
    ap.add_argument("--out", default="testdata/aligned")
    ap.add_argument("--solve", action="store_true")
    ap.add_argument("--adapt", type=int, default=2,
                    help="unsupervised re-estimation passes (0 = hand-set profiles only)")
    ap.add_argument("--tonic", type=int, default=60)
    ap.add_argument("--stretch", type=float, default=1.0)
    ap.add_argument("--smooth", type=int, default=1)
    ap.add_argument("--ref-hz", type=float, default=220.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    x, fs = f0_from_wav.read_wav(a.wav)
    tones = [int(t) for t in a.tones.split(",")] if a.tones.strip() else []
    pylist = a.pinyin.strip() or None
    bounds, info = align(x, fs, a.text, tones, pylist, want_report=True,
                         adapt=a.adapt)

    print("rate_scale=%.2f  states=%d  cost=%.0f"
          % (info["rate_scale"], info["n_states"], info["total_cost"]))
    print("durations:", [int(round(b[1] - b[0])) for b in bounds])
    for s in info["syllables"]:
        print("  %s %-3s/%-5s tone=%d  %6.0f-%6.0f  %4.0fms%s"
              % (s["char"], s["initial"] or "-", s["final"], s["tone"],
                 s["onset_ms"], s["end_ms"], s["dur_ms"],
                 "" if s["initial_end_ms"] is None
                 else "  initial ends %.0f" % s["initial_end_ms"]))

    times, f0, rms, clar = f0_from_wav.f0_track(x, fs)
    f0s = f0_from_wav.repair_octaves(times, f0_from_wav.median_filter(f0, 5))
    f0_path = os.path.join(a.out, "f0.csv")
    with open(f0_path, "w", encoding="utf-8", newline="") as f:
        f.write("t_ms,f0_hz\n")
        for t, v in zip(times, f0s):
            f.write("%.2f,%.2f\n" % (t, v))
    syl_path = os.path.join(a.out, "syl.csv")
    with open(syl_path, "w", encoding="utf-8", newline="") as f:
        f.write("char,tone,onset_ms,end_ms\n")
        for s in info["syllables"]:
            f.write("%s,%d,%.1f,%.1f\n" % (s["char"], s["tone"], s["onset_ms"], s["end_ms"]))
    with open(os.path.join(a.out, "align_report.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print("[ok]", f0_path)
    print("[ok]", syl_path)

    if a.solve:
        os.system('python f0_from_csv.py --syl "%s" --f0 "%s" --ref-hz %s '
                  '--tonic %d --stretch %s --smooth %d --out "%s"'
                  % (syl_path, f0_path, a.ref_hz, a.tonic, a.stretch, a.smooth,
                     os.path.join(a.out, "motive")))


if __name__ == "__main__":
    main()
