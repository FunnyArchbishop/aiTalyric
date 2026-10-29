import unittest
import editor
import gui


class EditorTests(unittest.TestCase):
    def test_insert_delete_reorder(self):
        seq, pos = editor.edit_sequence(['I', 'V', 'vi'], 1, 'duplicate')
        self.assertEqual((seq, pos), (['I', 'V', 'V', 'vi'], 2))
        seq, pos = editor.edit_sequence(seq, pos, 'right')
        self.assertEqual(seq, ['I', 'V', 'vi', 'V'])
        seq, pos = editor.edit_sequence(seq, pos, 'delete')
        self.assertEqual((seq, pos), (['I', 'V', 'vi'], 2))
        with self.assertRaises(ValueError):
            editor.edit_sequence(['I'], 0, 'delete')
        self.assertEqual(editor.edit_sequence(['I', 'V'], 0, 'left'), (['I', 'V'], 0))

    def test_history_branch_and_snapshot_isolation(self):
        h = editor.History(limit=3)
        state = {'chords': ['I']}
        h.record(state)
        state['chords'].append('V')
        h.record(state)
        self.assertEqual(h.move(-1), {'chords': ['I']})
        self.assertEqual(h.move(1), state)
        h.move(-1)
        h.record({'chords': ['vi']})
        self.assertIsNone(h.move(1))
        self.assertEqual(h.move(-1), {'chords': ['I']})

    def test_complete_template_survives_short_phrase(self):
        pattern = ['I', 'V', 'vi', 'iii', 'IV', 'I', 'IV', 'V']
        state = dict(gui.DEFAULTS, progression_mode='custom', chord_progression=','.join(pattern))
        model = gui.build_model(state)
        self.assertEqual(model['editable_sequence'], pattern)
        self.assertLess(len(model['chord_sequence']), len(pattern))
        altered, _ = editor.edit_sequence(pattern, 0, 'right')
        state['chord_progression'] = ','.join(altered)
        changed = gui.build_model(state)
        self.assertEqual(changed['chord_sequence'][:2], ['V', 'I'])
        self.assertNotEqual(model['chord_notes'], changed['chord_notes'])


if __name__ == '__main__':
    unittest.main()
