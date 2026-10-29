"""Real Tk integration checks; skipped explicitly without DISPLAY."""
import copy
import os
from types import SimpleNamespace
import unittest

import chord_library as lib
import studio
import studio_project as project


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','requires display')
class StudioGuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root=tk.Tk();self.app=studio.Studio(self.root);self.root.update()

    def tearDown(self):
        self.app.close(force=True)

    def test_polar_replace_duration_history(self):
        a=self.app;a.filter_root.set('D');a.filter_quality.set('min7');a.filter();self.root.update()
        self.assertEqual(len(a.map_targets),1)
        x,y,c=a.map_targets[0]
        a.map_click(SimpleNamespace(x=x,y=y,x_root=0,y_root=0),replace=True)
        self.assertEqual(a.doc['progression'][0]['chord'],c['id'])
        a.beats.set('2.5');a.set_beats();self.assertEqual(a.doc['progression'][0]['beats'],2.5)
        a.history_move(-1);self.assertEqual(a.doc['progression'][0]['beats'],4)
        a.history_move(1);self.assertEqual(a.doc['progression'][0]['beats'],2.5)

    def test_texture_edits_change_rendered_notes(self):
        a=self.app;before=list(a.notes)
        a.texture_name.set('test');a.texture_editor.delete('1.0','end')
        a.texture_editor.insert('1.0','{"beats":1,"events":[{"at":0,"dur":0.3,"voice":"bass","velocity":90}]}')
        a.save_texture();self.assertEqual(a.doc['texture'],'test');self.assertNotEqual(a.notes,before)
        self.assertEqual(project.validate(a.doc),a.doc)

    def test_generation_favorites_and_invalid_input(self):
        a=self.app;a.tension_curve.set('0.1,0.4,0.6');a.generate()
        self.assertEqual(len(a.doc['progression']),3)
        a.selected=lib.make_chord(0,'maj7');a.favorite()
        a.only_favorites.set(True);a.filter();self.assertEqual(len(a.filtered),1)
        snapshot=copy.deepcopy(a.doc);a.tempo.set('nan');a.guard(a.apply_settings)
        self.assertEqual(a.doc,snapshot);self.assertIn('操作失败',a.status.get())

    def test_stop_cancels_pending_playback(self):
        a=self.app;generation=a.audio_generation;a.stop()
        a.jobs.put(('/tmp/nonexistent-preview.wav',True,None,generation))
        self.root.after_cancel(a.poll_id);a.poll()
        self.assertIsNone(a.process)


if __name__=='__main__':unittest.main()
