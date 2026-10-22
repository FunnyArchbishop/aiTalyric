"""Text -> WAV via the Windows built-in speech engine (System.Speech).

Zero installs: any voices already registered with SAPI are usable, and a
zh-CN voice gives real Mandarin prosody (including tone realisation) that a
synthetic tone-archetype contour cannot.

    python tts_wav.py "我想和你一起看海" --out testdata/tts.wav
    python tts_wav.py "..." --voice "Microsoft Huihui Desktop" --rate 0
"""

import argparse
import os
import subprocess
import tempfile

PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:VOICE) { $s.SelectVoice($env:VOICE) }
$s.Rate = [int]$env:RATE
$s.SetOutputToWaveFile($env:OUTWAV)
$s.Speak($env:SPKTEXT)
$s.Dispose()
"""


def list_voices():
    ps = ("Add-Type -AssemblyName System.Speech; "
          "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
          ".GetInstalledVoices() | ForEach-Object { "
          "$_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True)
    rows = []
    for line in out.stdout.splitlines():
        if "|" in line:
            name, cul = line.strip().split("|", 1)
            rows.append((name, cul))
    return rows


def synth(text, out_wav, voice=None, rate=0):
    os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False,
                                     encoding="utf-8") as f:
        f.write(PS)
        script = f.name
    env = dict(os.environ, SPKTEXT=text, OUTWAV=os.path.abspath(out_wav),
               RATE=str(rate))
    if voice:
        env["VOICE"] = voice
    else:
        env.pop("VOICE", None)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", script], env=env, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(out_wav):
            raise SystemExit("TTS failed: %s %s" % (r.stdout, r.stderr))
    finally:
        try:
            os.remove(script)
        except OSError:
            pass
    return out_wav


def pick_chinese(voices):
    for name, cul in voices:
        if cul.lower().startswith("zh"):
            return name
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--out", default="testdata/tts.wav")
    ap.add_argument("--voice", default=None, help="default: first zh-* voice")
    ap.add_argument("--rate", type=int, default=0, help="-10..10, 0 is normal")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    voices = list_voices()
    if a.list or not voices:
        for n, c in voices:
            print("%-32s %s" % (n, c))
        if not voices:
            raise SystemExit("no SAPI voices found")
        return
    voice = a.voice or pick_chinese(voices)
    if not voice:
        raise SystemExit("no zh-* voice installed; available: %s" % voices)
    synth(a.text, a.out, voice, a.rate)
    print("[ok] %s  (voice %s, %d bytes)" % (a.out, voice, os.path.getsize(a.out)))


if __name__ == "__main__":
    main()
