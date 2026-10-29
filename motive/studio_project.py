"""Portable harmony studio sessions, validated before replacing active state."""
import copy
import csv
import json
import math
import os
from pathlib import Path
import tempfile

import chord_library as library
import harmony_metrics
import textures


def default_project():
    return dict(version=1, name='Untitled', tempo=100., tonic=0, mode='major', swing=0.,
                instrument='piano', texture='block', custom_textures={}, favorites=[],
                progression=[dict(chord=library.make_chord(r,q)['id'], beats=4.)
                             for r,q in ((0,'maj'),(7,'maj'),(9,'min'),(5,'maj'))])


def validate(doc):
    import inst
    if not isinstance(doc,dict) or doc.get('version') != 1:
        raise ValueError('不支持的工程格式版本')
    p = copy.deepcopy(doc)
    if not isinstance(p.get('name'),str) or len(p['name']) > 200:
        raise ValueError('工程名称过长或无效')
    for key,low,high in (('tempo',30,300),('swing',0,.75)):
        v = p.get(key)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError(f'{key} 须在 {low}–{high}')
    if type(p.get('tonic')) is not int or p['tonic'] not in range(12) or p.get('mode') not in ('major','minor','penta'):
        raise ValueError('无效调性')
    if p.get('instrument') not in inst.INSTRUMENTS:
        raise ValueError('无效乐器')
    custom = p.get('custom_textures')
    if not isinstance(custom,dict) or len(custom) > 100:
        raise ValueError('自定义织体最多 100 个')
    for name,pattern in custom.items():
        if not isinstance(name,str) or not name.strip() or len(name)>80 or name in textures.BUILTINS:
            raise ValueError('自定义织体名称无效或覆盖内置名称')
        textures.validate(pattern)
    if p.get('texture') not in (textures.BUILTINS | custom):
        raise ValueError('所选织体不存在')
    rows = p.get('progression')
    if not isinstance(rows,list) or not 1 <= len(rows) <= 128:
        raise ValueError('进行需要 1–128 个和弦')
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError('无效进行条目')
        library.resolve(row.get('chord'))
        v = row.get('beats')
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not .125 <= v <= 64:
            raise ValueError('每个和弦时长须在 0.125–64 拍')
    favorites = p.get('favorites')
    if not isinstance(favorites,list) or len(favorites)>2000:
        raise ValueError('收藏最多 2000 项')
    for cid in favorites:
        library.resolve(cid)
    return p


def load(path):
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError('工程文件超过 2 MB')
    return validate(json.loads(path.read_text(encoding='utf-8')))


def save(path, doc):
    data = validate(doc)
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.studio-',suffix='.json')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def render(doc):
    p = validate(doc)
    chords = [library.resolve(row['chord']) for row in p['progression']]
    pattern = (textures.BUILTINS | p['custom_textures'])[p['texture']]
    notes = textures.render(chords,[r['beats'] for r in p['progression']],pattern,p['swing'])
    return chords, notes, harmony_metrics.analyze(chords,p['tonic'],p['mode'])


def export(path, doc, kind):
    import inst
    import midi_io
    chords, notes, analysis = render(doc)
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if kind == 'midi':
        midi_io.write_midi(str(path),doc['tempo'],[('Harmony',0,notes)])
    elif kind == 'wav':
        if sum(r['beats'] for r in doc['progression'])*60/doc['tempo'] > 600:
            raise ValueError('WAV export is limited to 10 minutes; use MIDI for longer projects')
        tracks = {'Harmony': [(*n,doc['instrument']) for n in notes]}
        inst.render_tracks(tracks,str(path),doc['tempo'],sr=22050)
    elif kind == 'csv':
        with path.open('w',encoding='utf-8-sig',newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['index','symbol','beats',*harmony_metrics.LABELS])
            for i,(chord,row,m) in enumerate(zip(chords,doc['progression'],analysis['rows'])):
                writer.writerow([i+1,chord['symbol'],row['beats'],*[m[k] for k in harmony_metrics.LABELS]])
    else:
        raise ValueError('未知导出类型')
    return str(path)


def transpose(doc, semitones):
    p = copy.deepcopy(doc)
    for row in p['progression']:
        c = library.resolve(row['chord'])
        # Resolve the absolute root shift, preserving bass/register crossing.
        absolute = c['register'] + c['root'] + semitones
        register = (absolute // 12)*12
        if register not in (36,48,60,72):
            raise ValueError('移调超出支持音区 C2–B5')
        row['chord'] = library.make_chord(absolute%12,c['quality'],c['inversion'],register,c['spread'])['id']
    p['tonic'] = (p['tonic']+semitones)%12
    return validate(p)


def from_model(model, state):
    """Transfer the existing melody tool's chord runs into an editable studio project."""
    import theory
    p = default_project()
    p.update(name='From aiTalyric',tempo=float(state['tempo']),tonic=int(state['tonic'])%12,
             mode=state['mode'],instrument=state.get('instrument','piano'))
    rows=[]
    for run in model['runs']:
        entry=theory.CHORD_VOCAB[state['mode']][run['index']]
        offsets=entry[1];root_offset=offsets[0]
        relative={(n-root_offset)%12 for n in offsets}
        quality=next((q for q,ns in library.QUALITIES.items() if {n%12 for n in ns}==relative),None)
        if quality is None:
            raise ValueError('当前和弦无法映射到工作台词汇：'+entry[0])
        inversion=sorted(relative).index((entry[4]-root_offset)%12)
        chord=library.make_chord((p['tonic']+root_offset)%12,quality,inversion)
        rows.append(dict(chord=chord['id'],beats=run['end']-run['start']))
    p['progression']=rows
    return validate(p)


def generate(doc, targets):
    """Deterministic tension-guided continuation, with a penalty for repetition."""
    if not 1 <= len(targets) <= 32 or any(not math.isfinite(t) or not 0<=t<=1 for t in targets):
        raise ValueError('目标曲线需要 1–32 个 0–1 数值')
    p=copy.deepcopy(doc)
    candidates=[library.make_chord(r,q) for r in range(12) for q in library.QUALITIES]
    previous=None;rows=[]
    for target in targets:
        choices=harmony_metrics.recommend(previous,candidates,p['tonic'],p['mode'],target,limit=12)
        selected=next((c for c in choices if previous is None or (c['root'],c['quality'])!=(previous['root'],previous['quality'])),choices[0])
        rows.append(dict(chord=selected['id'],beats=4.));previous=selected
    p['progression']=rows
    return validate(p)


def smooth_voicings(doc):
    """Keep symbols/qualities, greedily choose nearby bass/upper voice positions."""
    p=copy.deepcopy(doc);previous=None
    for row in p['progression']:
        original=library.resolve(row['chord'])
        if previous:
            options=[c for c in library.catalogue() if c['root']==original['root'] and c['quality']==original['quality']]
            options.append(original)
            def cost(c):
                m=harmony_metrics.metrics(c,previous,p['tonic'],p['mode'])
                return m['voice_motion']+.3*m['bass_motion']+.05*m['register_span']
            chosen=min(options,key=lambda c:(cost(c),c['id']))
            row['chord']=chosen['id'];previous=chosen
        else:previous=original
    return validate(p)
