"""Eight documented, independent descriptive metrics, all normalized to [0, 1]."""
import math
from chord_library import intrinsic

LABELS = {
    'roughness': '音程粗糙度', 'chromaticity': '离调音比例', 'voice_motion': '声部移动',
    'common_tones': '共同音比例', 'root_motion': '根音移动', 'bass_motion': '低音移动',
    'density': '音级密度', 'register_span': '音域跨度',
}


def metrics(chord, previous=None, tonic=0, mode='major'):
    import theory
    notes = chord['notes']
    pcs = set(n % 12 for n in notes)
    scale = {(n+tonic)%12 for n in theory.SCALES[mode]}
    out = dict(roughness=intrinsic(notes), chromaticity=len(pcs-scale)/len(pcs),
               voice_motion=0., common_tones=0., root_motion=0., bass_motion=0.,
               density=len(pcs)/12, register_span=min(1., (max(notes)-min(notes))/48))
    if previous:
        old = previous['notes']; oldpcs = set(n%12 for n in old)
        # Symmetric nearest-voice distance; supports unequal chord cardinalities.
        movement = (sum(min(abs(n-m) for m in old) for n in notes)/len(notes)
                    + sum(min(abs(n-m) for m in notes) for n in old)/len(old))/2
        out.update(voice_motion=min(1.,movement/12), common_tones=len(pcs & oldpcs)/len(pcs | oldpcs),
                   root_motion=min((chord['root']-previous['root'])%12,
                                   (previous['root']-chord['root'])%12)/6,
                   bass_motion=min(1.,abs(min(notes)-min(old))/12))
    return out


def analyze(chords, tonic=0, mode='major'):
    rows = [metrics(c, chords[i-1] if i else None, tonic, mode) for i,c in enumerate(chords)]
    transition = {'voice_motion','common_tones','root_motion','bass_motion'}
    average = {}
    for key in LABELS:
        values = [r[key] for r in (rows[1:] if key in transition else rows)]
        average[key] = sum(values)/len(values) if values else 0.
    return dict(rows=rows, average=average)


def recommend(previous, candidates, tonic=0, mode='major', target=.3, limit=12):
    scored = []
    for chord in candidates:
        m = metrics(chord, previous, tonic, mode)
        score = abs(m['roughness']-target) + .4*m['voice_motion'] + .3*m['chromaticity'] - .1*m['common_tones']
        scored.append((score, chord['id'], chord))
    return [c for _,_,c in sorted(scored)[:limit]]
