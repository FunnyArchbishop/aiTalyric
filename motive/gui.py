"""gui.py - parameter tuning GUI.  tkinter + numpy, nothing to install.

Left  : every knob that matters (intonation, melisma, groove, harmony, weights)
Right : piano roll + the metrics that tell you what the knobs did
Bottom: preview playback (a rough synth, not VOCALOID) and export

    python gui.py                # open the window
    python gui.py --headless     # print the default render, no window
    python gui.py --smoke        # build the window, render once, write files, exit

Design note: the GUI holds no musical logic.  Every control writes one value
into a plain dict, and `build_model()` runs the exact same pipeline the CLIs
run (run_groove.load_params -> realize.realize -> joint.solve_joint).  So any
knob you find here can be reproduced from the command line.
"""

import argparse
import json
import os
import sys
import wave

import numpy as np

import export
import joint
import midi_io
import realize
import rhythm
import run_demo
import run_groove
import theory

try:
    import winsound
    HAVE_SOUND = True
except ImportError:
    HAVE_SOUND = False


# --------------------------------------------------------------------- state

DEFAULTS = dict(
    phrase="A", wav="", text="", tones="", pinyin="",
    tonic=60, mode="major", span=12.0, stretch=1.0, smooth=1, tempo=120.0,
    melisma=2, pattern="tail", cell_theme="none", variation=4,
    swing=0.0, push="", grace=False, max_repeat=2,
    harmony="fixed", change_cost=1.2, chord_every=2,
    w_contour=1.0, sigma=2.0, w_tone=1.2, w_harmony=1.0, w_motion=0.8,
)

PHRASE_TONES = {k: [t for _, t in v[1]] for k, v in run_demo.PHRASES.items()}


def build_model(state):
    """Run the pipeline for one parameter set.  Pure function: no Tk involved."""
    style = realize.load_style(state.get("style_file") or None)
    style["melisma"] = int(state["melisma"])
    style["swing"] = float(state["swing"])
    style["push"] = state["push"]
    style["chord_every"] = int(state["chord_every"])
    style["grace"]["enabled"] = bool(state["grace"])

    ns = argparse.Namespace(
        phrase=state["phrase"], wav=state["wav"], text=state["text"],
        tones=state["tones"], pinyin=state["pinyin"], adapt=2,
        tempo=float(state["tempo"]), tonic=int(state["tonic"]),
        mode=state["mode"], span=float(state["span"]),
        stretch=float(state["stretch"]), smooth=int(state["smooth"]),
        ref_hz=220.0,
    )
    params = run_groove.load_params(ns, style)

    # refine the grid so a 4-sixteenth cell actually fits, as the CLI does
    if state["cell_theme"] != "none":
        cell = float(style.get("cell", realize.GRID))
        med = sorted(params["beats"])[len(params["beats"]) // 2]
        need = max(sum(c) for c in rhythm.THEMES[state["cell_theme"]]["cells"])
        while med / cell < need and cell > 0.0625:
            cell /= 2.0
        style["cell"] = cell

    slots, chord_at, info = realize.realize(
        params, style=style, pattern=state["pattern"],
        rhythm_theme=state["cell_theme"], variation_every=int(state["variation"]))
    p2 = realize.to_params(params, slots, chord_at)
    if state["harmony"] == "free":
        p2["harmony_free"] = True
        p2["harmony_change_cost"] = float(state["change_cost"])

    W = dict(w_contour=float(state["w_contour"]), sigma=float(state["sigma"]),
             w_tone=float(state["w_tone"]), w_harmony=float(state["w_harmony"]),
             w_motion=float(state["w_motion"]))
    path, ev, world = joint.solve_joint(p2, W, style.get("chord_every", 2),
                                        max_repeat=(int(state["max_repeat"]) or None))

    melody = [(slots[j]["start"], slots[j]["dur"] * 0.95, world["P"][p],
               realize.accent_velocity(slots[j], style)) for j, (_, _, p) in enumerate(path)]
    runs, chord_notes = [], []
    for j, (_, c, _) in enumerate(path):
        if j == 0 or path[j][1] != path[j - 1][1]:
            label = world["vocab"][c][0]
            start = slots[j]["start"]
            end = slots[max(0, j - 1)]["start"] + slots[max(0, j - 1)]["dur"] if j else \
                slots[j]["start"]
            runs.append(dict(start=start, label=label, pcs=world["in_chord"][c],
                             index=c))
    for k, r in enumerate(runs):
        r["end"] = runs[k + 1]["start"] if k + 1 < len(runs) else \
            slots[-1]["start"] + slots[-1]["dur"]
        for q in theory.voicing(world["vocab"][r["index"]], params["tonic"]):
            chord_notes.append((r["start"], (r["end"] - r["start"]) * 0.92, q,
                                70 if q < 52 else 62))

    metrics = dict(notes=len(slots), syllables=len(params["beats"]),
                   chords=len(runs), contour_rms=ev["contour_rms"],
                   tone_violations=ev["tone_violations"],
                   non_chord=ev["harmony_violations"], max_leap=ev["max_leap"],
                   stepwise=ev["stepwise_ratio"], total=ev["total"],
                   max_repeat=ev.get("max_repeat", 1),
                   progression="-".join(r["label"] for r in runs))
    return dict(params=params, slots=slots, info=info, melody=melody,
                chord_notes=chord_notes, runs=runs, metrics=metrics,
                style=style)


# ------------------------------------------------------------ preview audio

def write_preview(path, melody, chords, tempo, sr=22050):
    """A rough additive synth so you can hear the shape without VOCALOID."""
    end = 0.0
    for s, d, p, v in melody + chords:
        end = max(end, s + d)
    n = int((end + 0.4) * sr)
    buf = np.zeros(n + 1)

    def add_note(start, dur, pitch, vel, amp, decay, harmonics):
        a = int(start * sr)
        b = min(n, a + int(max(0.02, dur) * sr))
        if b <= a:
            return
        t = np.arange(b - a) / sr
        f = 440.0 * 2 ** ((pitch - 69) / 12.0)
        env = np.exp(-t * decay) * np.minimum(1.0, t * 120.0)
        sig = np.zeros_like(t)
        for k, w in enumerate(harmonics, start=1):
            if f * k > sr / 2 - 200:
                break
            sig += w * np.sin(2 * np.pi * f * k * t)
        buf[a:b] += sig * env * amp * (vel / 96.0)

    for (s, d, p, v) in chords:
        add_note(s, d, p, v, 0.10, 2.0, [1.0, 0.4, 0.2])
    for (s, d, p, v) in melody:
        add_note(s, d, p, v, 0.22, 3.2, [1.0, 0.5, 0.25, 0.1])

    peak = float(np.max(np.abs(buf))) or 1.0
    pcm = (buf / peak * 0.85 * 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return path


# ------------------------------------------------------------------- tk app

def _font(size=9, bold=False):
    return ("Consolas" if os.name == "nt" else "monospace", size,
            "bold" if bold else "normal")


class App:
    def __init__(self, root, state=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.state = dict(DEFAULTS)
        if state:
            self.state.update(state)
        self.root = root
        root.title("aiTalyric - 调参台")
        root.geometry("1280x800")
        root.minsize(1080, 680)
        self.model = None
        self._after = None
        self._preview = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "out_gui", "preview.wav")

        outer = ttk.Frame(root, padding=6)
        outer.pack(fill="both", expand=True)

        left = ttk.Frame(outer, width=360)
        left.pack(side="left", fill="y", padx=(0, 6))
        left.pack_propagate(False)
        right = ttk.Frame(outer)
        right.pack(side="left", fill="both", expand=True)

        self._build_controls(left)

        self.canvas = tk.Canvas(right, background="#1b1b1f", height=420,
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw())

        self.text = tk.Text(right, height=11, font=_font(9), wrap="none",
                            background="#111114", foreground="#d8d8d8")
        self.text.pack(fill="x", pady=(6, 0))

        self.status = tk.StringVar(value="就绪")
        ttk.Label(root, textvariable=self.status, anchor="w",
                  relief="sunken").pack(fill="x", side="bottom")

        self.rebuild()

    # -- controls ---------------------------------------------------------
    def _build_controls(self, parent):
        from tkinter import ttk
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True)
        self._tabs = {}
        for name in ("语调", "转音", "律动", "和声", "权重", "导出"):
            f = ttk.Frame(nb, padding=6)
            nb.add(f, text=name)
            self._tabs[name] = f

        t = self._tabs["语调"]
        self._combo(t, "句子", "phrase", list(run_demo.PHRASES), row=0)
        self._entry(t, "音频 wav（留空用内置句）", "wav", row=1, width=26)
        self._entry(t, "文本（配合 wav）", "text", row=2, width=26)
        self._entry(t, "声调（逗号分隔）", "tones", row=3, width=26)
        self._spin(t, "主音 MIDI", "tonic", 48, 72, row=4)
        self._combo(t, "调式", "mode", list(theory.SCALES), row=5)
        self._scale(t, "跨度 span (半音)", "span", 6, 20, 0.5, row=6)
        self._scale(t, "夸张 stretch k", "stretch", 0.7, 2.2, 0.05, row=7)
        self._scale(t, "平滑 smooth", "smooth", 0, 3, 1, row=8)
        self._scale(t, "速度 tempo", "tempo", 60, 200, 1, row=9)

        t = self._tabs["转音"]
        self._scale(t, "melisma（多加几个音）", "melisma", 0, 4, 1, row=0)
        self._combo(t, "时值模式", "pattern", list(realize.DEFAULT_STYLE["patterns"]), row=1)
        self._spin(t, "最长同音（0=不限）", "max_repeat", 0, 4, row=2)
        self._check(t, "允许倚音 grace", "grace", row=3)

        t = self._tabs["律动"]
        self._combo(t, "节奏型", "cell_theme", list(rhythm.THEMES), row=0)
        self._spin(t, "每 N 音节加花", "variation", 0, 8, row=1)
        self._scale(t, "swing", "swing", 0.0, 1.0, 0.1, row=2)
        self._entry(t, "push（如 0,1,0,-1）", "push", row=3, width=22)

        t = self._tabs["和声"]
        self._combo(t, "和声节奏", "harmony", ["fixed", "free"], row=0)
        self._scale(t, "换和弦代价", "change_cost", 0.2, 4.0, 0.1, row=1)
        self._spin(t, "每几音节换一次", "chord_every", 1, 8, row=2)

        t = self._tabs["权重"]
        self._scale(t, "w_contour 贴轮廓", "w_contour", 0.0, 4.0, 0.1, row=0)
        self._scale(t, "sigma 容差", "sigma", 0.5, 5.0, 0.1, row=1)
        self._scale(t, "w_tone 防倒字", "w_tone", 0.0, 4.0, 0.1, row=2)
        self._scale(t, "w_harmony 和弦音", "w_harmony", 0.0, 4.0, 0.1, row=3)
        self._scale(t, "w_motion 级进", "w_motion", 0.0, 3.0, 0.1, row=4)

        t = self._tabs["导出"]
        for text, fn in (("播放预览", self.play), ("停止", self.stop),
                         ("写 MIDI", self.export_midi), ("写 .vsqx", self.export_vsqx),
                         ("写 .ustx", self.export_ustx), ("保存预设", self.save_preset),
                         ("载入预设", self.load_preset), ("随机化", self.randomize)):
            from tkinter import ttk as _t
            _t.Button(t, text=text, command=fn).pack(fill="x", pady=2)
        ttk.Label(t, text="预览是合成音，只用来听轮廓/律动；\n真正的声音请导出后用 VOCALOID/OpenUtau。",
                  wraplength=300, foreground="#888").pack(anchor="w", pady=(8, 0))

    def _var(self, key, kind):
        from tkinter import DoubleVar, IntVar, StringVar, BooleanVar
        if kind == "double":
            v = DoubleVar(value=float(self.state[key]))
        elif kind == "int":
            v = IntVar(value=int(self.state[key]))
        elif kind == "bool":
            v = BooleanVar(value=bool(self.state[key]))
        else:
            v = StringVar(value=str(self.state[key]))
        self.state["_var_" + key] = v
        return v

    def _commit(self, key, kind):
        """Write a widget value back into state and schedule a rebuild."""
        v = self.state["_var_" + key].get()
        self.state[key] = float(v) if kind == "double" else (
            int(v) if kind == "int" else (bool(v) if kind == "bool" else str(v)))
        self.schedule()

    def _scale(self, parent, label, key, lo, hi, res, row):
        from tkinter import ttk
        ttk.Label(parent, text=label).grid(row=row * 2, column=0, sticky="w")
        v = self._var(key, "double" if isinstance(res, float) else "int")
        s = ttk.Scale(parent, from_=lo, to=hi, variable=v, orient="horizontal",
                      command=lambda _=None, k=key,
                      kind=("double" if isinstance(res, float) else "int"):
                      self._commit(k, kind))
        s.grid(row=row * 2 + 1, column=0, sticky="ew", pady=(0, 6))
        parent.columnconfigure(0, weight=1)

    def _spin(self, parent, label, key, lo, hi, row):
        from tkinter import ttk
        ttk.Label(parent, text=label).grid(row=row * 2, column=0, sticky="w")
        v = self._var(key, "int")
        sp = ttk.Spinbox(parent, from_=lo, to=hi, textvariable=v, width=8,
                         command=lambda k=key: self._commit(k, "int"))
        sp.bind("<Return>", lambda e, k=key: self._commit(k, "int"))
        sp.grid(row=row * 2 + 1, column=0, sticky="w", pady=(0, 6))

    def _combo(self, parent, label, key, values, row):
        from tkinter import ttk
        ttk.Label(parent, text=label).grid(row=row * 2, column=0, sticky="w")
        v = self._var(key, "str")
        cb = ttk.Combobox(parent, textvariable=v, values=list(values),
                          state="readonly", width=18)
        cb.bind("<<ComboboxSelected>>", lambda e, k=key: self._commit(k, "str"))
        cb.grid(row=row * 2 + 1, column=0, sticky="w", pady=(0, 6))
        if key == "phrase":
            cb.bind("<<ComboboxSelected>>", lambda e: (self._on_phrase(),))

    def _on_phrase(self):
        ph = self.state["phrase"]
        self.state["_var_tones"].set(",".join(str(t) for t in PHRASE_TONES[ph]))
        self.state["_var_text"].set(run_demo.PHRASES[ph][0])
        self.schedule()

    def _entry(self, parent, label, key, row, width=22):
        from tkinter import ttk
        ttk.Label(parent, text=label).grid(row=row * 2, column=0, sticky="w")
        v = self._var(key, "str")
        e = ttk.Entry(parent, textvariable=v, width=width)
        e.bind("<Return>", lambda ev, k=key: self._commit(k, "str"))
        e.grid(row=row * 2 + 1, column=0, sticky="w", pady=(0, 6))

    def _check(self, parent, label, key, row):
        from tkinter import ttk
        v = self._var(key, "bool")
        cb = ttk.Checkbutton(parent, text=label, variable=v,
                             command=lambda k=key: self._commit(k, "bool"))
        cb.grid(row=row * 2, column=0, sticky="w", pady=(0, 6))

    # -- pipeline ---------------------------------------------------------
    def schedule(self):
        if self._after:
            self.root.after_cancel(self._after)
        self._after = self.root.after(120, self.rebuild)

    def rebuild(self):
        self._after = None
        clean = {k: v for k, v in self.state.items() if not k.startswith("_var_")}
        try:
            self.model = build_model(clean)
        except Exception as exc:            # a bad knob value must not kill the app
            self.status.set("生成失败：%s" % exc)
            return
        self.draw()
        self.report()
        m = self.model["metrics"]
        self.status.set("音符 %d / 音节 %d | 和弦 %d | RMS %.2f | 倒字 %d | "
                        "非和弦 %d | %s"
                        % (m["notes"], m["syllables"], m["chords"],
                           m["contour_rms"], m["tone_violations"],
                           m["non_chord"], m["progression"]))

    # -- drawing ----------------------------------------------------------
    def draw(self):
        c = self.canvas
        c.delete("all")
        if not self.model:
            return
        mel = self.model["melody"]
        if not mel:
            return
        w = max(c.winfo_width(), 200)
        lo = min(n[2] for n in mel) - 3
        hi = max(n[2] for n in mel) + 3
        px_b = 58.0
        px_s = 13.0
        top, bottom = 26, 30
        x0, y0 = 18, top

        def X(beat):
            return x0 + beat * px_b

        def Y(pitch):
            return y0 + (hi - pitch) * px_s

        end_beat = max(n[0] + n[1] for n in mel) + 0.5
        for b in range(int(end_beat) + 1):
            col = "#3a3a44" if b % 4 == 0 else "#26262c"
            c.create_line(X(b), y0 - 8, X(b), Y(lo), fill=col)
            if b % 4 == 0:
                c.create_text(X(b) + 3, y0 - 14, text=str(b // 4 + 1),
                              fill="#6a6a78", anchor="w", font=_font(8))
        for p in range(lo, hi + 1):
            if p % 12 == 0:
                c.create_line(x0 - 4, Y(p), X(end_beat), Y(p), fill="#2f2f38")

        for r in self.model["runs"]:
            bx0, bx1 = X(r["start"]), X(r["end"])
            c.create_rectangle(bx0, Y(lo) + 0, bx1, Y(lo) + 16,
                               fill="#2b3a4d", outline="")
            c.create_text((bx0 + bx1) / 2, Y(lo) + 8, text=r["label"],
                          fill="#9dc4ef", font=_font(8))

        for (s, d, p, v) in self.model["chord_notes"]:
            color = "#394a5c" if p < 52 else "#33404f"
            c.create_rectangle(X(s), Y(p) - 5, X(s + d), Y(p) + 5,
                               fill=color, outline="")
        for (s, d, p, v) in mel:
            c.create_rectangle(X(s), Y(p) - 6, X(s + d), Y(p) + 6,
                               fill="#e8c46a", outline="#1b1b1f")
        for j, sl in enumerate(self.model["slots"]):
            if sl.get("first"):
                c.create_text(X(sl["start"]) + 2, Y(mel[j][2]) - 12,
                              text=self.model["params"]["chars"][sl["syl"]] if
                              sl["syl"] < len(self.model["params"]["chars"]) else "",
                              fill="#8fa4b8", anchor="w", font=_font(9))

    def report(self):
        m = self.model["metrics"]
        p = self.model["params"]
        rows = ["%s   %s %s   span=%.0f k=%.2f smooth=%d   melisma=%d %s"
                % ("".join(p["chars"]), theory.note_name(int(self.state["tonic"])),
                   self.state["mode"], float(self.state["span"]),
                   float(self.state["stretch"]), int(self.state["smooth"]),
                   int(self.state["melisma"]), self.state["pattern"]),
                "音符 %d | 每音节 %.2f | 和弦 %d (%s) | 换和弦代价 %.1f"
                % (m["notes"], m["notes"] / max(1, m["syllables"]), m["chords"],
                   self.state["harmony"], float(self.state["change_cost"])),
                "轮廓RMS %.2f | 倒字 %d | 非和弦音 %d | 最大音程 %d | 级进比 %.2f | 最长同音 %d | 总能量 %.2f"
                % (m["contour_rms"], m["tone_violations"], m["non_chord"],
                   m["max_leap"], m["stepwise"], m.get("max_repeat", 1), m["total"]),
                "逐音节：" + " ".join("%d" % i["notes"] for i in self.model["info"]),
                "音高：" + " ".join(theory.note_name(n[2]) for n in self.model["melody"])]
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(rows))
        self.text.configure(state="disabled")

    # -- actions ----------------------------------------------------------
    def _ensure_out(self):
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out_gui")
        os.makedirs(d, exist_ok=True)
        return d

    def play(self):
        if not self.model:
            return
        self.stop()
        path = write_preview(self._preview, self.model["melody"],
                             self.model["chord_notes"],
                             float(self.state["tempo"]))
        if HAVE_SOUND:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            self.status.set("播放预览：%s" % path)
        else:
            self.status.set("没有 winsound，预览已写到 %s" % path)

    def stop(self):
        if HAVE_SOUND:
            winsound.PlaySound(None, winsound.SND_PURGE)

    def _ask(self, suffix, default):
        from tkinter import filedialog
        return filedialog.asksaveasfilename(
            defaultextension=suffix, initialfile=default,
            initialdir=self._ensure_out())

    def _notes(self):
        p = self.model["params"]
        finals = []
        if p.get("chars"):
            import align
            finals = [s["final"] for s in align.parse_syllables("".join(p["chars"]))]
        lyr = export.lyrics_for(self.model["slots"], p["chars"], finals)
        return [dict(start=m[0], dur=m[1], midi=int(m[2]),
                     lyric=lyr[j] if j < len(lyr) else "a")
                for j, m in enumerate(self.model["melody"])]

    def export_midi(self):
        if not self.model:
            return
        path = self._ask(".mid", "aiTalyric.mid")
        if not path:
            return
        midi_io.write_midi(path, float(self.state["tempo"]),
                           [("melody", 73, self.model["melody"]),
                            ("chords", 0, self.model["chord_notes"])])
        self.status.set("已写 %s" % path)

    def export_vsqx(self):
        if not self.model:
            return
        path = self._ask(".vsqx", "aiTalyric.vsqx")
        if not path:
            return
        export.write_vsqx(path, self._notes(), float(self.state["tempo"]),
                          portamento=1.0)
        chk = export.check_vsqx(path, expect_notes=len(self.model["melody"]))
        self.status.set("已写 %s  %s" % (path, chk))

    def export_ustx(self):
        if not self.model:
            return
        path = self._ask(".ustx", "aiTalyric.ustx")
        if not path:
            return
        export.write_ustx(path, self._notes(), float(self.state["tempo"]))
        self.status.set("已写 %s" % path)

    def save_preset(self):
        path = self._ask(".json", "preset.json")
        if not path:
            return
        clean = {k: v for k, v in self.state.items() if not k.startswith("_var_")}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        self.status.set("已存预设 %s" % path)

    def load_preset(self):
        from tkinter import filedialog, messagebox
        path = filedialog.askopenfilename(filetypes=[("json", "*.json")])
        if not path:
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data.items():
            if k in self.state and not k.startswith("_var_"):
                self.state[k] = v
                var = self.state.get("_var_" + k)
                if var is not None:
                    var.set(v)
        self.schedule()
        self.status.set("已载入预设 %s" % path)

    def randomize(self):
        import random
        self.state["melisma"] = random.choice([1, 2, 2, 3])
        self.state["pattern"] = random.choice(list(realize.DEFAULT_STYLE["patterns"]))
        self.state["cell_theme"] = random.choice(
            [k for k in rhythm.THEMES if k != "none"])
        self.state["swing"] = random.choice([0.0, 0.0, 0.3, 0.6])
        self.state["harmony"] = random.choice(["fixed", "free"])
        self.state["stretch"] = random.choice([1.0, 1.2, 1.4])
        for k in ("melisma", "pattern", "cell_theme", "swing", "harmony", "stretch"):
            var = self.state.get("_var_" + k)
            if var is not None:
                var.set(self.state[k])
        self.schedule()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()

    if a.headless:
        model = build_model(dict(DEFAULTS))
        m = model["metrics"]
        print("notes=%d  chords=%d  rms=%.2f  倒字=%d  非和弦=%d  %s"
              % (m["notes"], m["chords"], m["contour_rms"], m["tone_violations"],
                 m["non_chord"], m["progression"]))
        print("melody:", [theory.note_name(n[2]) for n in model["melody"]])
        return

    import tkinter as tk
    root = tk.Tk()
    app = App(root, dict(DEFAULTS))
    if a.smoke:
        root.withdraw()
        root.update()
        out = app._ensure_out()
        app.draw()
        items = len(app.canvas.find_all())
        midi_io.write_midi(os.path.join(out, "smoke.mid"), float(app.state["tempo"]),
                           [("melody", 73, app.model["melody"]),
                            ("chords", 0, app.model["chord_notes"])])
        wav_path = os.path.join(out, "smoke.wav")
        write_preview(wav_path, app.model["melody"], app.model["chord_notes"],
                      float(app.state["tempo"]))
        with wave.open(wav_path) as f:
            frames = f.getnframes()
        export.write_vsqx(os.path.join(out, "smoke.vsqx"), app._notes(),
                          float(app.state["tempo"]))

        # a slider move must flow through widget -> state -> pipeline -> redraw
        before = app.model["metrics"]["notes"]
        app.state["_var_melisma"].set(0)
        app._commit("melisma", "int")
        app.rebuild()
        app.draw()
        after = app.model["metrics"]["notes"]
        items2 = len(app.canvas.find_all())

        print("smoke ok:", app.status.get())
        print("canvas items=%d -> %d   notes %d -> %d (melisma 0)" %
              (items, items2, before, after))
        print("preview wav frames=%d  ->  %s" % (frames, out))
        assert items > 20 and items2 > 20, "piano roll drew nothing"
        assert after < before, "melisma=0 did not reduce the note count"
        assert frames > 1000, "preview wav is empty"
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
