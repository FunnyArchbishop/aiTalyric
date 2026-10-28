"""Regression tests for harmonic template selection (no display required)."""
import unittest
from types import SimpleNamespace

import gui
import joint
import progressions
import realize
import run_demo


class ProgressionTests(unittest.TestCase):
    def params(self, mode="major", phrase="A"):
        p, w = run_demo.build(SimpleNamespace(
            phrase=phrase, tempo=120., tonic=60, mode=mode,
            span=12., stretch=1., smooth=1))
        style = realize.load_style(None)
        style["elongate"] = 2.
        slots, ca, _ = realize.realize(p, style=style)
        return realize.to_params(p, slots, ca), w

    def labels(self, result):
        path, _, world = result
        return [world["vocab"][c][0] for _, c, _ in path]

    def test_presets_cycle_and_hold_inside_syllables(self):
        for mode in ("major", "minor", "penta"):
            p, w = self.params(mode)
            for name, sequence in progressions.PRESETS[mode].items():
                with self.subTest(mode=mode, preset=name):
                    p.update(progression_mode="preset", progression_preset=name)
                    result = joint.solve_joint(p, w)
                    labels = self.labels(result)
                    step = -1
                    for i, label in enumerate(labels):
                        if i == 0 or p["chord_at"][i]:
                            step += 1
                        self.assertEqual(label, sequence[step % len(sequence)])
                    self.assertEqual(result[1]["selected_progression"], name)

    def test_auto_selects_lowest_decode_cost(self):
        for phrase in ("A", "B", "C"):
            p, w = self.params(phrase=phrase)
            costs = {}
            for name in progressions.PRESETS["major"]:
                p.update(progression_mode="preset", progression_preset=name)
                costs[name] = joint.solve_joint(p, w, max_repeat=None)[1]["decode_cost"]
            p["progression_mode"] = "auto"
            result = joint.solve_joint(p, w, max_repeat=None)
            self.assertAlmostEqual(result[1]["decode_cost"], min(costs.values()))
            self.assertEqual(result[1]["selected_progression"], min(costs, key=costs.get))

    def test_custom_fixed_rate_and_secondary_dominant(self):
        p, w = self.params()
        p.pop("chord_at")
        p.update(progression_mode="custom", chord_progression="V/V, V, I")
        result = joint.solve_joint(p, w, chord_rate=2)
        labels = self.labels(result)
        self.assertEqual(labels, [["V/V", "V", "I"][(i // 2) % 3]
                                  for i in range(len(labels))])

    def test_free_rhythm_advances_at_each_note(self):
        p, w = self.params()
        p.update(progression_mode="custom", chord_progression=["I", "V"], harmony_free=True)
        self.assertEqual(self.labels(joint.solve_joint(p, w)),
                         ["I" if i % 2 == 0 else "V" for i in range(len(p["contour"]))])

    def test_invalid_inputs(self):
        p, w = self.params()
        for updates in (dict(progression_mode="bad"),
                        dict(progression_mode="preset", progression_preset="bad"),
                        dict(progression_mode="custom", chord_progression=""),
                        dict(progression_mode="custom", chord_progression="i,V")):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                joint.solve_joint(dict(p, **updates), w)
        with self.assertRaises(ValueError):
            joint.solve_joint(p, w, chord_rate=0)

    def test_gui_can_switch_modes_and_presets(self):
        state = dict(gui.DEFAULTS)
        for mode, name in (("auto", "pop"), ("preset", "pop"),
                           ("preset", "classic"), ("custom", "custom"), ("free", "free")):
            state.update(progression_mode=mode, progression_preset=name)
            model = gui.build_model(state)
            if mode != "auto":
                self.assertEqual(model["metrics"]["selected_progression"], name)
            self.assertTrue(model["chord_notes"])


if __name__ == "__main__":
    unittest.main()
