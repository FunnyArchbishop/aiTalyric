import unittest
from types import SimpleNamespace
import gui
import theory
import tension_map


class TensionMapTests(unittest.TestCase):
    def test_all_chords_have_bounded_coordinates(self):
        for mode, vocab in theory.CHORD_VOCAB.items():
            for previous in [None] + [c[0] for c in vocab]:
                points = tension_map.points(mode, previous)
                self.assertEqual({p['label'] for p in points}, {c[0] for c in vocab})
                self.assertTrue(all(0 <= p['x'] <= 1 and 0 <= p['y'] <= 1 for p in points))
                if previous is None:
                    self.assertTrue(all(p['y'] == 0 for p in points))

    def test_dominant_resolution_has_less_transition_tension(self):
        pts = {p['label']: p for p in tension_map.points('major', 'V7')}
        self.assertLess(pts['I']['y'], pts['IV']['y'])
        self.assertLess(pts['I']['x'], pts['V7']['x'])

    def test_click_replaces_only_selected_progression_position(self):
        state = dict(gui.DEFAULTS)
        model = gui.build_model(state)
        before = list(model['chord_sequence'])
        for key in ('progression_mode', 'chord_progression'):
            state['_var_' + key] = SimpleNamespace(set=lambda value: None)
        app = SimpleNamespace(state=state, model=model, _after=None)
        def rebuild():
            app.model = gui.build_model(app.state)
        app.rebuild = rebuild
        gui.App.select_map_chord(app, 1, 'vi')
        expected = before[:]
        expected[1] = 'vi'
        self.assertEqual(app.model['chord_sequence'], expected)
        self.assertEqual(state['progression_mode'], 'custom')
        self.assertNotEqual(model['chord_notes'], app.model['chord_notes'])


if __name__ == '__main__':
    unittest.main()
