"""Named harmonic templates and strict per-slot chord schedules."""

import re

import theory

MODES = ("auto", "preset", "custom", "free")
PRESETS = {
    "major": {
        "pop": ["I", "V", "vi", "IV"],
        "classic": ["I", "IV", "V", "I"],
        "jazz": ["ii7", "V7", "I", "I"],
        "canon": ["I", "V", "vi", "iii", "IV", "I", "IV", "V"],
    },
    "minor": {
        "pop": ["i", "VI", "III", "VII"],
        "classic": ["i", "iv", "V", "i"],
        "jazz": ["ii", "V7", "i", "i"],
        "canon": ["i", "V", "VI", "III", "iv", "i", "iv", "V"],
    },
}
PRESETS["penta"] = PRESETS["major"]


def candidates(params):
    presets = PRESETS[params["mode"]]
    mode = params["progression_mode"]
    if mode == "auto":
        return list(presets.items())
    if mode == "preset":
        name = params.get("progression_preset", "pop")
        if name not in presets:
            raise ValueError("unknown progression preset: %s" % name)
        return [(name, presets[name])]
    sequence = params.get("chord_progression", "")
    labels = ([x for x in re.split(r"[\s,，-]+", sequence.strip()) if x]
              if isinstance(sequence, str) else list(sequence))
    if not labels:
        raise ValueError("custom progression must contain at least one chord")
    valid = {c[0] for c in theory.CHORD_VOCAB[params["mode"]]}
    unknown = [label for label in labels if label not in valid]
    if unknown:
        raise ValueError("chords unavailable in %s: %s" %
                         (params["mode"], ", ".join(unknown)))
    return [("custom", labels)]


def plan(params, labels, chord_rate):
    # Keep the same boundaries as the decoder, including free harmonic rhythm.
    import joint
    step = -1
    result = []
    for i in range(len(params["contour"])):
        if i == 0 or joint._is_boundary(params, i, chord_rate):
            step += 1
        result.append(labels[step % len(labels)])
    return result
