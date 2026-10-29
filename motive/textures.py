"""Validated, portable JSON accompaniment patterns; beat units throughout."""
import copy
import json
import math

BUILTINS = {
    'block': dict(beats=4, events=[dict(at=0, dur=3.8, voice='all', velocity=76)]),
    'up': dict(beats=4, events=[dict(at=i*.5, dur=.45, voice=i, velocity=82 if i%2==0 else 65) for i in range(8)]),
    'down': dict(beats=4, events=[dict(at=i*.5, dur=.45, voice=7-i, velocity=75) for i in range(8)]),
    'alberti': dict(beats=4, events=[dict(at=i*.5, dur=.45, voice=[0,2,1,2][i%4], velocity=74) for i in range(8)]),
    'waltz': dict(beats=3, events=[dict(at=0,dur=.9,voice='bass',velocity=85), dict(at=1,dur=.8,voice='upper',velocity=65),dict(at=2,dur=.8,voice='upper',velocity=65)]),
    'offbeat': dict(beats=4, events=[dict(at=i+.5,dur=.4,voice='all',velocity=74) for i in range(4)]),
    'bass_chord': dict(beats=4,events=[dict(at=i,dur=.9,voice='bass' if i%2==0 else 'upper',velocity=78) for i in range(4)]),
}


def validate(pattern):
    if not isinstance(pattern, dict):
        raise ValueError('织体必须为 JSON 对象')
    beats = pattern.get('beats')
    if isinstance(beats,bool) or not isinstance(beats,(int,float)) or not math.isfinite(beats) or not 0 < beats <= 32:
        raise ValueError('beats 必须在 (0, 32]')
    events = pattern.get('events')
    if not isinstance(events,list) or not 1 <= len(events) <= 256:
        raise ValueError('events 需要 1–256 个事件')
    for event in events:
        if not isinstance(event,dict):
            raise ValueError('事件必须为对象')
        for key in ('at','dur'):
            v = event.get(key)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):
                raise ValueError('at/dur 必须为有限数字')
        if not 0 <= event['at'] < beats or not 0 < event['dur'] <= 32:
            raise ValueError('事件起点须在周期内，时长须在 (0,32]')
        voice = event.get('voice')
        if not ((type(voice) is int and 0 <= voice <= 63) or
                (isinstance(voice,str) and voice in ('all','bass','upper'))):
            raise ValueError('voice 使用 0–63 或 all/bass/upper')
        velocity = event.get('velocity',76)
        if type(velocity) is not int or not 1 <= velocity <= 127:
            raise ValueError('velocity 必须为 1–127 整数')
    return copy.deepcopy(pattern)


def render(chords, durations, pattern, swing=0.):
    pattern = validate(pattern)
    if len(chords) != len(durations) or not 0 <= swing <= .75:
        raise ValueError('和弦/时长数量不符或 swing 越界')
    result, start = [], 0.
    for chord, duration in zip(chords,durations):
        if not math.isfinite(duration) or not .125 <= duration <= 64:
            raise ValueError('和弦时长须在 0.125–64 拍')
        notes = chord['notes']; cycle = 0.
        while cycle < duration:
            for event in pattern['events']:
                at = cycle + event['at']
                if abs(at % 1 - .5) < 1e-8:
                    at += swing * .5
                if at >= duration:
                    continue
                voice = event['voice']
                pitches = notes if voice == 'all' else notes[:1] if voice == 'bass' else notes[1:] if voice == 'upper' else [notes[voice % len(notes)]]
                for pitch in pitches:
                    result.append((start+at, min(event['dur'],duration-at),pitch,event.get('velocity',76)))
            cycle += pattern['beats']
        start += duration
    return sorted(result)
