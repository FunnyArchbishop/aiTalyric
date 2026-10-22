"""Export a decoded phrase so it can actually be sung.

Two targets, both fed from the same note list:

  .vsqx  VOCALOID4 (VSQ4 schema).  Every melodic note becomes a real note with
         its own lyric, which is what makes a 转音 a *melodic figure* and not a
         slide: the first note of a syllable carries the character, the melisma
         notes carry that syllable's vowel (VOCALOID needs a lyric per note).
         The optional portamento layer writes PIT control points, so skeleton
         notes and pitch movement stay separate layers.

  .ustx  OpenUtau (YAML), for the DiffSinger path.

Verified against vvTalk/reliance/output/vsqxWrite.py for the VSQ4 skeleton
(vendor/version/vVoiceTable/mixer/masterTrack/vsTrack, resolution 480,
tempo in beats*100 per minute, <cc><v id="S"> for PBS and id="P" for PIT).

    python export.py --image            # write both from phrase A, then read back
"""

import argparse
import os
import xml.etree.ElementTree as ET

RESOLUTION = 480
VOWELS = "aoeiuü"


def vowel_of(final):
    """The syllabic vowel of a pinyin final, for melisma notes."""
    f = (final or "").lower()
    for v in ("a", "o", "e"):
        if v in f:
            return v
    for v in ("i", "u", "ü", "v"):
        if v in f:
            return "i" if v == "v" else v
    return "a"


def lyrics_for(slots, chars, finals):
    """One lyric per note: character on the syllable's first note, else vowel."""
    out = []
    for s in slots:
        i = s["syl"]
        ch = chars[i] if i < len(chars) else "a"
        if s.get("first"):
            out.append(ch)
        else:
            out.append(vowel_of(finals[i] if i < len(finals) else ""))
    return out


def _tick(beat):
    return int(round(beat * RESOLUTION))


def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def write_vsqx(path, notes, tempo=120.0, pbs=17, voice=("BK8H76TAEHXWSKDB", "Luotianyi_CHN_Meng"),
               title="aiTalyric", portamento=0.0, vel=64):
    """notes: [{start, dur, midi, lyric}] in beats."""
    tempo_v = int(round(tempo * 100))
    total = max(_tick(n["start"] + n["dur"]) for n in notes) if notes else RESOLUTION

    body_notes = []
    for n in notes:
        t = _tick(n["start"])
        dur = max(1, _tick(n["dur"]) - 1)
        lyric = (n.get("lyric") or "a").replace("]]>", "")
        body_notes.append(
            "            <note>\n"
            "                <t>%d</t>\n"
            "                <dur>%d</dur>\n"
            "                <n>%d</n>\n"
            "                <v>%d</v>\n"
            "                <y><![CDATA[%s]]></y>\n"
            "                <p><![CDATA[]]></p>\n"
            "                <nStyle><v id=\"accent\">50</v></nStyle>\n"
            "            </note>\n" % (t, dur, int(n["midi"]), vel, lyric))

    cc = ['        <cc><t>1</t><v id="S">%d</v></cc>\n' % pbs]
    if portamento:
        # slide into every note from `portamento` semitones below, then settle
        for n in notes:
            t0 = _tick(n["start"])
            t1 = t0 + max(1, int(portamento * RESOLUTION / 2))
            p0 = int(round(-portamento / float(pbs) * 8190))
            cc.append('        <cc><t>%d</t><v id="P">%d</v></cc>\n' % (max(1, t0), p0))
            cc.append('        <cc><t>%d</t><v id="P">0</v></cc>\n' % t1)

    head = '''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<vsq4 xmlns="http://www.yamaha.co.jp/vocaloid/schema/vsq4/"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:schemaLocation="http://www.yamaha.co.jp/vocaloid/schema/vsq4/ vsq4.xsd">
    <vender><![CDATA[Yamaha corporation]]></vender>
    <version><![CDATA[4.0.0.3]]></version>
    <vVoiceTable>
        <vVoice>
            <bs>4</bs>
            <pc>0</pc>
            <id><![CDATA[%s]]></id>
            <name><![CDATA[%s]]></name>
            <vPrm><bre>0</bre><bri>0</bri><cle>0</cle><gen>0</gen><ope>0</ope></vPrm>
        </vVoice>
    </vVoiceTable>
    <mixer>
        <masterUnit><oDev>0</oDev><rLvl>0</rLvl><vol>0</vol></masterUnit>
        <vsUnit><tNo>0</tNo><iGin>0</iGin><sLvl>-898</sLvl><sEnable>0</sEnable>
            <m>0</m><s>0</s><pan>64</pan><vol>0</vol></vsUnit>
        <monoUnit><iGin>0</iGin><sLvl>-898</sLvl><sEnable>0</sEnable>
            <m>0</m><s>0</s><pan>64</pan><vol>0</vol></monoUnit>
        <stUnit><iGin>0</iGin><m>0</m><s>0</s><vol>-129</vol></stUnit>
    </mixer>
    <masterTrack>
        <seqName><![CDATA[%s]]></seqName>
        <comment><![CDATA[aiTalyric]]></comment>
        <resolution>%d</resolution>
        <preMeasure>0</preMeasure>
        <timeSig><m>0</m><nu>4</nu><de>4</de></timeSig>
        <tempo><t>0</t><v>%d</v></tempo>
    </masterTrack>
    <vsTrack>
        <tNo>0</tNo>
        <name><![CDATA[Voice]]></name>
        <comment><![CDATA[Voice]]></comment>
        <vsPart>
            <t>0</t>
            <playTime>%d</playTime>
            <name><![CDATA[Part]]></name>
            <comment><![CDATA[aiTalyric]]></comment>
            <sPlug><id><![CDATA[ACA9C502-A04B-42b5-B2EB-5CEA36D16FCE]]></id>
                <name><![CDATA[VOCALOID2 Compatible Style]]></name>
                <version><![CDATA[3.0.0.1]]></version></sPlug>
            <pStyle>
                <v id="accent">50</v><v id="bendDep">8</v><v id="bendLen">0</v>
                <v id="decay">50</v><v id="fallPort">0</v><v id="opening">127</v>
                <v id="risePort">0</v>
            </pStyle>
            <singer><t>0</t><bs>4</bs><pc>0</pc></singer>
''' % (voice[0], voice[1], title, RESOLUTION, tempo_v, total)

    tail = '''        </vsPart>
    </vsTrack>
    <monoTrack>
    </monoTrack>
    <stTrack>
    </stTrack>
    <aux>
        <id><![CDATA[AUX_VST_HOST_CHUNK_INFO]]></id>
        <content><![CDATA[VlNDSwAAAAADAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=]]></content>
    </aux>
</vsq4>
'''
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(head)
        f.writelines(cc)
        f.writelines(body_notes)
        f.write(tail)
    return path


def write_ustx(path, notes, tempo=120.0, track_name="Voice", singer="Mai",
               phonemizer="Chinese", renderer="CLASSIC"):
    """OpenUtau project (YAML). Notes in beats, tone = MIDI pitch."""
    total = max(_tick(n["start"] + n["dur"]) for n in notes) if notes else RESOLUTION
    lines = [
        "ustxVersion: 0.6",
        "name: aiTalyric",
        "comment: generated by aiTalyric",
        "output_dir: Vocal",
        "cache_dir: UCache",
        "image: ",
        "resolution: %d" % RESOLUTION,
        "bpm: %g" % tempo,
        "beat_per_bar: 4",
        "beat_unit: 4",
        "tracks:",
        "  - track_name: %s" % track_name,
        "    singer: %s" % singer,
        "    phonemizer: %s" % phonemizer,
        "    renderer: %s" % renderer,
        "    mute: false",
        "    solo: false",
        "    volume: 0.8",
        "voice_parts:",
        "  - name: Part 1",
        "    track_no: 0",
        "    position: 0",
        "    duration: %d" % total,
        "    notes:",
    ]
    for n in notes:
        lines += [
            "      - position: %d" % _tick(n["start"]),
            "        duration: %d" % max(1, _tick(n["dur"])),
            "        tone: %d" % int(n["midi"]),
            '        lyric: "%s"' % (n.get("lyric") or "a"),
        ]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def check_vsqx(path, expect_notes=None):
    """Structural check: well formed, note/lyric counts, cc ranges."""
    root = ET.parse(path).getroot()
    tags = [e.tag.split("}")[-1] for e in root.iter()]
    notes = [e for e in root.iter() if e.tag.endswith("note")]
    lyrics = []
    for n in notes:
        y = [c for c in n if c.tag.endswith("y")]
        lyrics.append((y[0].text or "") if y else "")
    pits = [e for e in root.iter() if e.tag.endswith("cc")]
    pbs = None
    pit_vals = []
    for cc in pits:
        v = [c for c in cc if c.tag.endswith("v")]
        if not v:
            continue
        vid = v[0].get("id")
        val = int(v[0].text)
        if vid == "S":
            pbs = val
        elif vid == "P":
            pit_vals.append(val)
    ok = (len(notes) > 0
          and all(l for l in lyrics)
          and "masterTrack" in tags and "vsTrack" in tags
          and (expect_notes is None or len(notes) == expect_notes))
    return dict(ok=ok, notes=len(notes), lyrics=lyrics, pbs=pbs,
                pit_points=len(pit_vals),
                pit_in_range=all(-8191 <= v <= 8191 for v in pit_vals))


def main():
    import argparse as ap
    import json
    p = ap.ArgumentParser()
    p.add_argument("--image", action="store_true")
    p.add_argument("--out", default="out_export")
    a = p.parse_args()
    if not a.image:
        return
    # a tiny fixed image: the first notes of phrase A, one syllable split in two
    notes = [
        dict(start=0.0, dur=0.5, midi=64, lyric="我"),
        dict(start=0.5, dur=0.5, midi=62, lyric="想"),
        dict(start=1.0, dur=0.25, midi=62, lyric="和"),
        dict(start=1.25, dur=0.25, midi=60, lyric="e"),
        dict(start=1.5, dur=1.0, midi=57, lyric="你"),
    ]
    os.makedirs(a.out, exist_ok=True)
    v = write_vsqx(os.path.join(a.out, "image.vsqx"), notes, portamento=1.5)
    u = write_ustx(os.path.join(a.out, "image.ustx"), notes)
    chk = check_vsqx(v, expect_notes=len(notes))
    print(json.dumps(chk, ensure_ascii=False))
    print("[ok]", v)
    print("[ok]", u)


if __name__ == "__main__":
    main()
