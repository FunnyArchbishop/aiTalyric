"""Joint decoding of melody and harmony.

One objective, one DP.  Nothing here is a "translation" step: the prosody only
supplies a *soft target*, harmony only supplies *soft constraints plus
transition dynamics*, and both are decoded together.

    E =  sum_i  w_c * ((p_i - target_i)/sigma)^2        melodic contour fit
       + sum_i  w_t * tone_cost(dir_i, p_i, p_i-1)      Mandarin tone direction
       + sum_i  w_h * strong_i * [p_i not in chord]     harmonic consonance
       + sum_i  w_m * motion(p_i-1, p_i)                melodic motion
       + sum_j  functional(c_j-1, c_j)                  harmonic syntax

State = (chord, pitch); transitions carry the melody-side couplings, so the
optimum is global, not greedy.  The chord may only change on slot boundaries,
which is what keeps the trellis small (|C| x |P| ~ 100-200 states).
"""

import numpy as np

import theory

INF = 1e9


def _motion_table():
    t = np.full(64, 1.9)
    t[0] = 0.30      # repeated note: not free any more, it is the dullest move
    t[1] = 0.00
    t[2] = 0.02
    t[3] = 0.10
    t[4] = 0.16
    t[5] = 0.42
    t[6] = 0.95      # tritone
    t[7] = 0.42
    t[8] = 0.95
    t[9] = 0.70
    t[10] = 1.15
    t[11] = 0.60
    t[12] = 1.00
    return t


MOTION = _motion_table()


def _tone_cost(dir_i, world):
    """Cost matrix over (prev_pitch, cur_pitch) for one syllable's tone demand."""
    sign_mat = world["sign"]
    if dir_i > 0:
        return np.where(sign_mat > 0, 0.0, np.where(sign_mat == 0, 0.35, 1.0))
    if dir_i < 0:
        return np.where(sign_mat < 0, 0.0, np.where(sign_mat == 0, 0.35, 1.0))
    # level tone (T1 / T3-in-context): mildly prefers to stay level
    d = world["dist"].astype(float)
    return np.minimum(1.0, 0.22 * np.maximum(0.0, d - 2.0))


def _motion_for(d):
    return MOTION[np.clip(d, 0, 63)]


def build_world(params, pitch_lo=None, pitch_hi=None):
    tonic = params["tonic"]
    mode = params["mode"]
    scale = theory.SCALES[mode]
    # The candidate range must contain the targets.  A fixed 57..76 window
    # clamps low targets onto the floor, and every note that wants to go lower
    # then comes out as the same pitch - which is exactly the "same note over
    # and over" that sounds wrong.
    if pitch_lo is None or pitch_hi is None:
        tg = _targets(params)
        lo = int(min(tg)) - 3
        hi = int(max(tg)) + 3
        if hi - lo < 14:
            mid = (hi + lo) / 2.0
            lo, hi = int(mid - 7), int(mid + 7)
        pitch_lo = max(40, lo) if pitch_lo is None else pitch_lo
        pitch_hi = min(88, hi) if pitch_hi is None else pitch_hi
    P = [p for p in range(pitch_lo, pitch_hi + 1) if (p - tonic) % 12 in scale]
    vocab = theory.CHORD_VOCAB[mode]
    roles = [c[2] for c in vocab]
    roots = [c[1][0] for c in vocab]
    targets = [c[3] for c in vocab]
    pens = [c[5] if len(c) > 5 else 0.0 for c in vocab]
    m = len(vocab)

    # Transition cost: a secondary dominant must resolve to its target, every
    # other move follows the T/S/D grammar, and each chord carries its own
    # idiomaticity penalty (64 chords, vii, borrowed chords).
    trans = np.zeros((m, m))
    for a in range(m):
        for b in range(m):
            if targets[a] is not None:
                trans[a, b] = 0.0 if (roots[b] - targets[a]) % 12 == 0 else 2.0
            else:
                trans[a, b] = theory.ROLE_COST[(roles[a], roles[b])]
            trans[a, b] += pens[b]

    pcs = [{(tonic + o) % 12 for o in c[1]} for c in vocab]
    npitch, m = len(P), len(vocab)
    in_chord = np.zeros((m, npitch), dtype=bool)
    for ci in range(m):
        for pi, p in enumerate(P):
            in_chord[ci, pi] = (p % 12) in pcs[ci]
    Parr = np.array(P, dtype=float)
    sign = np.sign(Parr[None, :] - Parr[:, None])          # (prev, cur)
    dist = np.abs(Parr[None, :] - Parr[:, None]).astype(int)
    motion = MOTION[np.clip(dist, 0, 63)]
    tonic_label = "I" if mode != "minor" else "i"
    tonic_idx = [i for i, c in enumerate(vocab) if c[0] == tonic_label][0]
    return dict(P=P, vocab=vocab, roles=roles, trans=trans, in_chord=in_chord,
                sign=sign, dist=dist, motion=motion, m=m, npitch=npitch,
                tonic=tonic, tonic_idx=tonic_idx, Parr=Parr)


def _targets(params):
    half = params["span_semitones"] / 2.0
    k = params["stretch"]
    return [params["tonic"] + k * half * c for c in params["contour"]]


def _is_boundary(params, i, chord_rate):
    """Chord may change at slot i.  params["chord_at"] overrides the fixed rate,
    which is how a melisma (several notes inside one syllable) keeps its chords
    aligned with syllable boundaries instead of with notes.  params["harmony_free"]
    lets the chord move at every note, with a change cost doing the pacing."""
    if params.get("harmony_free"):
        return True
    ca = params.get("chord_at")
    if ca is not None:
        return bool(ca[i])
    return i % chord_rate == 0


def _emit(params, world, W, targets, i, chord_rate):
    P = world["Parr"]
    sigma = W["sigma"]
    e = W["w_contour"] * ((P - targets[i]) / sigma) ** 2          # (npitch,)
    bias = params.get("bias_pitch") or {}
    if i in bias:                       # search aid: discourage a pitch that
        pen = float(params.get("repeat_penalty", 2.0))
        e = e + np.where(P == bias[i], pen, 0.0)
    strong = 1.5 if _is_boundary(params, i, chord_rate) else 0.6
    hw = params.get("harmony_w")
    if hw is not None:
        strong *= float(hw[i])
    e_h = W["w_harmony"] * strong * (~world["in_chord"]).astype(float)  # (m,npitch)
    return e[None, :] + e_h


def solve_joint(params, W, chord_rate=2, verbose=False, max_repeat=2,
                refine_rounds=2):
    """Decode melody + harmony.  With max_repeat set, runs of the same pitch
    longer than that are broken up by re-decoding with a local penalty.

    A run of identical pitches sounds like a stuck note, but making repeats
    expensive globally fights the tone system (a level-tone pair *should* repeat)
    and measurably raises 倒字.  So the objective stays untouched and the repair
    is a separate, local search step: find over-long runs, discourage exactly
    those pitches at exactly those slots, decode again.
    """
    if max_repeat is None:
        path, ev, world = _solve_once(params, W, chord_rate)
        ev["repeat_repairs"] = 0
        return path, ev, world

    p = dict(params)
    p["bias_pitch"] = dict(params.get("bias_pitch") or {})
    cands = []
    for _ in range(max(1, refine_rounds) + 1):
        path, ev, world = _solve_once(p, W, chord_rate)
        seq = [world["P"][x[2]] for x in path]
        longest = 1 if seq else 0
        cur = 1
        for a, b in zip(seq, seq[1:]):
            cur = cur + 1 if a == b else 1
            longest = max(longest, cur)
        cands.append((longest, ev["total"], path, ev, world, len(p["bias_pitch"])))
        if longest <= int(max_repeat):
            break
        bad, i = {}, 0
        while i < len(seq):
            j = i
            while j + 1 < len(seq) and seq[j + 1] == seq[i]:
                j += 1
            if j - i + 1 > int(max_repeat):
                for k in range(i + 1, j + 1):
                    bad[k] = seq[i]
            i = j + 1
        if not bad:
            break
        changed = False
        for k, v in bad.items():
            if p["bias_pitch"].get(k) != v:
                p["bias_pitch"][k] = v
                changed = True
        if not changed:
            break
    # fewest repeated notes first, then the best objective; the repair may cost
    # a little energy, which is the honest price of not sounding like a stuck key
    longest, total, path, ev, world, nbias = min(cands, key=lambda c: (c[0], c[1]))
    ev["repeat_repairs"] = nbias
    ev["max_repeat"] = longest
    return path, ev, world


def _solve_once(params, W, chord_rate=2, verbose=False):
    world = build_world(params)
    targets = _targets(params)
    dirs = [g["dir"] for g in params["gestures"]]
    n = len(targets)
    m, npitch = world["m"], world["npitch"]
    P = world["P"]
    S = m * npitch

    prev = _emit(params, world, W, targets, 0, chord_rate)
    if not params.get("start_chord_free"):
        want = params.get("start_role")
        start_bonus = np.array([
            0.0 if (world["roles"][c] == (want or "T")) else 3.0
            for c in range(m)])[:, None]
        prev = prev + start_bonus

    back = np.zeros((n, m, npitch), dtype=np.int32)

    same_slot = np.arange(m)[:, None] == np.arange(m)[None, :]

    for i in range(1, n):
        tone_term = W["w_tone"] * _tone_cost(dirs[i], world)
        if _is_boundary(params, i, chord_rate):
            chord_term = (world["trans"] + np.eye(m, dtype=float) * 0.55)
            w_change = float(params.get("harmony_change_cost", 0.0))
            if w_change:
                chord_term = chord_term + (np.ones((m, m)) - np.eye(m)) * w_change
        else:
            chord_term = np.where(same_slot, 0.0, INF)

        mw = params.get("motion_w")
        mscale = float(mw[i]) if mw is not None else 1.0

        t = (prev[:, :, None, None]                                   # (m,p,m,p)
             + tone_term[None, :, None, :]
             + (W["w_motion"] * mscale * world["motion"])[None, :, None, :]
             + chord_term[:, None, :, None]
             + _emit(params, world, W, targets, i, chord_rate)[None, None, :, :])

        flat = t.reshape(S, S)
        back[i] = flat.argmin(axis=0).reshape(m, npitch)
        prev = flat.min(axis=0).reshape(m, npitch)

    term = np.zeros((m, npitch))
    if params.get("must_end_tonic"):
        term += np.where(np.arange(m)[:, None] == world["tonic_idx"], 0.0, 6.0)
    if params.get("end_pref", True):
        term += np.where(np.array([world["roles"][c] for c in range(m)])[:, None] == "T",
                         0.0, 3.0)
    term[world["tonic_idx"], :] -= 0.0
    for pi, p in enumerate(P):
        if p % 12 != params["tonic"] % 12:
            term[:, pi] += 0.3
    final = prev + term
    flat = final.reshape(-1)
    idx = int(flat.argmin())
    c, p = divmod(idx, npitch)

    path = [(n - 1, c, p)]
    for i in range(n - 1, 0, -1):
        prev_idx = int(back[i][c, p])
        c, p = divmod(prev_idx, npitch)
        path.append((i - 1, c, p))
    path.reverse()
    return path, evaluate(path, params, W, chord_rate), world


def evaluate(path, params, W, chord_rate):
    """Energy decomposition of a concrete (melody, harmony) path."""
    world = build_world(params)
    targets = _targets(params)
    P = world["P"]
    sigma = W["sigma"]
    out = dict(contour=0.0, tone=0.0, harmony=0.0, motion=0.0, function=0.0,
               tone_violations=0, harmony_violations=0, leaps=[], chords=[])
    prev_c = prev_p = None
    for (i, c, p) in path:
        out["contour"] += W["w_contour"] * ((P[p] - targets[i]) / sigma) ** 2
        strong = 1.5 if _is_boundary(params, i, chord_rate) else 0.6
        hw = params.get("harmony_w")
        if hw is not None:
            strong *= float(hw[i])
        if not world["in_chord"][c, p]:
            out["harmony"] += W["w_harmony"] * strong
            out["harmony_violations"] += 1
        if prev_p is not None:
            d = P[p] - P[prev_p]
            out["leaps"].append(d)
            out["motion"] += W["w_motion"] * MOTION[min(63, abs(d))]
            tc = _tone_cost(params["gestures"][i]["dir"], world)[prev_p, p]
            out["tone"] += W["w_tone"] * tc
            if tc > 0.5:
                out["tone_violations"] += 1
        if prev_c is not None and c != prev_c:
            out["function"] += world["trans"][prev_c, c]
        prev_c, prev_p = c, p
        out["chords"].append(world["vocab"][c][0])
    out["total"] = (out["contour"] + out["tone"] + out["harmony"]
                    + out["motion"] + out["function"])
    leaps = out["leaps"]
    out["contour_rms"] = (out["contour"] / max(1e-9, W["w_contour"] * len(path))) ** 0.5 * sigma
    out["max_leap"] = max((abs(x) for x in leaps), default=0)
    out["stepwise_ratio"] = (sum(1 for x in leaps if abs(x) <= 2) / len(leaps)) if leaps else 1.0
    # repeated-note stats: a run of identical pitches is dull, so it is visible
    seq = [P[p] for (_, _, p) in path]
    best = cur = 1 if seq else 0
    for a, b in zip(seq, seq[1:]):
        cur = cur + 1 if a == b else 1
        best = max(best, cur)
    out["max_repeat"] = best
    out["repeat_pairs"] = sum(1 for a, b in zip(seq, seq[1:]) if a == b)
    return out


def solve_two_step(params, W, chord_rate=2):
    """Baseline: quantise the contour first, then harmonise the frozen melody."""
    world = build_world(params)
    targets = _targets(params)
    P = world["P"]
    dirs = [g["dir"] for g in params["gestures"]]
    n = len(targets)

    melody = []
    for i in range(n):
        cands = sorted(range(len(P)), key=lambda pi: abs(P[pi] - targets[i]))
        pick = cands[0]
        if melody and dirs[i] != 0:
            ok = [pi for pi in cands if np.sign(P[pi] - P[melody[-1]]) == dirs[i]]
            if ok:
                pick = ok[0]
        melody.append(pick)

    # chord DP with the melody fixed
    m = world["m"]
    ca = params.get("chord_at")
    if ca is not None:
        groups, cur = [], []
        for i in range(n):
            cur.append(i)
            if ca[i]:
                groups.append(cur)
                cur = []
        if cur:
            groups.append(cur)
    else:
        groups = [list(range(s * chord_rate, min(n, (s + 1) * chord_rate)))
                  for s in range((n + chord_rate - 1) // chord_rate)]
    nslots = len(groups)
    cost = np.zeros((nslots, m))
    for s in range(nslots):
        for c in range(m):
            acc = 0.0
            for i in groups[s]:
                strong = 1.5 if _is_boundary(params, i, chord_rate) else 0.6
                if not world["in_chord"][c, melody[i]]:
                    acc += W["w_harmony"] * strong
            cost[s, c] = acc
    prev = cost[0] + np.array([0.0 if world["roles"][c] == "T" else 1.2 for c in range(m)])
    bp = np.zeros((nslots, m), dtype=int)
    for s in range(1, nslots):
        t = prev[:, None] + world["trans"] + np.eye(m) * 0.55 + cost[s][None, :]
        bp[s] = t.argmin(axis=0)
        prev = t.min(axis=0)
    term = np.where(np.array([world["roles"][c] for c in range(m)]) == "T", 0.0, 3.0)
    term[world["tonic_idx"]] -= 0.0
    c = int((prev + term).argmin())
    chords = [c]
    for s in range(nslots - 1, 0, -1):
        c = int(bp[s][c])
        chords.append(c)
    chords.reverse()

    slot_of_chord = {}
    for s_, g in enumerate(groups):
        for i in g:
            slot_of_chord[i] = s_
    path = [(i, chords[slot_of_chord[i]], melody[i]) for i in range(n)]
    return path, evaluate(path, params, W, chord_rate), world
