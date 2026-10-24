"""ex08: use aiTalyric as a library - the smallest complete pipeline.

Everything is a plain function on plain dicts, so you can skip the CLIs and
drive it from your own code (a DAW bridge, a web backend, a batch run).

    python examples/ex08_library_min.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import joint        # noqa: E402
import midi_io      # noqa: E402
import realize      # noqa: E402
import run_demo     # noqa: E402
import theory       # noqa: E402

# 1. parameters for one phrase (here: the built-in demo; in real use this comes
#    from prosody.extract_params on your own F0)
a = type("A", (), dict(phrase="A", tempo=120.0, tonic=60, mode="major",
                       span=12.0, stretch=1.0, smooth=1))()
params, _ = run_demo.build(a)

# 2. expand syllables into notes (melisma + rhythm), then decode melody+chords
slots, chord_at, info = realize.realize(params, style=realize.load_style(None),
                                        rhythm_theme="sync")
p2 = realize.to_params(params, slots, chord_at)
path, ev, world = joint.solve_joint(p2, dict(run_demo.W0), 2)

# 3. collect MIDI events
melody, chords = [], []
for j, (_, c, p) in enumerate(path):
    s = slots[j]
    melody.append((s["start"], s["dur"] * 0.95, world["P"][p],
                   realize.accent_velocity(s)))
    if chord_at[j]:
        for q in theory.voicing(world["vocab"][c], params["tonic"]):
            chords.append((s["start"], s["dur"] * 0.95, q, 70 if q < 52 else 62))

os.makedirs("out_examples", exist_ok=True)
midi_io.write_midi("out_examples/ex08.mid", params["tempo"],
                   [("melody", 73, melody), ("chords", 0, chords)])

print("notes  :", " ".join(theory.note_name(m[2]) for m in melody))
print("energy :", {k: round(ev[k], 2) for k in ("total", "contour_rms",
                                                "harmony_violations")})
print("[ok] out_examples/ex08.mid")
