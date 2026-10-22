"""Minimal SMF (format 1) writer - stdlib only, so no pip is needed."""

import struct


def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def _track(events, ppq):
    """events: list of (tick, order, bytes)."""
    events = sorted(events, key=lambda e: (e[0], e[1]))
    data = bytearray()
    last = 0
    for tick, _, payload in events:
        data += _vlq(tick - last)
        data += payload
        last = tick
    data += _vlq(0) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + bytes(data)


def write_midi(path, tempo_bpm, tracks, ppq=480):
    """tracks: list of (name, program, notes) with notes = (start_q, dur_q, pitch)."""
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks) + 1, ppq)

    beat_ms = 60000.0 / tempo_bpm
    us = int(round(beat_ms * 1000))
    cond = [(0, 0, b"\xff\x51\x03" + us.to_bytes(3, "big")),
            (0, 0, b"\xff\x58\x04\x04\x02\x18\x08"),
            (0, 0, b"\xff\x03" + bytes([len(b"conductor")]) + b"conductor")]
    chunks = [_track(cond, ppq)]

    for name, program, notes in tracks:
        ev = [(0, 0, b"\xff\x03" + _vlq_len(name.encode()) + name.encode()),
              (0, 1, bytes([0xC0, program & 0x7F]))]
        for note in notes:
            start_q, dur_q, pitch = note[0], note[1], note[2]
            vel = int(note[3]) if len(note) > 3 else 80
            on = int(round(start_q * ppq))
            off = int(round((start_q + dur_q) * ppq))
            ev.append((on, 2, bytes([0x90, pitch & 0x7F, max(1, min(127, vel))])))
            ev.append((off, 1, bytes([0x80, pitch & 0x7F, 0])))
        chunks.append(_track(ev, ppq))

    with open(path, "wb") as f:
        f.write(header)
        for c in chunks:
            f.write(c)
    return path


def _vlq_len(b):
    n = len(b)
    return _vlq(n)
