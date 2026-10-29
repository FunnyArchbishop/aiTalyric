import copy
from contextlib import closing
import csv
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
import wave

import chord_library as lib
import harmony_metrics as hm
import studio_project as project
import textures


class LibraryTests(unittest.TestCase):
    def test_catalogue_unique_in_range_and_resolvable(self):
        rows=lib.catalogue()
        self.assertGreater(len(rows),12048)
        self.assertEqual(len(rows),len({tuple(c['notes']) for c in rows}))
        self.assertEqual(len(rows),len({c['id'] for c in rows}))
        for c in rows:
            self.assertEqual(c,lib.resolve(c['id']))
            self.assertTrue(all(0<=n<=127 for n in c['notes']))
            self.assertTrue(0<=lib.polar(c)[1]<=1)

    def test_circle_of_fifths(self):
        c=lib.polar(lib.make_chord(0,'maj'))[0]
        g=lib.polar(lib.make_chord(7,'maj'))[0]
        self.assertAlmostEqual(g-c,math.tau/12)
        self.assertEqual(lib.make_chord(0,'maj',1)['notes'][0]%12,4)

    def test_sqlite_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'chords.sqlite';count=lib.export_database(path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM chords').fetchone()[0],count)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM chords WHERE root=0 AND quality='maj'").fetchone()[0]>0,True)


class MetricTests(unittest.TestCase):
    def test_eight_metrics_and_known_cases(self):
        c=lib.make_chord(0,'maj');cluster=lib.make_chord(0,'cluster')
        m=hm.metrics(c,c)
        self.assertEqual(len(m),8)
        self.assertEqual(m['common_tones'],1)
        self.assertEqual(m['voice_motion'],0)
        self.assertEqual(m['chromaticity'],0)
        self.assertGreater(hm.metrics(cluster)['roughness'],m['roughness'])
        chromatic=hm.metrics(lib.make_chord(1,'maj'))
        self.assertGreater(chromatic['chromaticity'],0)
        self.assertTrue(all(0<=x<=1 for x in chromatic.values()))

    def test_transition_average_excludes_first(self):
        c=lib.make_chord(0,'maj');a=hm.analyze([c,c])
        self.assertEqual(a['average']['common_tones'],1)
        self.assertEqual(hm.analyze([c])['average']['common_tones'],0)


class TextureTests(unittest.TestCase):
    def test_every_builtin_clips_and_has_valid_notes(self):
        c=lib.make_chord(0,'maj')
        for name,p in textures.BUILTINS.items():
            with self.subTest(name=name):
                notes=textures.render([c,c],[2.25,3],p,.5)
                self.assertTrue(notes)
                self.assertTrue(all(n[0]>=0 and n[0]+n[1]<=5.25+1e-9 and n[2] in c['notes'] for n in notes))
                self.assertTrue(all(not (n[0]<2.25<n[0]+n[1]-1e-9) for n in notes))

    def test_custom_event_and_swing(self):
        p=dict(beats=1,events=[dict(at=.5,dur=.5,voice=1,velocity=93)])
        n=textures.render([lib.make_chord(0,'maj')],[2],p,.5)
        self.assertEqual(n[0],(.75,.5,52,93))
        self.assertEqual(n[-1][1],.25)

    def test_reject_invalid_patterns(self):
        for p in [dict(beats=0,events=[]),dict(beats=float('nan'),events=[]),
                  dict(beats=4,events=[dict(at=0,dur=-1,voice='all')]),
                  dict(beats=4,events=[dict(at=0,dur=1,voice='unknown')]),
                  dict(beats=4,events=[dict(at=0,dur=1,voice='all',velocity=128)])]:
            with self.assertRaises(ValueError):textures.validate(p)


class ProjectTests(unittest.TestCase):
    def test_save_load_exports(self):
        p=project.default_project();p['texture']='up';p['favorites']=[p['progression'][0]['chord']]
        p['custom_textures']['custom']=copy.deepcopy(textures.BUILTINS['waltz'])
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);project.save(d/'song.json',p)
            self.assertEqual(project.load(d/'song.json'),p)
            project.export(d/'song.mid',p,'midi');self.assertEqual((d/'song.mid').read_bytes()[:4],b'MThd')
            project.export(d/'song.csv',p,'csv')
            with (d/'song.csv').open(encoding='utf-8-sig') as f:rows=list(csv.reader(f))
            self.assertEqual(len(rows),5);self.assertEqual(len(rows[0]),11)
            p['progression']=p['progression'][:1];p['progression'][0]['beats']=.5
            project.export(d/'song.wav',p,'wav')
            with wave.open(str(d/'song.wav')) as w:
                self.assertGreater(w.getnframes(),0)
                self.assertGreater(max(w.readframes(w.getnframes())),0)

    def test_invalid_project_does_not_replace_saved_file(self):
        p=project.default_project()
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'p.json';project.save(f,p);before=f.read_bytes()
            for key,value in [('tempo',0),('progression',[]),('instrument','bad'),('swing',2),('favorites',['bad'])]:
                invalid=copy.deepcopy(p);invalid[key]=value
                with self.assertRaises(ValueError):project.save(f,invalid)
                self.assertEqual(f.read_bytes(),before)

    def test_transpose_and_generation(self):
        p=project.default_project();shift=project.transpose(p,1)
        for a,b in zip(p['progression'],shift['progression']):
            self.assertEqual([n+1 for n in lib.resolve(a['chord'])['notes']],lib.resolve(b['chord'])['notes'])
        self.assertEqual(project.transpose(shift,-1),p)
        a=project.generate(p,[0,.2,.5,.1]);b=project.generate(p,[0,.2,.5,.1])
        self.assertEqual(a,b);self.assertEqual(len(a['progression']),4)
        with self.assertRaises(ValueError):project.generate(p,[float('nan')])

    def test_smoothing_preserves_harmony_and_durations(self):
        p=project.default_project();smoothed=project.smooth_voicings(p)
        for a,b in zip(p['progression'],smoothed['progression']):
            ca,cb=lib.resolve(a['chord']),lib.resolve(b['chord'])
            self.assertEqual((ca['root'],ca['quality'],a['beats']),(cb['root'],cb['quality'],b['beats']))
        self.assertLessEqual(project.render(smoothed)[2]['average']['voice_motion'],project.render(p)[2]['average']['voice_motion'])

    def test_bridge_from_existing_gui(self):
        import gui
        for mode in ('major','minor','penta'):
            state=dict(gui.DEFAULTS,mode=mode)
            model=gui.build_model(state);p=project.from_model(model,state)
            chords,notes,_=project.render(p)
            self.assertEqual(len(chords),len(model['runs']))
            self.assertAlmostEqual(sum(row['beats'] for row in p['progression']),model['slots'][-1]['start']+model['slots'][-1]['dur'])
            self.assertTrue(notes)


if __name__=='__main__':unittest.main()
