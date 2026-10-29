# 和声工作台

这是根据公开功能描述独立实现的音乐工具。参考网站请求被当前网络代理以 403 拒绝，
因此没有使用其数据库、源码、界面资源或私有算法；不能视为原软件的兼容实现。
以下规则、指标、坐标和文件格式均为 aiTalyric 自己的定义。

## 启动

Python 3.10+，安装根目录 requirements.txt；桌面需要可用的 tkinter 和显示服务。

```bash
cd motive
python studio.py
# 直接打开保存的工程
python studio.py --project path/to/project.json
# 无显示环境生成完整演示（JSON、MIDI、WAV、CSV）
python studio.py --demo --out out_studio
# 生成带索引的 SQLite 和弦数据库
python studio.py --build-db out_studio/chords.sqlite
```

也可以从原来的 `python gui.py` 中点击「打开和声工作台」。会带入原工具的和弦进行、
和弦时长、速度和调性；工作台是独立编辑会话，不自动回写原旋律调参台。

本次云环境另建了支持中文字体的桌面 Python：

```bash
cd /workspace/aiTalyric/motive
/workspace/.venvs/aitalyric-desktop/bin/python studio.py
```

该环境使用系统 Python 3.13 / Tk 8.6。原 `.venv` 的 Tk 9 在这台机器上无法正确显示中文，
但其无显示测试正常。普通用户不需要复制云机器路径，使用本机带 Tk 和中文字体的 Python 即可。
Linux 推荐 Noto Sans CJK SC，Windows 使用微软雅黑，macOS 使用苹方。

## 功能与使用流程

1. **选和弦**：左侧搜索名称、类型或 ID，也可按根音、38 种类型筛选；每页显示 200 项。
2. **极坐标选择**：单击点选择候选，双击替换当前进行位置。重叠点弹出和弦菜单。
   地图按根音/类型折叠配置，显示优先接近 C3 音区的根位排列；完整转位及开放排列在左侧库中选择。
3. **编辑进行**：选中下方位置，追加、替换、复制、删除、左右移动；每项可设 0.125–64 拍。
4. **查看与聆听**：钢琴条高亮实际 MIDI 音高；可试听选中和弦或整个进行。
5. **分析**：「八项指标」显示当前位置与整段均值，以及粗糙度、离调比例的曲线。
6. **织体**：在上方选择 block/up/down/alberti/waltz/offbeat/bass_chord，点击「应用设置」。
   同处可设置 30–300 BPM、调性、乐器、swing；输入尚未应用时不会改变导出内容。
7. **自定义织体**：编辑 JSON，另起名称后「保存并应用」；支持单独导入/导出 JSON，并随工程持久保存。
8. **推荐与生成**：目标紧张度滑杆用于推荐下一个和弦；「目标紧张曲线」用逗号分隔 0–1 值，
   生成同样数量的和弦。综合粗糙度距离、声部移动、离调音及共同音排序，并尽量避免连续同和弦。
   算法为确定性的逐步选择，不承诺全局最优或严格达到目标值。
9. **平滑声部连接**：保留根音、和弦类型及时长，贪心选择更近的转位和排列；可能改变低音。
10. **整体移调**：每次 ±1 半音，同时更新分析调性，保留音符的实际半音移动；超出支持音区时拒绝操作。
11. **收藏**：收藏具体配置，按「只看收藏」过滤；收藏随工程保存。
12. **撤销重做**：按钮或 Ctrl+Z / Ctrl+Y，保留最近 100 个已应用状态，重新打开工程会清空历史。
13. **工程保存**：JSON 保存进行、时长、调性、速度、乐器、织体、自定义织体与收藏。保存前验证，
    采用临时文件加原子替换；无效工程不能覆盖当前工程。关闭或切换前提示未保存更改。
14. **导出**：MIDI、WAV、逐和弦指标 CSV。WAV 使用独立的合成乐器，无需商业声库。

原旋律工具的 MIDI/VSQX/USTX 导出仍保留；工作台的多音伴奏输出为 MIDI/WAV，未新增歌声工程导出。

## 和弦库的计数含义

库由 38 种三和弦、七和弦、扩展和弦、挂留和弦、四度和弦、音簇类型生成，遍历：

- 12 个根音。
- 每个和弦所有可用低音转位。
- 基础 MIDI 音区 36、48、60、72。
- 4 种封闭/开放排列。

剔除超出 MIDI 0–127 范围的配置，按完整有序 MIDI 音符元组去重，当前得到 **25,889** 项。
这表示不同实际音高配置，**不是 25,889 种不同和弦性质，也不是原网站 12,048 项数据库的复制**。
音高相同但命名不同的配置保留生成顺序靠前的规范名称，搜索不包含所有等音别名。
SQLite 的 `chords` 表提供 `id/symbol/root/quality/inversion/register/spread/notes/roughness`，
对根音/类型和粗糙度建索引。代码内查询使用相同生成器的内存缓存。

## 极坐标定义

- 根音五度圈沿顺时针排列：C、G、D、A、E、B、F#、C#、Ab、Eb、Bb、F。
- 角度为 `((root * 7) % 12) * 2π/12 - π/2`。
- 粗糙度为下述指标 `roughness`；可视半径为 `R * (0.2 + 0.8 * roughness)`，
  保留中心空区以减少点重叠。极坐标图上的刻度对应粗糙度值。
- 黄色箭头是当前进行路径；位置编号与下方表格一致。

## 八项量化指标

均归一化为 0–1。它们是描述性规则，不代表“分数越低越好”，也不是听感的客观测量。
首个和弦没有前驱，四项转换指标显示 0，整段转换均值跳过首项；只有一个和弦时转换均值为 0。

| 键 | 名称 | 本项目定义 |
|---|---|---|
| roughness | 音程粗糙度 | 唯一音级两两取最短音程类，1/2/3/4/5/6 半音分别赋 1/.65/.15/.1/0/.9，再取平均 |
| chromaticity | 离调音比例 | 当前调式以外的唯一音级数 / 当前和弦唯一音级数 |
| voice_motion | 声部移动 | 两方向“每个音到另一和弦最近音”的距离均值，再平均，除 12 并截到 1；不是严格声部匹配 |
| common_tones | 共同音比例 | 与前和弦的音级交集大小 / 并集大小 |
| root_motion | 根音移动 | 两根音的最短半音圆距离 / 6 |
| bass_motion | 低音移动 | 两实际最低音的半音距离 / 12，截到 1 |
| density | 音级密度 | 当前唯一音级数 / 12 |
| register_span | 音域跨度 | 最高音与最低音半音差 / 48，截到 1 |

## 自定义织体格式

```json
{
  "beats": 4,
  "events": [
    {"at": 0, "dur": 0.9, "voice": "bass", "velocity": 85},
    {"at": 1, "dur": 0.8, "voice": "upper", "velocity": 68},
    {"at": 2.5, "dur": 0.4, "voice": 2, "velocity": 76}
  ]
}
```

时间全部以拍为单位。周期长度 `(0,32]`，事件数 1–256；at 在周期内，dur 在 `(0,32]`。
voice 可为 `all` 全部音、`bass` 最低音、`upper` 其余音，或 0–63 的音序号（按音数取模）。
velocity 是 1–127 整数。事件在每个和弦起点重启周期并重复，跨越边界的音符截断。
Swing 只延后恰好处于半拍的事件，偏移为 `swing * 0.5` 拍，事件移出边界则不播放。
最多保留 100 个自定义织体，名称不能覆盖内置织体。

## 音频及边界

- 钢琴、电钢琴、拨弦、马林巴、铺底音色沿用 `inst.py`。
- ffplay 可用时用于试听；Windows 可回退到 winsound。没有音频设备的云机器只能验证 WAV 生成，不能确认实际扬声器输出。
- 音频在后台线程渲染，停止或编辑工程会取消待开始的旧试听；导出的 WAV 渲染不会被取消。
- 为控制内存，单个 WAV 最长 10 分钟；更长的工程请导出 MIDI。
- 进行最多 128 个和弦；工程 JSON 最多 2 MB，织体导入最多 100 KB。
- 24 小时试用、账号、付费系统和商业声库不在这次本地音乐工作台实现范围。

## 接口及测试

```python
import chord_library, harmony_metrics, studio_project

rows = chord_library.catalogue()
chord = chord_library.make_chord(0, 'maj7', inversion=1)
print(harmony_metrics.metrics(chord))
project = studio_project.default_project()
project = studio_project.generate(project, [0.1, 0.3, 0.6, 0.2])
studio_project.save('out_studio/my_project.json', project)
studio_project.export('out_studio/my_project.mid', project, 'midi')
```

```bash
cd motive
python -m unittest discover -p 'test_*.py' -v
python selftest.py
python studio.py --smoke  # 需要显示服务
python gui.py --smoke     # 需要显示服务
```

无 DISPLAY 时 4 个工作台 GUI 集成测试明确跳过；核心测试仍执行。
GUI 集成测试覆盖真实窗口上的极坐标替换、拍数编辑、撤销重做、织体应用、收藏、非法输入和取消旧试听。
