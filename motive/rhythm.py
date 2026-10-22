"""Rhythmic cell themes: groove is repetition.

The ear locks onto a short rhythmic cell that comes back.  Until now every
syllable computed its own durations, so the result had swing but no groove.

A **cell** is a list of sixteenth counts that sums to one beat (4 cells at 4/4).
A **theme** is a small vocabulary of cells plus a letter pattern over the
syllables of a phrase.  Each syllable tiles its assigned cell to fill its own
span, so the same ratio pattern recurs at different lengths - which is what
makes it audible as a rhythm rather than as arithmetic.

    plan(spans, "sync")   spans in sixteenths, one per syllable
      -> [{syl, letter, cell, parts, varied}, ...]

`parts` sums exactly to the syllable's span, so the global grid never moves.
"""

import random

# cells sum to 4 sixteenths (one beat) unless noted
THEMES = {
    "none":    dict(cells=[], pattern="", note="no rhythmic cell at all"),
    "sync":    dict(cells=[[2, 1, 1], [3, 1], [1, 1, 2], [4]],
                    pattern="A B A B A C B A",
                    note="short-long-short syncopation"),
    "dotted":  dict(cells=[[3, 1], [2, 2], [1, 1, 1, 1]],
                    pattern="A B A B C B A B",
                    note="dotted eighth + sixteenth"),
    "flowing": dict(cells=[[2, 2], [1, 1, 2], [2, 1, 1]],
                    pattern="A B A C A B A C",
                    note="mostly eighths, occasional push"),
    "sparse":  dict(cells=[[4], [3, 1], [2, 1, 1]],
                    pattern="A A B A A B A B",
                    note="held notes, few subdivisions"),
}


def _tile(cell, span):
    """Repeat `cell` until it covers `span` sixteenths, then trim the tail."""
    span = max(1, int(span))
    if not cell:
        return [span]
    parts = list(cell)
    guard = 0
    while sum(parts) < span and guard < 512:
        parts.extend(cell)
        guard += 1
    while sum(parts) > span and len(parts) > 1:
        if parts[-1] > 1:
            parts[-1] -= 1
        else:
            parts.pop()
    if sum(parts) != span:
        parts = [span]
    return parts


def _variant(parts):
    """Augment a cell: split its longest part, keeping the total intact."""
    if len(parts) < 1:
        return parts, False
    total = sum(parts)
    k = max(range(len(parts)), key=lambda i: parts[i])
    if parts[k] < 2:
        return parts, False
    out = list(parts)
    out[k] = 1
    out.insert(k + 1, parts[k] - 1)
    return out, sum(out) == total


def plan(spans, theme="sync", variation_every=4, seed=0):
    """Assign a cell to every syllable, with repetition and periodic variation."""
    th = THEMES.get(theme)
    if not th or not th["cells"]:
        return None
    cells = th["cells"]
    letters = th["pattern"].split()
    rng = random.Random(seed)
    out = []
    for i, span in enumerate(spans):
        letter = letters[i % len(letters)]
        idx = (ord(letter.upper()) - ord("A")) % len(cells)
        cell = list(cells[idx])
        parts = _tile(cell, span)
        varied = False
        if variation_every and (i + 1) % int(variation_every) == 0 and i:
            parts, varied = _variant(parts)
        out.append(dict(syl=i, letter=letter, cell=cell, parts=parts, varied=varied))
    return out


def stats(rhythm):
    """Reuse metrics: how often does the most common cell come back?"""
    if not rhythm:
        return dict(reuse=0.0, top=0, counts={}, at_least_3=False, pattern="",
                    varied=0)
    counts = {}
    for r in rhythm:
        counts[r["letter"]] = counts.get(r["letter"], 0) + 1
    n = len(rhythm)
    top = max(counts.values())
    return dict(reuse=round(top / float(n), 3), top=top, counts=counts,
                at_least_3=top >= 3,
                pattern=" ".join(r["letter"] for r in rhythm),
                varied=sum(1 for r in rhythm if r["varied"]))


def describe(rhythm, chars=None):
    if not rhythm:
        return "(no rhythm theme)"
    lines = []
    for r in rhythm:
        i = r["syl"]
        ch = chars[i] if chars and i < len(chars) else "?"
        lines.append("%2d %-2s %s cell=%-9s span=%2d -> %-16s%s"
                     % (i + 1, ch, r["letter"], str(r["cell"]),
                        sum(r["parts"]), str(r["parts"]),
                        "  (varied)" if r["varied"] else ""))
    return "\n".join(lines)
