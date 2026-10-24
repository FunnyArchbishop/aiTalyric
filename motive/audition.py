"""audition.py - one preset in, one listenable WAV out.

    python audition.py                                  # uses out_gui/preset_minor.json
    python audition.py --preset p.json -o out_take1
    python audition.py --preset p.json --min-note 1.0 --tempo 120

Writes, into the output directory:

    take.vsqx   VOCALOID4 project (open it in VOCALOID to get the real voice)
    take.ustx   OpenUtau project (free path; needs a Chinese voicebank)
    take.mid    piano sketch
    take.wav    formant-synth audition (this is the "audio file" right now)

The WAV is a synthetic vowel singer, not 洛天依.  It lets you judge melody,
lengths and melisma; the vsqx/ustx are what you render properly in an editor.
"""

import argparse
import json
import os

import export
import gui
import midi_io
import sing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="out_gui/preset_minor.json")
    ap.add_argument("-o", "--out", default="out_take")
    ap.add_argument("--melisma", type=int, default=None)
    ap.add_argument("--elongate", type=float, default=None)
    ap.add_argument("--min-note", type=float, default=None)
    ap.add_argument("--tempo", type=float, default=None)
    ap.add_argument("--max-repeat", type=int, default=None)
    ap.add_argument("--cell-theme", default=None)
    ap.add_argument("--instrument", default="piano",
                    help="piano/epiano/pluck/marimba/pad, or 'voice' for the vocal synth")
    ap.add_argument("--portamento", type=float, default=1.0)
    a = ap.parse_args()

    state = dict(gui.DEFAULTS)
    if a.preset and os.path.exists(a.preset):
        with open(a.preset, encoding="utf-8") as f:
            state.update(json.load(f))
    for key in ("melisma", "elongate", "min_note", "tempo", "max_repeat",
                "cell_theme"):
        v = getattr(a, key if key != "max_repeat" else "max_repeat")
        if v is not None:
            state[key] = v

    os.makedirs(a.out, exist_ok=True)
    model = gui.build_model(state)
    params = model["params"]
    tempo = float(state["tempo"])

    notes = []
    import align
    finals = [s["final"] for s in align.parse_syllables("".join(params["chars"]))]
    lyr = export.lyrics_for(model["slots"], params["chars"], finals)
    for j, m in enumerate(model["melody"]):
        notes.append(dict(start=m[0], dur=m[1], midi=int(m[2]),
                          lyric=(lyr[j] if j < len(lyr) else "a")))

    vsqx = os.path.join(a.out, "take.vsqx")
    export.write_vsqx(vsqx, notes, tempo, portamento=a.portamento)
    chk = export.check_vsqx(vsqx, expect_notes=len(notes))
    export.write_ustx(os.path.join(a.out, "take.ustx"), notes, tempo)
    midi_io.write_midi(os.path.join(a.out, "take.mid"), tempo,
                       [("melody", 73, model["melody"]),
                        ("chords", 0, model["chord_notes"])])

    wav = os.path.join(a.out, "take.wav")
    if a.instrument == "voice":
        sung = []
        for j, n in enumerate(notes):
            sung.append(dict(start_beats=n["start"], dur_beats=n["dur"],
                             midi=n["midi"], vowel=sing.vowel_of_lyric(n["lyric"])))
        path, secs = sing.render(sung, wav, tempo)
        flavour = "voice"
    else:
        import inst
        tracks = {
            "melody": [(n[0], n[1], int(n[2]), n[3] if len(n) > 3 else 90, a.instrument)
                       for n in model["melody"]],
            "chords": [(c[0], c[1], int(c[2]), 70, a.instrument)
                       for c in model["chord_notes"]],
        }
        path, secs = inst.render_tracks(tracks, wav, tempo)
        flavour = a.instrument

    m = model["metrics"]
    durs = sorted(int(round(x[1] * 60.0 / tempo * 1000)) for x in model["melody"])
    print("notes %d | phrase %.2f beats | chords %s | 倒字 %d | 最长同音 %d"
          % (m["notes"], sum(x[1] for x in model["melody"]), m["progression"],
             m["tone_violations"], m.get("max_repeat", 1)))
    print("note lengths (ms): shortest %d, median %d, longest %d"
          % (durs[0], durs[len(durs) // 2], durs[-1]))
    print("vsqx check:", chk["notes"], "notes,", chk["pit_points"], "PIT points")
    print("[ok]", vsqx)
    print("[ok]", wav, "(%s, %.1f s)" % (flavour, secs))


if __name__ == "__main__":
    main()
