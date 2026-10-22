"""Build a .vsqx that mimics VvTalk's writer, so the VSQX path can be tested.

VvTalk writes: resolution 480, tempo 12000 (=120 BPM), every note at height 65,
PBS=18 as <v id="S">, and PIT as <v id="P"> with value = semitones/pbs*8190.
This script encodes the same synthetic prosody the demo uses and records the
ground-truth Hz so the round trip can be checked.
"""

import csv
import os

import prosody
import run_demo

RESOLUTION = 480
TEMPO = 12000                      # beats*100 per minute
MS_PER_DOT = 6000000.0 / TEMPO / RESOLUTION
PBS = 18
HEIGHT = 65

os.makedirs("testdata", exist_ok=True)
_, syll, durs = run_demo.PHRASES["A"]
chars = [c for c, _ in syll]
tones = [t for _, t in syll]
samples, bounds, tones2 = prosody.synth_prosody(chars, tones, durs)


def dot(ms):
    return int(round(ms / MS_PER_DOT))


notes = "".join(
    f"""      <note>
        <t>{dot(s)}</t>
        <dur>{max(1, dot(e) - dot(s) - 1)}</dur>
        <n>{HEIGHT}</n>
        <v>64</v>
        <y><![CDATA[{ch}]]></y>
        <p><![CDATA[]]></p>
      </note>
"""
    for ch, (s, e) in zip(chars, bounds))

pits, truth, last = [], [], None
for t, v in samples:
    if not any(s <= t < e for (s, e) in bounds):
        continue
    hz = 220.0 * (2.0 ** (v / 12.0))
    midi = 57.0 + v                      # 220 Hz == A3 == MIDI 57
    semis = midi - HEIGHT
    val = int(round(semis / PBS * 8190))
    val = max(-8190, min(8190, val))
    if val == last:
        continue
    last = val
    pits.append(f"""      <cc><t>{dot(t)}</t><v id="P">{val}</v></cc>""")
    truth.append((round(t, 2), round(hz, 4)))

doc = f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<vsq4 xmlns="http://www.yamaha.co.jp/vocaloid/schema/vsq4/">
  <vender><![CDATA[Yamaha corporation]]></vender>
  <version><![CDATA[4.0.0.3]]></version>
  <masterTrack>
    <seqName><![CDATA[fixture]]></seqName>
    <resolution>{RESOLUTION}</resolution>
    <tempo><t>0</t><v>{TEMPO}</v></tempo>
  </masterTrack>
  <vsTrack>
    <tNo>0</tNo>
    <name><![CDATA[Voice]]></name>
    <comment><![CDATA[]]></comment>
    <vsPart>
      <t>0</t><playTime>0</playTime><name><![CDATA[part]]></name>
{''.join(pits)}
      <cc><t>1</t><v id="S">{PBS}</v></cc>
{notes}    </vsPart>
  </vsTrack>
</vsq4>
"""
with open("testdata/vv_fixture.vsqx", "w", encoding="utf-8") as f:
    f.write(doc)
with open("testdata/vv_truth.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["t_ms", "f0_hz"])
    w.writerows(truth)

print("[ok] testdata/vv_fixture.vsqx  (%d PIT points, %d notes)" % (len(truth), len(chars)))
