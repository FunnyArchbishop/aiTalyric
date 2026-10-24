# 使用与改造手册

这份文档只讲两件事：**怎么跑**，以及**想改的时候改哪里**。
每个"改"都对应 `motive/examples/` 里一个能直接运行的脚本，不要只读说明——跑一遍最快。

```
python examples/ex01_frontend_csv.py     # 换前端
python examples/ex02_style_knobs.py      # 改转音规则
python examples/ex03_add_rhythm_theme.py # 加节奏型
python examples/ex04_add_chord.py        # 加和弦
python examples/ex05_weights.py          # 改目标函数权重
python examples/ex06_hand_edit_slots.py  # 手改展开结果
python examples/ex07_export_and_check.py # 导出并自检
python examples/ex08_library_min.py      # 当库用（12 行跑完整条链）
```

（Windows 控制台中文乱码时先 `chcp 65001`，或直接用 Windows Terminal。）

---

## 一、30 秒上手

```bash
pip install -r requirements.txt
cd motive
python selftest.py                 # 18 项回归，先确认环境是好的
python run_demo.py                 # 最小一条链：合成语调 → 8 音动机 + 和弦
python run_groove.py --cell-theme sync --harmony free \
    --vsqx out/x.vsqx --ustx out/x.ustx
```

> 注意：`run_groove.py --vsqx out/x.vsqx` 里 `out/` 目录要先存在
> （`--out` 会自动建，但导出路径不会）。`mkdir out` 或把导出写进 `--out` 指定的目录。

---

## 一·五、图形界面调参台（`gui.py`）

不想记参数时用它。tkinter + numpy，**零安装**：

```bash
cd motive
python gui.py                # 打开窗口
python gui.py --headless     # 只打印默认渲染结果，不开窗口（脚本/回归用）
python gui.py --smoke        # 建窗口→渲染一次→写 smoke.mid/wav/vsqx→退出（自检用）
```

```
┌─ 参数（6 个标签页）──────────┬─ 钢琴卷帘 ──────────────────────┐
│ 语调  句子/主音/调式/span/k   │ 黄块=旋律，蓝块=和弦，底部=和弦名 │
│ 转音  melisma/时值模式/倚音   │ 每格=一拍，每 4 拍带小节号       │
│ 律动  节奏型/加花/swing/push  ├─ 指标 ──────────────────────────┤
│ 和声  fixed|free/代价/换频    │ 音符数·RMS·倒字·非和弦·最大音程   │
│ 权重  五个 w_* 滑杆           │ 逐音节音数 · 完整音高序列         │
│ 导出  播放/停止/MIDI/vsqx/ustx│                                  │
│       预设存取 · 随机化       │                                  │
└──────────────────────────────┴──────────────────────────────────┘
```

- **改任何滑杆立刻重算**（120 ms 防抖），钢琴卷帘和指标同步刷新。
- **播放预览**用 numpy 合成一段 WAV（正弦叠加 + 衰减包络），只用来听**轮廓和律动**；
  真正的声音请导出 `.vsqx` / `.ustx` 后用 VOCALOID / OpenUtau。
- **保存预设 / 载入预设**：把整套参数存成 JSON，调出满意的组合可以直接复用，
  也能对着它写命令行参数。
- **随机化**：随机换 melisma / 时值模式 / 节奏型 / swing / 和声模式 / k，
  用来快速扫"这个方向值不值得继续"。

> GUI 里没有任何音乐逻辑：每个控件只往一个 dict 里写一个值，
> `build_model()` 跑的就是命令行同一条流水线
> （`run_groove.load_params → realize.realize → joint.solve_joint`）。
> 所以界面里调出来的任何结果，都能用命令复现。自检里也验了这一点：
> 把 melisma 拉到 0，音符数从 13 掉到 8。


---

## 二、五个数据接口

整条链只有五个"形状约定"，改任何一个都不影响其他层。

### A. 前端 → 音节边界 + F0

两种入口，下游完全一样。

**A1. 工程文件**（VvTalk 生成的 `.vsqx`）

```bash
python vsqx_pit.py path/to/vvtalk.vsqx --out out_vv --tones 3,3,2,3,1,3,4,3 --solve
```

**A2. 音频或任意 F0 序列**

```
syl.csv : char,tone,dur_ms          # 或 char,tone,onset_ms,end_ms
f0.csv  : t_ms,f0_hz                # 0 或 NaN = 清音帧，会被跳过
```

```bash
python tts_wav.py "我想和你一起看海" --out testdata/tts.wav     # 系统中文 TTS
python f0_from_wav.py --wav testdata/tts.wav --text 我想和你一起看海 \
    --tones 3,3,2,3,1,3,4,3 --solve                            # 自己取 F0 + 对齐
python f0_from_csv.py --syl syl.csv --f0 f0.csv --solve        # 你自己的 F0
```

代码里最低层的接口是这三个函数：

```python
x, fs = f0_from_wav.read_wav("x.wav")                 # numpy mono, sample rate
bounds, info = align.align(x, fs, "我想看海", [3,3,4,3])  # 音节边界；info 里有全部诊断
times, f0, rms, clar = f0_from_wav.f0_track(x, fs)    # YIN
f0 = f0_from_wav.repair_octaves(times, f0_from_wav.median_filter(f0, 5))
```

**改前端 = 只要能吐出 `(t_ms, f0_hz)` 和音节边界，就没有别的约束。**
`examples/ex01_frontend_csv.py` 直接造了 4 个音节的轮廓喂进去。

### B. 动机参数 `params`（调性/音域/速度都无关）

`prosody.extract_params()` 的返回值，一个普通 dict：

```python
{
  "chars":        ["我","想","和",...],
  "tones":        [2,3,2,3,...],        # 连读变调之后
  "contour":      [0.58,0.42,...],      # 归一化轮廓 ∈[-1,1] —— 旋律的软目标
  "contour_raw":  [...],                # 未平滑，用来对比"平滑吃掉了什么"
  "sub_contour":  [[...5 个点...], ...],# 音节内部形状 —— 决定转音怎么展开
  "beats":        [0.5,0.5,...],        # 时长比例（拍），与速度解耦
  "gestures":     [{"tone":3,"dir":0,"low":True,"measured_slope":-1.1,"conflict":False}, ...],
  "tempo": 120.0,
  "span_semitones": 12.0,               # 抽象后的音乐跨度
  "stretch": 1.0,                       # 夸张系数 k
  "tonic": 60, "mode": "major",         # 后两个由调用方补
}
```

给 `params` 加字段是安全的：所有下游都用 `params.get(...)`。
`examples/ex01` 就是从零构造这四个字段喂进去的。

### C. 音符槽 `slots` + `chord_at`

`realize.realize(params, style=..., rhythm_theme=...)` 的返回值。

```python
slots = [ { "syl": 0, "k": 0, "n": 1, "start_cell": 0, "cells": [2,1,1],
            "start": 0.0, "dur": 0.5, "target": 0.58,
            "first": True, "last": False, "grace": False }, ... ]
chord_at = [True, False, False, ...]     # 这个槽是音节开头吗 → 和弦允许在这里换
```

`slots` 就是"这个词唱成哪几个音、每个音多长、目标音高多少"。
`realize.to_params()` 会把它转成解码器认识的 `params`（`contour/beats/chord_at/motion_w`）。

`examples/ex06_hand_edit_slots.py`：dump → 改 `midi`/`start` → `--from-slots` 重新渲染。

### D. 风格文件 `style.json`

```bash
python run_groove.py --dump-style style.json     # 导出带 _doc 说明的默认值
python run_groove.py --style-file style.json     # 浅合并，只写想改的键
```

| 键 | 含义 | 默认 |
|---|---|---|
| `melisma` | 每音节最多多加几个音 | 2 |
| `sub_points` | 音节内采样点数（3–7） | 5 |
| `note_rules.two_above` | 起伏超过多少 → 第 2 个音 | 0.55 |
| `note_rules.three_above` | 起伏超过多少 → 第 3 个音 | 0.70 |
| `note_rules.turn_eps` | 中间偏离首尾连线多少算转折 | 0.12 |
| `note_rules.held_beats` | 长过多少拍给跑动 | 1.75 |
| `note_rules.run_beats` | 长过多少拍给 4 个音 | 2.50 |
| `patterns` | 每种音数的时值比例（可自建模式名） | tail/even/onset/run |
| `grace` | 倚音开关与触发条件 | 关 |
| `swing` / `push` | 摇摆量 / 逐音节推拉 16 分 | 0 / 空 |
| `accents` | 强拍/弱起/弱拍/摇摆/倚音力度 | 94/88/74/90/66 |
| `per_syllable` | `{"5":3}` 逐音节强制音数（1 起） | 空 |
| `cell` | 网格粒度（0.25=16 分，0.125=32 分） | 0.25 |
| `chord_every` | 每几个音节换和弦 | 2 |

`examples/ex02` 一次跑了 5 种风格并打印每个音节的音数。

### E. 导出音符 `notes`

```python
notes = [dict(start=0.0, dur=0.5, midi=64, lyric="我"),   # 拍为单位
         dict(start=0.5, dur=0.25, midi=62, lyric="o"), ...]
export.write_vsqx("x.vsqx", notes, tempo=96.0, portamento=1.5)  # VOCALOID4
export.write_ustx("x.ustx", notes, tempo=96.0)                  # OpenUtau
export.check_vsqx("x.vsqx", expect_notes=len(notes))            # 结构自检
```

转音在导出时的关键细节：**一个音节多个音时，第一个音带汉字、后续音带该音节的韵母**
（VOCALOID 每个音符都要有歌词，用韵母才能保持同一个字的口型）。
`export.lyrics_for()` 就是干这个的，`examples/ex07` 有完整演示。

---

## 三、想改什么，改哪里

### 1. 换前端（TTS / 录音 / 自己的模型）

改**数据**，不改代码。只要能产出 `f0.csv` + `syl.csv`，或者直接调用
`prosody.extract_params(chars, tones, durs, samples, bounds, ...)`。
→ `examples/ex01_frontend_csv.py`

### 2. 改转音规则（一个字给几个音）

- 只调数值：`style.json` 里的 `note_rules`（见上表）。
- 改判定逻辑：`realize.notes_for(profile, dur_beats, style)`，返回 `(n, why, exc, turn)`。
  想加规则（比如"每个乐句最后一个字一定给 3 个音"）就在这里加分支，
  返回新的 `n` 和一句 `why`（`why` 会出现在报告的"为什么"那一列）。
→ `examples/ex02_style_knobs.py`

### 3. 加一个节奏型

`rhythm.THEMES` 里加一条，运行时就生效：

```python
import rhythm
rhythm.THEMES["threes"] = dict(
    cells=[[2, 1, 1], [1, 1, 1, 1], [3, 1], [1, 2, 1]],  # 每个 cell 之和 = 4（一拍）
    pattern="A B A C",                                    # 字母循环覆盖音节
    note="说明，出现在文档里",
)
# 然后 run_groove.py --cell-theme threes 就能用
```

注意：型是 4 个十六分，音节跨度不足时会被截断——`run_groove.py` 会自动把
`cell` 细化到 0.125 拍让它装得下，并打印 `[grid] cell ...` 提示。
→ `examples/ex03_add_rhythm_theme.py`

### 4. 加和弦（转位 / 七和弦 / 副属 / 借和弦）

`theory.CHORD_VOCAB[mode]` 加一个元组：

```python
(label, 音级偏移, 功能, 解决目标或 None, 低音偏移, 习惯性代价)
("bVII", (10, 2, 5),      "S", None, 10, 0.35)   # 借和弦
("V/vi", (4, 8, 11),      "D", 9,    4,  0.15)   # 副属：必须解决到 vi(9)
("I6",   (0, 4, 7),       "T", None, 4,  0.15)   # 第一转位：低音换成三音
```

- 功能用 `T/S/D`，走向代价在 `theory.ROLE_COST`。
- 有"解决目标"的和弦（副属）会强制下一步到该根音，代价写在 `joint.build_world()` 里。
- 低音偏移决定 `--vsqx` 的低音声部（`theory.voicing()`）。
→ `examples/ex04_add_chord.py`（含"扩词汇不会让最优解变差"的验证）

### 5. 改目标函数权重

```python
W = dict(w_contour=1.0, sigma=2.0, w_tone=1.2, w_harmony=1.0, w_motion=0.8)
joint.solve_joint(params, W, chord_rate)
```

| 权重 | 拉向 | 调大以后 |
|---|---|---|
| `w_contour` / `sigma` | 贴语调轮廓 | 更像念白、倒字变多 |
| `w_tone` | 声调走向 | 严格依字行腔、轮廓被压平 |
| `w_harmony` | 落在和弦音上 | 更"顺"，旋律自由变少 |
| `w_motion` | 级进 | 大跳消失 |

实测：`w_tone` 在"我想和你一起看海"上完全不敏感（旋律本来就下行），
在"你有没有想过为什么"上放松到 0.2 立刻出现 3 处倒字、换来 RMS 1.45→1.02。
**所以别拿一句的音色去调权重。**
→ `examples/ex05_weights.py`

### 6. 手改展开结果

```bash
python run_groove.py --dump-slots slots.json --cell-theme sync
# 改 slots.json 里任意 midi / start / dur / cells
python run_groove.py --from-slots slots.json
```

`slots.json` 每行含 `syl / note / char / start / dur / start_cell / cells / target / grace / midi / chord`。
→ `examples/ex06_hand_edit_slots.py`

### 7. 加一个导出格式

`export.py` 里加一对 `write_xxx(path, notes, tempo, ...)` + `check_xxx(path)`，
遵守"notes = [{start,dur,midi,lyric}]（拍为单位）"这个形状即可。
`run_groove.py` 里加一个 `--xxx PATH` 参数，3 行接上。

### 8. 当库用

```python
params, _ = run_demo.build(a)                       # 或 prosody.extract_params(...)
slots, chord_at, info = realize.realize(params, rhythm_theme="sync")
p2 = realize.to_params(params, slots, chord_at)
path, ev, world = joint.solve_joint(p2, W, 2)
```

`world["P"][p]` 是 MIDI 音高，`world["vocab"][c][0]` 是和弦名。
→ `examples/ex08_library_min.py`（12 行跑完整条链并写 MIDI）

---

## 四、命令行速查

### `run_groove.py`（主力：展开 + 律动 + 解码 + 导出）

```
--phrase {A,B,C}            内置句子      --wav/--text/--tones/--pinyin   真实音频
--tonic 60  --mode {major,minor,penta}  --span 12  --stretch 1.0  --smooth 1
--melisma 2                最多多加几个音   --style {tail,even,onset,run}
--swing 0.5               延迟后半拍八分   --push 0,1,0,-1
--cell-theme {none,sync,dotted,flowing,sparse}   --variation-every 4
--harmony {fixed,free}     --change-cost 1.2
--max-repeat 2            同一音最多连续几个（0=不限）
--chord-every 2            --grace          --override 5:3,7:4
--style-file s.json        --dump-style s.json
--dump-slots x.json        --from-slots x.json
--vsqx x.vsqx  --ustx x.ustx  --portamento 1.5
--out out_groove           输出目录（report.txt / params_groove.json / groove.mid）
```

### `develop.py`（一句 → 8 小节）

```
--bars 8  --modulate 2  --min-corr 0.8  --cell-theme sync  --variation-every 4
（其余同 run_groove 的前端参数）
```

### `align.py` / `validate_align.py`

```
--wav --text --tones --pinyin --adapt 2 --solve    # 对齐 + 出动机
python validate_align.py                            # 合成真值 + 真实语音两组检查
```

### `run_demo.py`（对照实验）

```
--phrase {A,B,C} --stretch 1.0 --sweep --tone-strict
```

### 同音反复是怎么处理的（`--max-repeat`）

同一个音连着弹四五次听起来像卡键。原因是两个真 bug，都已修：

1. **候选音域写死 57–76**，低音目标被夹在底线上 → 所有想往下走的音都变成同一个最低音。
   现在音域由目标轮廓推导（`min(target)-3 .. max(target)+3`，再夹到 40–88）。
2. **转音的多个音会塌到同一个音高**：音节内部轮廓本来就平（一声或过度平滑），
   采样 4 次得到 4 个相同的目标；而和声项又把它们全拽到和弦音上。
   现在会先按声调原型补上运动（二声上行 / 四声下行 / 一三声回转），
   并把目标吸附到**互不相同**的音级；转音内部的非骨架音只按 0.35 权重计和声协和，
   它们本来就可以是非和弦音。

剩下的长同音由 `--max-repeat` 做一次**局部修正**：先正常解码，找出超过阈值的同音段，
只对那几拍的那个音高加罚再解一次——目标函数本身不动，所以不会伤到声调约束。

| `--max-repeat` | 同音最长 | 倒字（A 句） | 总能量 |
|---|---|---|---|
| 不限 | 3 | 0 | 5.10 |
| 2（默认） | 2 | 1 | 7.04 |
| 1 | 2 | 2 | 7.42 |

**这是一个显式的取舍：不想要重复，就得让一点轮廓/声调。** 要不要这么换，由你决定。

---

## 五、配方

| 想要 | 这么调 |
|---|---|
| 更念白、更像说话 | `--stretch 0.9 --melisma 0 --smooth 0` |
| 更歌唱、音程更大 | `--stretch 1.3~1.6`（超过 1.6 开始倒字） |
| 一字多音的转音 | `--melisma 2~3`，或 `--override 5:3,7:4` 指定某个字 |
| 强律动 | `--cell-theme sync --swing 0.5 --push 0,0,1,0,-1` |
| 和声更骚 | `--harmony free --change-cost 0.8`（越小换得越勤） |
| 严格依字行腔 | `examples/ex05` 里 `w_tone=3.0`，或 `run_demo.py --tone-strict` |
| 不要同音反复 | `--max-repeat 1`（默认 2；代价见下） |
| 换调 | `--tonic 62`（D）`--mode minor` |
| 更长的结构 | `develop.py --bars 16 --modulate 3` |
| 拿去唱 | `--vsqx x.vsqx --portamento 1.0`，或 `--ustx x.ustx` 进 OpenUtau |

---

## 六、常见坑

1. **导出目录要先存在**：`--out` 会自动建目录，`--vsqx out/x.vsqx` 不会。
2. **`--override` / `per_syllable` 用 1 起的序号**，和报告里的"序号"列一致。
3. **节奏型被截断**：型是 4 个十六分，若音节只有 2 个十六分，会退化成单个音。
   `run_groove.py` 启用 `--cell-theme` 时会自动细化网格并打印 `[grid]` 提示；
   自己写代码调用 `realize` 时要手动把 `style["cell"]` 设成 0.125。
4. **`chord_at` 与 `harmony_free`**：给了 `chord_at` 就按它换；`harmony_free=True` 会忽略它，
   改成"每个音都可能换，由 `harmony_change_cost` 决定节奏"。
5. **VSQX 的 PIT 是相对量**，基准是音符自己的 `<n>`；PBS 默认 17。
   换声库时 `vVoice` 的 `id` 要换成你本地声库的 id。
6. **`penta` 调式的和弦词汇直接复用大调**，不是真正的五声和声，别当成结论用。
7. **真实语音上的对齐还没有人工标注验证**，只有合成音频的定量结论（中位 19.6 ms）。
