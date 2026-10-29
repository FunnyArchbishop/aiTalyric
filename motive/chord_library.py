"""Independent, generated chord/voicing catalogue; no third-party database."""
from functools import lru_cache
import math

NAMES = ('C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B')
QUALITIES = {
    'maj': (0,4,7), 'min': (0,3,7), 'dim': (0,3,6), 'aug': (0,4,8),
    'sus2': (0,2,7), 'sus4': (0,5,7), 'maj7': (0,4,7,11), '7': (0,4,7,10),
    'min7': (0,3,7,10), 'minMaj7': (0,3,7,11), 'dim7': (0,3,6,9),
    'm7b5': (0,3,6,10), '6': (0,4,7,9), 'min6': (0,3,7,9),
    'add9': (0,4,7,14), 'madd9': (0,3,7,14), 'add11': (0,4,7,17),
    '9': (0,4,7,10,14), 'maj9': (0,4,7,11,14), 'min9': (0,3,7,10,14),
    '7b9': (0,4,7,10,13), '7#9': (0,4,7,10,15), '7#11': (0,4,7,10,18),
    '7b13': (0,4,7,10,20), '11': (0,4,7,10,14,17),
    'min11': (0,3,7,10,14,17), 'maj13': (0,4,7,11,14,21),
    '13': (0,4,7,10,14,21), 'min13': (0,3,7,10,14,21),
    '69': (0,4,7,9,14), 'min69': (0,3,7,9,14), '7sus4': (0,5,7,10),
    '9sus4': (0,5,7,10,14), 'maj7#5': (0,4,8,11), '7#5': (0,4,8,10),
    '7b5': (0,4,6,10), 'quartal': (0,5,10), 'cluster': (0,2,4),
}


def make_chord(root, quality, inversion=0, register=48, spread=0):
    if root not in range(12) or quality not in QUALITIES:
        raise ValueError('Invalid chord root or quality')
    intervals = sorted(set(n % 12 for n in QUALITIES[quality]))
    if inversion not in range(len(intervals)) or spread not in range(4) or register not in (36,48,60,72):
        raise ValueError('Invalid voicing')
    notes = [register + root + n for n in intervals]
    notes = notes[inversion:] + [n+12 for n in notes[:inversion]]
    # Preserve the chosen bass while opening upper voices.
    notes = sorted(n + (12 if i > 0 and ((spread == 1 and i % 2) or
                   (spread == 2 and i % 2 == 0)) else 24 if spread == 3 and i > 0 else 0)
                   for i,n in enumerate(notes))
    if any(n < 0 or n > 127 for n in notes):
        raise ValueError('Voicing exceeds MIDI range')
    symbol = NAMES[root] + ('' if quality == 'maj' else 'm' if quality == 'min' else quality)
    if inversion:
        symbol += '/' + NAMES[notes[0] % 12]
    return dict(id=f'{root}:{quality}:{inversion}:{register}:{spread}', root=root,
                quality=quality, inversion=inversion, register=register, spread=spread,
                symbol=symbol, notes=notes)


@lru_cache(maxsize=1)
def catalogue():
    # Deduplicate pitch-identical voicings; retain a deterministic conventional name.
    seen, rows = set(), []
    for root in range(12):
        for quality, offsets in QUALITIES.items():
            for inversion in range(len(set(n % 12 for n in offsets))):
                for register in (36,48,60,72):
                    for spread in range(4):
                        try:
                            c = make_chord(root, quality, inversion, register, spread)
                        except ValueError:
                            continue
                        key = tuple(c['notes'])
                        if key not in seen:
                            seen.add(key)
                            rows.append(c)
    return tuple(rows)


def resolve(chord_id):
    try:
        root, quality, inversion, register, spread = chord_id.split(':')
        return make_chord(int(root), quality, int(inversion), int(register), int(spread))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError('Invalid chord ID') from exc


def intrinsic(notes):
    pcs = sorted(set(n % 12 for n in notes))
    pairs = [min((b-a)%12, (a-b)%12) for i,a in enumerate(pcs) for b in pcs[i+1:]]
    return sum({1:1., 2:.65, 3:.15, 4:.1, 5:0., 6:.9}[d] for d in pairs) / max(1,len(pairs))


def polar(chord):
    # Circle of fifths, clockwise from C; radial roughness independent of context.
    return ((chord['root'] * 7) % 12) * math.tau / 12 - math.pi/2, intrinsic(chord['notes'])


def export_database(path):
    """Materialize an indexed SQLite catalogue for external tools and inspection."""
    import json
    import os
    from pathlib import Path
    import sqlite3
    from contextlib import closing
    import tempfile
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,suffix='.sqlite');os.close(fd)
    try:
        with closing(sqlite3.connect(tmp)) as db, db:
            db.execute('CREATE TABLE chords (id TEXT PRIMARY KEY, symbol TEXT, root INTEGER, quality TEXT, inversion INTEGER, register INTEGER, spread INTEGER, notes TEXT UNIQUE, roughness REAL)')
            db.executemany('INSERT INTO chords VALUES (?,?,?,?,?,?,?,?,?)',
                [(c['id'],c['symbol'],c['root'],c['quality'],c['inversion'],c['register'],c['spread'],json.dumps(c['notes']),intrinsic(c['notes'])) for c in catalogue()])
            db.execute('CREATE INDEX chord_root_quality ON chords(root,quality)')
            db.execute('CREATE INDEX chord_roughness ON chords(roughness)')
            db.execute('PRAGMA user_version=1')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return len(catalogue())
