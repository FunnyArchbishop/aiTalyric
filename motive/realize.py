"""Melisma + groove realization: per-syllable params -> note slots.

A syllable is not one note.  The expansion is driven by the syllable's own F0
shape (sampled at `sub_points` time quantiles), and everything about it is
editable:

  * a style dict / JSON file holds every threshold, pattern and accent
  * --override lets you force the note count of individual syllables
  * the realized slots can be dumped to JSON, hand-edited (pitches included)
    and rendered again

The joint decoder is untouched: it still picks pitches and chords together, it
just sees more notes per syllable.  Chord changes are pinned to syllable
boundaries through params["chord_at"].
"""

import json
import math

GRID = 0.25          # beats per 16th at 4/4

DEFAULT_STYLE = {
    "_doc": {
        "melisma": "max extra notes per syllable (0 = one note per syllable)",
        "sub_points": "how many points sample the syllable's F0 shape (3..7)",
        "note_rules": "thresholds that decide the note count",
        "patterns": "duration split per note count, per style name",
        "grace": "optional short leading note (倚音)",
        "swing": "0..1, delays off-beat 8ths",
        "push": "per-syllable 16th offsets, e.g. '0,1,0,-1'",
        "per_syllable": "1-based syllable index -> forced note count",
        "accents": "MIDI velocities by onset position",
    },
    "melisma": 2,
    "sub_points": 5,
    "note_rules": {
        "two_above": 0.55,      # excursion that earns a 2nd note
        "three_above": 0.70,    # excursion needed for 3 notes
        "turn_eps": 0.12,       # middle must deviate this far from the straight line
        "held_beats": 1.75,     # a note held this long gets a run
        "run_beats": 2.50,      # a note held this long earns 4 notes
    },
    "patterns": {
        "tail": {1: [1.0], 2: [0.60, 0.40], 3: [0.46, 0.32, 0.22],
                 4: [0.42, 0.24, 0.19, 0.15]},
        "even": {1: [1.0], 2: [0.5, 0.5], 3: [1 / 3] * 3, 4: [0.25] * 4},
        "onset": {1: [1.0], 2: [0.40, 0.60], 3: [0.28, 0.38, 0.34],
                  4: [0.22, 0.26, 0.28, 0.24]},
        "run": {1: [1.0], 2: [0.5, 0.5], 3: [0.50, 0.25, 0.25],
                4: [0.40, 0.20, 0.20, 0.20]},
    },
    "grace": {"enabled": False, "min_beats": 1.0, "cells": 1, "rise_above": 0.55},
    "swing": 0.0,
    "push": "",
    "per_syllable": {},
    "accents": {"downbeat": 94, "offbeat": 88, "weak": 74, "swung": 90, "grace": 66},
    "chord_every": 2,
    "cell": GRID,
}


def merge_style(base=None, over=None):
    """Shallow-merge a user style over the defaults, one level deep."""
    out = json.loads(json.dumps(base or DEFAULT_STYLE))
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def load_style(path=None):
    if not path:
        return json.loads(json.dumps(DEFAULT_STYLE))
    with open(path, encoding="utf-8") as f:
        return merge_style(DEFAULT_STYLE, json.load(f))


def dump_style(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_STYLE, f, ensure_ascii=False, indent=2)
    return path


# ------------------------------------------------------------------ profiles

def _tile_to(parts, span):
    """Keep a cell's ratio pattern but make it sum exactly to `span`."""
    total = sum(parts)
    if total == span:
        return list(parts)
    return _split_cells_from_ratios(parts, span)


def _split_cells_from_ratios(parts, span):
    n = max(1, len(parts))
    total = float(sum(parts)) or float(n)
    cells = [max(1, int(round(span * p / total))) for p in parts[:n]]
    diff = span - sum(cells)
    k = n - 1
    guard = 0
    while diff != 0 and cells and guard < 1000:
        if diff > 0:
            cells[k] += 1
            diff -= 1
        elif cells[k] > 1:
            cells[k] -= 1
            diff += 1
        k = (k - 1) % n
        guard += 1
    return cells


def _sample(profile, n):
    """n representative pitches (normalised) across the syllable shape."""
    if n <= 1:
        return [sum(profile) / len(profile)]
    last = len(profile) - 1
    out = []
    for k in range(n):
        x = (k / (n - 1)) * last
        i0 = int(math.floor(x))
        i1 = min(i0 + 1, last)
        f = x - i0
        out.append(profile[i0] * (1 - f) + profile[i1] * f)
    return out


def turning(profile):
    """Max deviation of the shape from the straight line between its ends.

    Length-agnostic, so it works for 3, 5 or 7 sample points: a 3rd tone dips
    below that line, a 4th tone hugs it.
    """
    n = len(profile)
    if n < 3:
        return 0.0
    a, b = profile[0], profile[-1]
    dev = 0.0
    for i in range(1, n - 1):
        line = a + (b - a) * i / (n - 1)
        dev = max(dev, abs(profile[i] - line))
    return dev


def notes_for(profile, dur_beats, style):
    """How many notes this syllable gets, and why."""
    rules = style["note_rules"]
    melisma = max(0, int(style.get("melisma", 2)))
    exc = max(profile) - min(profile)
    turn = turning(profile)
    n, why = 1, "level"
    if melisma >= 1 and exc > rules["two_above"]:
        n, why = 2, "moving contour"
    if melisma >= 2 and turn > rules["turn_eps"] and exc > rules["three_above"]:
        n, why = 3, "turning tone (V/^)"
    if melisma >= 2 and dur_beats >= rules["held_beats"]:
        n = max(n, min(3, melisma + 1))
        why = why if n > 2 else "held note"
    if melisma >= 3 and dur_beats >= rules["run_beats"]:
        n = min(4, melisma + 1)
        why = "long held note, run"
    n = max(1, min(n, melisma + 1))
    return n, why, round(exc, 2), round(turn, 2)


# ------------------------------------------------------------------ patterns

def _split_cells(total, n, pattern_name, style):
    table = style["patterns"].get(pattern_name) or style["patterns"]["tail"]
    frac = table.get(n) if isinstance(table, dict) else None
    if not frac:
        frac = [1.0 / n] * n
    cells = [max(1, int(round(total * f))) for f in frac[:n]]
    diff = total - sum(cells)
    k = n - 1
    guard = 0
    while diff != 0 and cells and guard < 1000:
        if diff > 0:
            cells[k] += 1
            diff -= 1
        elif cells[k] > 1:
            cells[k] -= 1
            diff += 1
        k = (k - 1) % n
        guard += 1
    return cells


# ------------------------------------------------------------------ realize

def realize(params, style=None, pattern="tail", overrides=None,
            rhythm_theme=None, variation_every=4):
    """Return (slots, chord_at, per-syllable info)."""
    st = style or load_style(None)
    cell = float(st.get("cell", GRID))
    prof = params.get("sub_contour")
    beats = params["beats"]
    n_syl = len(beats)
    if not prof:
        prof = [[c, c, c] for c in params["contour"]]

    forced = {}
    for k, v in (st.get("per_syllable") or {}).items():
        forced[int(k) - 1] = int(v)
    for k, v in (overrides or {}).items():
        forced[int(k) - 1] = int(v)

    push_cells = [int(x) for x in str(st.get("push") or "").split(",") if x.strip()] or [0]
    MIN_SYL_CELLS = 2

    # 1. note counts
    plan = []
    for i in range(n_syl):
        n, why, exc, turn = notes_for(prof[i], beats[i], st)
        if i in forced:
            n, why = max(1, min(forced[i], max(1, int(st.get("melisma", 2)) + 1))), "manual override"
        plan.append(dict(n=n, why=why, exc=exc, turn=turn,
                         span=max(n, int(round(beats[i] / cell)))))

    # 1b. rhythmic cells: the theme decides how many notes and how long they are,
    #     unless the syllable was overridden by hand
    rhythm = None
    if rhythm_theme and rhythm_theme != "none":
        import rhythm as _rhythm
        rhythm = _rhythm.plan([p["span"] for p in plan], rhythm_theme, variation_every)
        if rhythm:
            for i, rp in enumerate(rhythm):
                if i in forced:
                    continue
                plan[i]["n"] = len(rp["parts"])
                plan[i]["why"] = "cell " + rp["letter"]
                plan[i]["letter"] = rp["letter"]

    # 2. syllabus placement on the grid (monotonic; push rushes/drags, never reorders)
    starts, cursor = [], 0
    for i in range(n_syl):
        s = cursor + push_cells[i % len(push_cells)]
        if starts:
            s = max(s, starts[-1] + MIN_SYL_CELLS)
        starts.append(s)
        cursor += plan[i]["span"]

    # 3. split each syllable into notes
    slots, chord_at, info = [], [], []
    for i in range(n_syl):
        n = plan[i]["n"]
        span = (starts[i + 1] - starts[i]) if i + 1 < n_syl else plan[i]["span"]
        span = max(span, n)
        if rhythm and i not in forced:
            parts = _tile_to(rhythm[i]["parts"], span)
            n = len(parts)
            cells = parts
        else:
            cells = _split_cells(span, n, pattern, st)
        targets = _sample(prof[i], n)
        sy_start = len(slots)

        # optional grace note (倚音) when the syllable starts much lower than it goes
        g = st.get("grace") or {}
        grace_cells = 0
        if (g.get("enabled") and beats[i] >= g.get("min_beats", 1.0)
                and (prof[i][1] - prof[i][0]) > g.get("rise_above", 0.55)
                and span > n + int(g.get("cells", 1))):
            grace_cells = int(g.get("cells", 1))
            slots.append(dict(syl=i, k=-1, n=n, grace=True,
                              start_cell=starts[i], cells=grace_cells,
                              target=prof[i][0], first=True, last=False))
            off = grace_cells
        else:
            off = 0
        for k in range(n):
            slots.append(dict(syl=i, k=k, n=n, grace=False,
                              start_cell=starts[i] + off, cells=cells[k],
                              target=targets[k], first=(k == 0),
                              last=(k == n - 1)))
            off += cells[k]
        chord_at.extend([False] * (len(slots) - sy_start))
        chord_at[sy_start] = (i % max(1, int(st.get("chord_every", 2))) == 0)
        info.append(dict(syl=i, notes=n + (1 if grace_cells else 0),
                         melisma_notes=n, grace=bool(grace_cells),
                         why=plan[i]["why"], excursion=plan[i]["exc"],
                         turn=plan[i]["turn"], cells=cells,
                         total_cells=max(off, span)))

    # 4. swing + monotonic onsets, then durations follow the onsets
    swing = float(st.get("swing") or 0.0)
    for j, s in enumerate(slots):
        if swing and abs(s["start_cell"] % 4 - 2) < 1e-9:
            s["start_cell"] += swing * 2.0
        if j:
            s["start_cell"] = max(s["start_cell"], slots[j - 1]["start_cell"] + 0.5)
    for j, s in enumerate(slots):
        nxt = (slots[j + 1]["start_cell"] if j + 1 < len(slots)
               else s["start_cell"] + s["cells"])
        s["start"] = s["start_cell"] * cell
        s["dur"] = max(cell, (nxt - s["start_cell"]) * cell)
    return slots, chord_at, info


def to_params(params, slots, chord_at):
    """A params object the unchanged joint decoder can consume."""
    out = dict(params)
    out["contour"] = [s["target"] for s in slots]
    out["beats"] = [s["dur"] for s in slots]
    out["chord_at"] = chord_at
    g_src = params["gestures"]
    g = []
    for s in slots:
        src = g_src[s["syl"]]
        g.append(dict(tone=src.get("tone", 0),
                      dir=src.get("dir", 0) if s["first"] else 0,
                      low=src.get("low", False),
                      measured_slope=src.get("measured_slope", 0.0),
                      conflict=False))
    out["gestures"] = g
    out["slot_syl"] = [s["syl"] for s in slots]
    # notes inside one syllable must be stepwise: a melisma that leaps is a
    # broken chord, not 转音; a grace note may leap, so it is not penalised
    out["motion_w"] = [1.0 if (s["first"] and s["k"] <= 0) else (1.0 if s.get("grace") else 2.6)
                       for s in slots]
    return out


def accent_velocity(slot, style=None):
    st = style or DEFAULT_STYLE
    acc = st.get("accents") or {}
    if slot.get("grace"):
        return int(acc.get("grace", 66))
    c = slot["start_cell"]
    if abs(c - round(c)) > 1e-6:
        return int(acc.get("swung", 90))
    c = int(round(c))
    if c % 4 == 0:
        return int(acc.get("downbeat", 94))
    if c % 4 == 2:
        return int(acc.get("offbeat", 88))
    return int(acc.get("weak", 74))


def describe(params, slots, info):
    lines = []
    tones = params.get("tones") or []
    chars = params.get("chars") or []
    for row in info:
        i = row["syl"]
        ch = chars[i] if i < len(chars) else "?"
        tone = tones[i] if i < len(tones) else 0
        shape = (params.get("sub_contour") or [[0, 0, 0]] * 99)[i]
        lines.append("%2d %-2s tone=%d shape=[%s] exc=%.2f turn=%.2f -> %d note(s)%s  %-22s cells=%s"
                     % (i + 1, ch, tone,
                        ", ".join("%+.2f" % v for v in shape),
                        row["excursion"], row.get("turn", 0.0),
                        row["notes"], " +倚音" if row.get("grace") else "",
                        "(" + row["why"] + ")", row["cells"]))
    return "\n".join(lines)


# ------------------------------------------------------- editable slot files

def dump_slots(path, params, slots, path_pitch=None, world=None):
    """Write the realized slots so they can be hand-edited and re-rendered."""
    rows = []
    for j, s in enumerate(slots):
        row = dict(syl=s["syl"] + 1, note=s["k"],
                   char=(params.get("chars") or ["?"] * 99)[s["syl"]],
                   start=round(s["start"], 4), dur=round(s["dur"], 4),
                   start_cell=s["start_cell"], cells=s["cells"],
                   target=round(s["target"], 4),
                   grace=bool(s.get("grace")))
        if path_pitch is not None:
            row["midi"] = int(path_pitch[j])
            row["name"] = None
        rows.append(row)
    doc = dict(notes=rows, chord_at=[[j, bool(c)] for j, c in enumerate([])])
    doc = dict(notes=rows)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return path


def load_slots(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    return doc["notes"] if isinstance(doc, dict) else doc
