# aiTalyric — 语调 → 旋律动机 → 联合和弦解码

把汉语语调抽象成一小组**动机参数**，再用一个**联合约束优化**同时解出旋律与和声。
核心不是"把音高翻译成音符"，而是"把语调变成目标函数里的一项"。

```bash
pip install -r requirements.txt
cd motive && python selftest.py        # 21 项回归，全绿
python gui.py                          # 调参台：滑杆 + 钢琴卷帘 + 预览播放
mkdir -p out
python run_groove.py --cell-theme sync --harmony free \
    --vsqx out/x.vsqx --ustx out/x.ustx    # 一句 → MIDI + VOCALOID 工程 + OpenUtau 工程
```

流水线：`音频/文本 → 音节边界 + F0 → 动机参数 → 转音与律动展开 → 联合解码 → MIDI / .vsqx / .ustx`

| 阶段 | 文件 | 说明 |
|---|---|---|
| 界面 | `gui.py` | 图形化调参台（tkinter，零安装） |
| 前端 | `align.py` `tts_wav.py` `f0_from_wav.py` `vsqx_pit.py` `f0_from_csv.py` | 三种可互换入口 |
| 抽象 | `prosody.py` | 调性/音域/速度无关的动机参数 |
| 展开 | `realize.py` `rhythm.py` | 一字多音 + 节奏型复用 |
| 解码 | `joint.py` `theory.py` | 旋律与和弦的联合 DP |
| 发展 | `develop.py` | 8 小节结构 + 轮廓守护 |
| 导出 | `export.py` `midi_io.py` | .vsqx / .ustx / .mid |
| 验证 | `selftest.py` `validate_align.py` | 一键回归 |
| 示例 | `examples/ex01..ex08` | 一个例子一个接口，都能跑 |

**想改什么、怎么改**看 [`docs/USAGE.md`](docs/USAGE.md)：五个数据接口的形状、
八个可直接运行的改造示例（换前端 / 改转音规则 / 加节奏型 / 加和弦 / 改权重 /
手改展开结果 / 加导出格式 / 当库用）、命令行速查和常见坑。

```bash
python examples/ex02_style_knobs.py      # 改转音规则，一次看 5 种风格
python examples/ex05_weights.py          # 改目标函数权重，两句对比
python examples/ex06_hand_edit_slots.py  # dump → 手改 → 重新渲染
```

进度与验收记录见 [`ROADMAP.md`](ROADMAP.md)。

## 一句话的形式化

```
E =  Σ_i w_c·((p_i − target_i)/σ)²      旋律贴合语调轮廓（软目标）
   + Σ_i w_t·tone_cost(dir_i, p_i−1, p_i)   声调走向约束（防倒字）
   + Σ_i w_h·strong_i·[p_i ∉ chord]        旋律音与和弦的协和度
   + Σ_i w_m·motion(p_i−1, p_i)            旋律进行（级进优先）
   + Σ_j functional(c_j−1, c_j)            和声功能语法（T/S/D 进行）
```

状态 = (和弦, 音高)，一次 DP 解出全局最优。和弦只在槽位边界可换，
所以状态数只有 |C|×|P| ≈ 300–400，毫秒级。和弦词汇 24 个（含转位/七和弦/副属）。

**为什么必须联合**：两步法（先定旋律再配和弦）里，旋律一冻结，某些音程
就只能硬配；联合解码可以在"轻微牺牲轮廓"与"轻微破坏和声"之间做全局取舍。
实测：总能量 3.05 vs 6.24（两句上 25%–68%）。

## 五层

| 层 | 位置 | 是否 AI |
|---|---|---|
| ① 音频 → 音节边界 + F0 | `align.py`（推荐）/ `f0_from_wav.py`（快） | 部分（TTS 前端） |
| ①' 工程文件 → F0 | `vsqx_pit.py`（VvTalk .vsqx）/ `f0_from_csv.py`（任意） | — |
| ② 逐音节测量 | `prosody.extract_params` | 否（确定性） |
| ③ 动机参数（调性无关） | `motive_params.json` | 否 |
| ④ 联合解码 | `joint.solve_joint` | 否（精确 DP） |
| ⑤ 输出 | `out/motive.mid` + `report.txt` | — |

## 轻量强制对齐（第①层，`align.py`）

问题的形状和旋律解码完全一样：**音素序列是已知的**（拼音给出每个音节的声母/韵母），
所以对齐不是识别，是一个受约束的解码。

```
状态  = sil, ([声母_i]?, 韵母_i) × N, sil
代价  = Σ 状态 特征似然(类别)  +  时长先验
求解  = 精确的分段 DP（每个状态覆盖一段连续帧，O(状态×帧×最长时长)）
```

特征只有四个（对数能量、过零率、周期性、谱通量），做**句内稳健标准化**；
发射概率是手写的类别剖面（stop / affricate / fricative / sonorant / vowel / sil），
没有任何训练数据。它**不会比 MFA 准**——但不需要模型、不需要音素化器、不需要 conda，
而且和能量谷检测有一个本质区别：**音节数由序列固定，它不可能把一个韵母切成两半**。

手写剖面猜不到具体说话人的特征分布，所以在每次解码后用对齐出来的帧
**重估一次各类别的均值/方差**（Viterbi 训练，向先验收缩，18 帧的等效先验），
跑 2 轮收敛。这就是 `--adapt`，默认 2。

```bash
python align.py --wav testdata/tts.wav --text 我想和你一起看海 \
    --tones 3,3,2,3,1,3,4,3 --solve
python validate_align.py        # 两个自动验证
```

### 验证结果（`validate_align.py`）

| 检验 | 结果 |
|---|---|
| A. 合成音频 + 已知边界（42 条边界，6 次随机） | 平均误差 **24.4 ms**，中位 19.6 ms，p90 42.9 ms；30 ms 内 76.2%，60 ms 内 95.2% |
| B. 真实 TTS：与本项目能量法对比 | 两者边界平均相差 40–51 ms；三声形状相关 A 句 0.37 vs 0.57、B 句 −0.50 vs −0.51 |

**诚实的结论**：A 说明机制是对的；**B 说明在真实语音上它还没有赢过能量法**。
差别在 40–50 ms 量级，两句样本不足以下判断。自校准把三声形状相关从 0.31 提到 0.37、
把"一"的时长从 89 ms 修正到 150–169 ms（更合理），但仍不足以宣称更准。

真正的价值目前是结构性的：给出声母/韵母分界、结果不依赖阈值、音节数固定，
以及——它是同一套 DP 思路的第二级实现，后面可以换成音素级、加上 MFA TextGrid 做对照。

## 转音 + 律动（第③④层之间，`realize.py` + `run_groove.py`）

参考风格是"一个音节不是一个音"：语调有起伏、但每个字被唱成 2–3 个连着的音，
整体落在 16 分音符格上、有推拍和摇摆。做法是**先把音节展开成音符槽，再交给原来的联合解码**
（解码器完全不改，只是看到更多音）。

```
音节内部声调形状（sub_contour，默认 5 个时间分位的中位数）
  → 音符数 n：由"起伏幅度 + 是否转折 + 是否长音"三条规则决定
  → 音高：把形状按 n 等距取样（n=3 时就是那个 V 形本身）
  → 时值：按 16 分格 + 模式表切分（tail / even / onset / run）
  → 倚音：音节起点明显低于后续时，可加一个极短的前置音
  → 律动：swing 延迟后半拍八分，push 逐音节推拉 16 分，重音力度分层
  → 和弦只允许在音节边界换（params["chord_at"]）
  → 同一音节内部的音用 2.6 倍 motion 权重强制级进（转音跳进 = 拆和弦，不是转音）
```

### 三条均可改

**1. 参数文件**。`--dump-style style.json` 导出一份带 `_doc` 说明的完整默认值，
改完用 `--style-file style.json` 载入（浅合并，只写想改的键）：

| 键 | 含义 |
|---|---|
| `melisma` | 每音节最多多加几个音（0 = 一音一字） |
| `sub_points` | 采样音节内曲线的点数（3–7，越大展开越细） |
| `note_rules.two_above` | 起伏超过多少 → 给第 2 个音（默认 0.55） |
| `note_rules.three_above` | 起伏超过多少 → 给第 3 个音（默认 0.70） |
| `note_rules.turn_eps` | 中间偏离首尾连线多少算"转折"（默认 0.12） |
| `note_rules.held_beats` | 长过多少拍给跑动（默认 1.75） |
| `note_rules.run_beats` | 长过多少拍给 4 个音（默认 2.50） |
| `patterns` | 每种音数对应的时值比例，可自建新模式名 |
| `grace` | 倚音开关与触发条件 |
| `swing` / `push` | 摇摆量与逐音节推拉 |
| `accents` | 强拍/弱起/弱拍/倚音的力度 |
| `per_syllable` | `{"5": 3, "7": 4}` 逐音节强制音数（1 起） |
| `cell` | 网格粒度（0.25 = 16 分，0.125 = 32 分） |

**2. 逐音节覆盖**：`--override 5:3,7:4`（比改文件快）。

**3. 手改展开结果**。`--dump-slots slots.json` 把展开后的每个音导出来
（含 `midi` 音高、`chord` 和弦、`start`/`dur`/`cells`），改完用
`--from-slots slots.json` 直接渲染——**这就是"展开还可以改"的最终形态：低层完全可控。**

```bash
python run_groove.py                                   # 合成句 A，默认转音（13 音）
python run_groove.py --melisma 3 --swing 0.6 --push 0,0,1,0,-1
python run_groove.py --cell-theme sync                 # 节奏型复用（真律动，22 音）
python run_groove.py --cell-theme sparse --variation-every 3
python run_groove.py --wav testdata/tts.wav --text 我想和你一起看海 \
    --tones 3,3,2,3,1,3,4,3 --melisma 2 --swing 0.5
python run_groove.py --dump-style style.json && python run_groove.py --style-file style.json
python run_groove.py --override 5:3,7:4 --grace
python run_groove.py --dump-slots slots.json && python run_groove.py --from-slots slots.json
```

### 节奏型复用（`rhythm.py`）

转音解决"一字多音"，`--cell-theme` 解决"律动"。节奏型是一个 4 个十六分的
时值比（如 `[2,1,1]`），在一个句子里按 `A B A B A C B A` 这样反复出现，
每 N 个音节加花一次（把最长的部分劈成两半，总时值不变）。

| 型名 | 型库 | 听感 |
|---|---|---|
| `sync` | `[2,1,1] [3,1] [1,1,2] [4]` | 短长短的切分 |
| `dotted` | `[3,1] [2,2] [1,1,1,1]` | 附点八分 + 十六分 |
| `flowing` | `[2,2] [1,1,2] [2,1,1]` | 以八分为主，偶尔推一下 |
| `sparse` | `[4] [3,1] [2,1,1]` | 长音为主，少分割 |

报告会给出复用率、最高频型出现次数和型序列。**注意**：型是 4 个十六分，而实测音节只有
2 个十六分时型会被截断，所以启用节奏型时 `run_groove.py` 会自动把网格从 0.25 细化到 0.125 拍。

效果（同一句合成语调，5 点轮廓 + 默认参数）：

| | 音符数 | 每音节 | 轮廓RMS | 最大音程 | 级进比 |
|---|---|---|---|---|---|
| 单音版 | 8 | 1.00 | 0.86 | 2 | 1.00 |
| 转音版 | 13 | 1.63 | 1.28 | 3 | 0.50 |

逐音节决策（节选）：

```
 5 一  tone=4 shape=[+0.48,+0.29,-0.10,-0.30,-0.46] exc=0.94 -> 2 音  (moving contour)
 6 起  tone=3 shape=[+0.47,+0.22,-0.20,-0.42,-0.56] exc=1.03 -> 3 音  (turning tone (V/^))
 8 海  tone=3 shape=[-0.39,-0.55,-0.70,-0.81,-0.95] exc=0.56 -> 2 音  (moving contour)
```

转音落在声调真正会拐的字上；`--override 5:3` 会把它改写成 `3 音 (manual override)`。

**这一步没有做：**节奏是**先展开再解码**，不是和旋律/和声联合优化。也就是说
"这个字用几个音、占几拍"由规则和声调形状决定，DP 只决定音高与和弦。
真正的联合解码（状态里带节奏位置）是下一个量级的工作。另外真正的"律动"需要
**节奏动机在句内重复**，现在是每个音节各自算，还没有节奏型复用。

## 动机参数（第③层，核心抽象）

调性、音域、速度都不在里面——所以同一个动机可以换调、换音域、换速度复用。

| 字段 | 含义 | 用途 |
|---|---|---|
| `contour[]` | 归一化轮廓，∈[−1,1] | 旋律的软目标 |
| `contour_raw[]` | 未平滑的实测轮廓 | 对照，看平滑吃掉了什么 |
| `beats[]` | 音节时长比例（拍） | 节奏，已与速度解耦 |
| `gestures[]` | 每音节的 `{tone, dir, low, measured_slope, conflict}` | 声调走向约束 + 质量检查 |
| `span_semitones` | 抽象后的音乐跨度 | 语调和旋律的音域不相等，这一步是显式的 |
| `stretch` (k) | 夸张系数 | 念白 ↔ 歌唱的连续旋钮 |

## 旋钮

| 参数 | 作用 | 建议范围 |
|---|---|---|
| `--smooth` | 轮廓一阶低通（吃掉逐音节抖动，保留 2–3 音节趋势） | 1–2 |
| `--stretch` | 音程放大系数 k | 1.0–1.6（>1.6 开始倒字） |
| `--span` | 音乐跨度（半音） | 9–14 |
| `--tonic` / `--mode` | 调与调式（major / minor / penta） | — |
| `w_tone` | 依字行腔的严格度（`--tone-strict` = 3.0） | 1.2–3.0 |
| `w_harmony` | 和声协和度权重 | 0.5–4.0（实测不敏感，见下） |
| `--chord-rate` | 每几个音节换一次和弦 | 2–4 |

## 运行

```bash
cd motive
python run_demo.py                    # 句子 A：我想和你一起看海
python run_demo.py --phrase B --stretch 1.3
python run_demo.py --sweep            # k × w_harmony 的取舍曲线
python run_demo.py --out out_x        # 输出到 out_x/motive.mid + report.txt
```

接真实语调（不需要改代码，只换数据）：

```bash
python make_test_data.py              # 造一份与真实前端同格式的样例
python f0_from_csv.py --syl testdata/syl.csv --f0 testdata/f0.csv --stretch 1.3
```

直接从 VvTalk 生成的 `.vsqx` 起步（不需要 VOCALOID，也不需要渲染音频）：

```bash
python vsqx_pit.py path/to/vvtalk.vsqx --out out_vv
python vsqx_pit.py path/to/vvtalk.vsqx --out out_vv --tones 3,3,2,3,1,3,4,3 --solve
```

`vsqx_pit.py` 读 `<cc><v id="P">` 的 PIT 曲线和 `<note>` 的音节/歌词，
换算成 `(t_ms, f0_hz)`，再交给同一条流水线。往返误差 < 0.02 Hz（纯量化）。

**注意 vvTalk 目前还产不出 vsqx**：需要 conda + python 3.8、`misc/`（仍压在
`misc_7z` 分卷里）、Montreal-Forced-Aligner、PyAudio cp38 wheel。所以默认不走这条路。

真实语调的最短路径（零安装，用系统自带中文 TTS）：

```bash
python tts_wav.py --list                                  # 看可用语音
python tts_wav.py "我想和你一起看海" --out testdata/tts.wav
python f0_from_wav.py --wav testdata/tts.wav --text 我想和你一起看海 \
    --tones 3,3,2,3,1,3,4,3 --solve
```

`tts_wav.py` 调 System.Speech（本机可用 Microsoft Huihui Desktop, zh-CN）。
`f0_from_wav.py` 用 YIN 取 F0、用 DP 按音节切分，输出同样的 CSV 契约。
换真人录音、换句子只改参数。

`f0_from_wav.py` 里有两个必须知道的坑（都已处理，但会影响你接别的数据）：

- **F0 必须是 YIN 而不是自相关 argmax**。自相关在窄带 TTS 人声上会大量出八度错误
  （同一句里 83 Hz 和 514 Hz 并存）。
- **八度修复要锚定全句中位数**，不能用局部中位数：如果尾部一整段都错，局部中位数
  会跟着错，反而把正确的帧改成错的。

CSV 契约：

```
syl.csv : char,tone,dur_ms          （或 char,tone,onset_ms,end_ms）
f0.csv  : t_ms,f0_hz                （清音帧写 0 或 NaN，会被跳过）
```

任何能给出 (time, Hz) 的前端都能接：CosyVoice2 / GPT-SoVITS / IndexTTS、
VvTalk 渲染、真人示读录音。

## 已核对：VvTalk 的真实输出格式

源码就在同目录 `vvTalk/`，以下是从 `reliance/output/vsqxWrite.py`、
`reliance/tyTalk/talker.py`、`reliance/global_vars.py` 直接核实的，不是推测：

| 事实 | 值 | 出处 |
|---|---|---|
| 所有音符压在同一高度 | `<n>65</n>`（65 = F4） | `vsqxWrite.py:83,185` |
| PBS | 17（writer 默认）/ 18（talker 默认），写成 `<cc><v id="S">` | `vsqxWrite.py:83,317` `talker.py:1100` |
| PIT 编码 | `v = semitones / pbs * 8190`，即 `semitones = v * pbs / 8190` | `vsqxWrite.py:199` `talker.py:1355` |
| 绝对音高 | `midi = 65 + PIT * pbs / 8190` | 由上两行推出 |
| 时间基 | `<resolution>480</resolution>`，`<tempo>12000</tempo>`（=120 BPM） | `vsqxWrite.py:284,287` |
| 每 dot 毫秒 | `ms_per_dot = 6000000/tempo/resolution = 1.04167 ms` | `global_vars.py:14-16` |
| 语调来源 | 示读/TTS 朗读 → MFA 强制对齐 → Praat 取 F0 | `reliance/imitation/imitation.py` |

结论：**PIT 是相对量，基准是固定音高 65；不存在"PIT 被限幅削平"的问题**
（除非语调跨度超过 ±17 半音）。所以"从 VvTalk 拿轮廓"这一步没有任何技术风险，
已经实现并跑通。

## 已实测的结果（内置三句，合成语调）

| 配置 | 轮廓RMS | 倒字 | 非和弦音 | 最大音程 | 级进比 | 总能量 |
|---|---|---|---|---|---|---|
| A 逐字忠实（smooth=0） | 1.57 | **3** | 1 | **5** | 0.43 | 10.85 |
| A 平滑 + 联合（默认） | 0.86 | 0 | 1 | 2 | 1.00 | **3.40** |
| A 两步法基线 | 1.18 | 0 | 3 | 4 | 0.86 | 6.29 |
| B 逐字忠实 | 1.62 | **3** | 0 | **7** | 0.29 | 12.10 |
| B 平滑 + 联合 | 1.45 | 0 | 1 | 3 | 0.86 | **6.83** |
| B 两步法基线 | 2.64 | **3** | 1 | 7 | 0.57 | 21.08 |

三条结论：

1. **朴素逐字翻译确实会崩**——不是音高不准，是 3 处倒字 + 最大音程 7 度 +
   级进比 0.29。抽象层和"不是简单翻译"这句话在这里被量化了。
2. **联合解码比两步法省 25–68% 的能量**，代价是轮廓 RMS 略增（0.86 vs 1.18），
   换来非和弦音从 3 降到 1。这正是"联合"买到的东西。
3. **主旋钮不是和声权重，是平滑宽度和夸张系数**。一旦旋律足够级进，和声约束
   几乎自动满足；`w_harmony` 从 0.5 扫到 4.0 结果几乎不变。而 `k` 超过 ~1.6
   就开始以倒字为代价——那是"夸张到唱不出来"的经验边界。

## 真实语调上的第一组结果（Microsoft Huihui, zh-CN, 同一句）

```
字     我  想  和  你  一  起  看  海
F0中位 188 158 200 191 250 193 220 268 Hz
轮廓   -29 -44 -11 +41 +34 -10   0 +13   (×100, 平滑前)
旋律   A3  A3  C4  D4  D4  C4  C4  C4
和弦   vi  ii7 V   I
contourRMS=0.64  倒字=0  非和弦音=1  级进比=0.86
```

两点值得注意：

- **真实语调不是"句末下降"**。焦点词"海"是全句最高点（268 Hz，也是最长音节的
  329 ms），而"想"最低（158 Hz，三声）。这正好说明规则化的语调模型不够用——
  这也是为什么前端必须是真数据。
- 经八度修复后 F0 落在 138–269 Hz（约 11 个半音），是一个合理的汉语语句跨度和
  合理的人声音域，正好对上 `span` 旋钮。

## 下一步（按性价比）

1. **用真机验证导出**。`.vsqx` / `.ustx` 的结构、音符数、歌词、PIT 范围都已自检通过，
   也用本项目的 `vsqx_pit.py` 反向读回过，但**没有在这台机器上用 VOCALOID / OpenUtau
   真的打开过**。第一次打开若报错，最可能是 `vVoice` 的 `id` 要换成你本地声库的 id。
2. **给对齐器做一份真标注**。现在唯一的定量证据是合成音频（中位 19.6 ms），
   真实语音上只有"比能量法差 40–50 ms"这种弱证据。要判断它到底行不行，需要
   20 句左右的人工标注边界（或一份 MFA TextGrid 作参照）。
3. **低音声部 DP**。转位已经真的换了低音，但低音是"和弦属性 → 固定音区"的函数，
   没有做声部进行优化。

进度与验收记录见 [`ROADMAP.md`](ROADMAP.md)。

## 局限（现在就知道的）

- 转音展开（`realize.py`）与节奏型（`rhythm.py`）都是**先验规则**：先展开、再联合解码，
  不是把节奏也放进同一个 DP 一起解。
- 和声语法是手写的 T/S/D 表 + 副属解决规则，没有语料训练，风格只有"古典功能和声"一种。
- 音域 57–76，超出即无解；五声调式的和弦词汇直接复用大调。
- 没有前奏/终止式/段落的句法，只有单句动机 + 8 小节发展。

## 致谢

本项目建立在 **VvTalk** 之上 —— 汉语普通话语调教（talkoid）工具。
本仓库里对 VSQ4 输出格式的每一个细节（音符统一高度 `<n>65</n>`、PBS 写的
`<cc><v id="S">`、PIT 的 `semitones/pbs*8190` 编码、`resolution 480`、
`tempo = beats*100`）都是对着 VvTalk 的
[`reliance/output/vsqxWrite.py`](https://github.com/GalaxieT/VvTalk/blob/master/reliance/output/vsqxWrite.py)
逐一核对的；它"示读 → MFA 强制对齐 → Praat 取 F0 → 写工程文件"的流程，也是本项目
前端设计的直接参照。

- VvTalk: <https://github.com/GalaxieT/VvTalk>
- 前身 TyTalk 算法: <https://github.com/GalaxieT/TyTalk>

其他依赖：`numpy`（数值）、`pypinyin`（声母/韵母与声调）。

**VvTalk 本身不在本仓库内**（`.gitignore` 已排除），需要请自行 clone 到项目根目录：

```bash
git clone https://github.com/GalaxieT/VvTalk.git vvTalk
```

参考曲目《一半一半》只作为风格参照（转音密度、律动感），
曲谱与音频未收入本仓库。
