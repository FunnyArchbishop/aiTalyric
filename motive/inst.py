"""inst.py - render the generated music with instruments (no singing involved).

The pipeline outputs notes, so the natural audition is a piano playing them -
no voicebank, no editor, no virtual singer.  This is an additive instrument
model: inharmonic partials with per-partial decay, a hammer transient, damper
release, and velocity-dependent brightness.

    python inst.py --preset out_gui/preset_minor_fixed.json -o out_gui/piano.wav
    python inst.py out_gui/test1_p12.vsqx -o out_gui/test1_piano.wav
    python inst.py --preset p.json --instrument epiano -o x.wav

Instruments: piano, epiano, pluck, marimba, pad.
"""

import argparse
import math
import os
import wave

import numpy as np

SR = 44100

# partial amplitude roll-off, per-partial decay, extra knobs
INSTRUMENTS = {
    "piano": dict(
        rolloff=0.42, decay_base=1.15, decay_slope=0.85, inharm=0.0004,
        hammer=0.032, release=0.075, detune=0.00035, bright=1.0,
        attack=0.002, sustain=0.0, max_partials=22),
    "epiano": dict(
        rolloff=0.55, decay_base=0.75, decay_slope=0.55, inharm=0.0001,
        hammer=0.012, release=0.12, detune=0.0006, bright=0.7,
        attack=0.004, sustain=0.15, max_partials=14),
    "pluck": dict(
        rolloff=0.30, decay_base=2.6, decay_slope=1.6, inharm=0.00008,
        hammer=0.02, release=0.05, detune=0.0002, bright=1.1,
        attack=0.001, sustain=0.0, max_partials=16),
    "marimba": dict(
        rolloff=0.9, decay_base=3.2, decay_slope=3.0, inharm=0.02,
        hammer=0.03, release=0.04, detune=0.0, bright=0.8,
        attack=0.001, sustain=0.0, max_partials=6),
    "pad": dict(
        rolloff=0.28, decay_base=0.12, decay_slope=0.05, inharm=0.0,
        hammer=0.0, release=0.5, detune=0.0012, bright=0.5,
        attack=0.18, sustain=1.0, max_partials=12),
}


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


def tone_note(midi, dur_s, vel, inst, sr=SR, tail=0.35):
    """One instrument note: additive partials + transient + damper release."""
    p = INSTRUMENTS[inst]
    f0 = midi_hz(midi)
    n = int((dur_s + p["release"] * 6 + tail) * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)
    v = max(1, min(127, int(vel))) / 127.0
    bright = 1.0 + (p["bright"] - 1.0) * 0.5
    # inharmonicity grows towards the bass strings
    b = p["inharm"] * (1.0 + max(0.0, (60 - midi) / 30.0))

    k = 1
    while k <= p["max_partials"]:
        fk = k * f0 * math.sqrt(1.0 + b * k * k)
        if fk > sr / 2 - 600:
            break
        amp = math.exp(-p["rolloff"] * (k - 1))
        if k > 1:
            amp *= 0.55 + 0.9 * v          # louder = brighter
        r = p["decay_base"] + p["decay_slope"] * (k - 1)
        r *= (1.0 + f0 / 1400.0)           # high notes die sooner
        env = np.exp(-r * t)
        if p["sustain"]:
            env = env * (1 - p["sustain"]) + p["sustain"] * np.minimum(1.0, np.exp(-0.6 * t))
        if p["detune"]:
            d = p["detune"] * f0
            out += amp * 0.5 * np.sin(2 * np.pi * (fk - d) * t) * env
            out += amp * 0.5 * np.sin(2 * np.pi * (fk + d) * t + 0.7) * env
        else:
            out += amp * np.sin(2 * np.pi * fk * t) * env
        k += 1

    # hammer / attack transient
    if p["hammer"]:
        ln = int(0.016 * sr)
        rng = np.random.default_rng(int(midi) * 7 + 1)
        burst = rng.normal(0, 1, ln) * np.exp(-np.arange(ln) / (0.004 * sr))
        out[:ln] += burst * p["hammer"] * (0.5 + v)
    # attack ramp
    atk = max(1, int(p["attack"] * sr))
    if atk > 1:
        out[:atk] *= np.linspace(0, 1, atk) ** 0.6
    # damper: after the written duration the note is released quickly
    off = min(n, int(dur_s * sr))
    if off < n:
        rel = np.exp(-np.arange(n - off) / (p["release"] * sr))
        out[off:] *= rel

    return out * (v ** 1.5)


def render_tracks(tracks, out_wav, tempo=120.0, sr=SR, tail=0.9):
    """tracks: {name: [(start_beats, dur_beats, midi, vel[, inst])]} -> WAV."""
    beat_s = 60.0 / tempo
    end = 0.0
    for notes in tracks.values():
        for n in notes:
            end = max(end, (n[0] + n[1]) * beat_s)
    n_total = int((end + tail) * sr) + 1
    buf = np.zeros(n_total + 1)

    for name, notes in tracks.items():
        for n in notes:
            start, dur, midi = n[0], n[1], n[2]
            vel = n[3] if len(n) > 3 else 88
            inst = n[4] if len(n) > 4 else "piano"
            a = int(start * beat_s * sr)
            if a >= n_total:
                continue
            seg = tone_note(int(midi), max(0.05, dur * beat_s), vel, inst, sr, tail)
            b = min(n_total, a + len(seg))
            buf[a:b] += seg[:b - a]

    peak = float(np.max(np.abs(buf))) or 1.0
    pcm = (buf / peak * 0.9 * 32767).astype("<i2").tobytes()
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return out_wav, n_total / sr


def from_vsqx(path, transpose=0):
    import vsqx_pit
    info = vsqx_pit.parse_vsqx(path)
    beat_dots = info["resolution"]
    notes = []
    for n in info["notes"]:
        notes.append((n["tick"] / beat_dots, max(1, n["dur"]) / beat_dots,
                      n["height"] + transpose, 90))
    tempo = info["tempo"] / 100.0
    return notes, tempo


def from_preset(preset, overrides=None, transpose=0):
    import gui
    import json
    state = dict(gui.DEFAULTS)
    if preset and os.path.exists(preset):
        with open(preset, encoding="utf-8") as f:
            state.update(json.load(f))
    for k, v in (overrides or {}).items():
        state[k] = v
    model = gui.build_model(state)
    mel = [(m[0], m[1], int(m[2]) + transpose, m[3] if len(m) > 3 else 90)
           for m in model["melody"]]
    ch = [(c[0], c[1], int(c[2]) + transpose, 70)
          for c in model["chord_notes"]]
    return {"melody": mel, "chords": ch}, float(state["tempo"]), model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vsqx", nargs="?", default="")
    ap.add_argument("--preset", default="")
    ap.add_argument("-o", "--out", default="out_inst/piano.wav")
    ap.add_argument("--instrument", default="piano", choices=list(INSTRUMENTS))
    ap.add_argument("--transpose", type=int, default=0)
    ap.add_argument("--tempo", type=float, default=None)
    ap.add_argument("--chord-instrument", default="")
    a = ap.parse_args()

    if a.preset:
        tracks, tempo, model = from_preset(a.preset, transpose=a.transpose)
        for name in tracks:
            tracks[name] = [(n[0], n[1], n[2], n[3],
                             a.instrument if name == "melody"
                             else (a.chord_instrument or a.instrument))
                            for n in tracks[name]]
        m = model["metrics"]
        print("notes %d | chords %s | 倒字 %d | 最长同音 %d"
              % (m["notes"], m["progression"], m["tone_violations"],
                 m.get("max_repeat", 1)))
        out = a.out
    elif a.vsqx:
        notes, tempo = from_vsqx(a.vsqx, a.transpose)
        tracks = {"melody": [(n[0], n[1], n[2], n[3], a.instrument) for n in notes]}
        out = a.out if a.out != "out_inst/piano.wav" else \
            os.path.splitext(a.vsqx)[0] + "_%s.wav" % a.instrument
    else:
        raise SystemExit("give a .vsqx or --preset")

    if a.tempo:
        tempo = a.tempo
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    path, secs = render_tracks(tracks, out, tempo)
    total = sum(len(v) for v in tracks.values())
    print("%s: %d notes, %.0f bpm, %.1f s" % (a.instrument, total, tempo, secs))
    print("[ok]", path)


if __name__ == "__main__":
    main()
