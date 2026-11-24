# LyraForge 人声转谱质量与音乐编曲专项评测报告

> **评测日期**：2026-11-24（Round 26 · 人声转谱专项优化）  
> **运行环境**：macOS Apple Silicon，独立隔离工具链：`ffmpeg 9.0`、`demucs 4.0.1`（`htdemucs`）、`basic-pitch 0.4.0`、`dettato 2.0.0`、`swift-f0 0.3.0` 与内置 `builtin-mono`  
> **仓库洁净边界**：所有外部测试音频、中间伴奏分轨与 `.wav`/`.mid` 试听对照样本均存放于本地工作目录外；**本仓库未提交任何受版权保护曲目或基准音频资产**。

---

## 1. 测试素材与合法授权声明（10 类基准 + 真实 CC0 器乐）

评测集完整覆盖任务要求的 7 类场景、人声人工伪影压力集、基于真实人类演唱（`CC-BY-4.0`）的多轨混音以及无真值真实 CC0 器乐对照：

| 类别 ID | 场景描述 | 来源与授权 | 音高范围 / 特征 | 真实参考（GT） |
|---|---|---|---|---|
| `cat1_male_pop` | 清晰男声流行（G2–G4） | 自编合成 WAV+MIDI | 含 G2（98 Hz）低音、滑音起点、颤音与轻伴奏 | `full_gt.mid` / `vocal_gt.mid` |
| `cat2_female_pop` | 清晰女声流行（F4–D6） | 自编合成 WAV+MIDI | 含越出风物诗琴上界（A5–D6）高音、吉他与贝斯 | `full_gt.mid` / `vocal_gt.mid` |
| `cat3_complex_mix` | 复杂人声与响亮高音伴奏混音 | 自编合成 WAV+MIDI | 人声嵌套在高于人声的 G5–C6 主导合成器/钢琴/鼓声中 | `full_gt.mid` / `vocal_gt.mid` |
| `cat4_jpop_anime` | 172 BPM 日语 / 二次元快节奏曲目 | 自编合成 WAV+MIDI | 连续快速同音字重复、A5–C6 高音、半音经过音（D#5）与 `sus2` 吉他 | `full_gt.mid` / `vocal_gt.mid` |
| `cat5_solo_piano_guitar` | 纯钢琴与吉他二重奏（无人声） | 自编合成 WAV+MIDI | 守卫 `direct + classic` 纯器乐基线与无人声时流水线防破坏 | `full_gt.mid` |
| `cat6_dense_band` | 高密度多乐器伴奏 + 领唱 | 自编合成 WAV+MIDI | 密集和弦切分 + 打击乐，检验主旋律权重移调与防冲突丢音 | `full_gt.mid` / `vocal_gt.mid` |
| `cat7_full_song_structure` | 完整结构曲目（前奏/主歌/副歌/间奏/尾奏） | 自编合成 WAV+MIDI | 检验前奏保留、人声进出避让与 `>=350ms` 间奏自动交接 | `full_gt.mid` / `vocal_gt.mid` |
| `cat8_vocal_artifacts` | 人声专项伪影压力集 | 自编合成 WAV+MIDI | 隔离颤音、滑音、65ms 装饰音、4 次同音重击、经过音、强谐波八度陷阱、低响度气声与渗漏 | `vocal_gt.mid` |
| `cat9_real_human_vocal_mix` | **真实人类独唱琶音 + 乐队混音** | **VocalSet (`CC-BY-4.0`, Zenodo 1442513, `singer_9`)** + 伴奏 | 真实专业人声抖音/呼吸/颤音混入钢琴/贝斯/弦乐/鼓组 | `full_gt.mid` / `vocal_gt.mid` |
| `cat10_real_human_scale_mix` | **真实人类音阶（含半音转换）+ 乐队混音** | **VocalSet (`CC-BY-4.0`, Zenodo 1442513, `singer_12`)** + 伴奏 | 真实人类上下行音阶（含 F#/C#）+ 乐队伴奏 | `full_gt.mid` / `vocal_gt.mid` |
| `real_cc0_instrumental` | 真实无真值器乐录混（18s 片段） | **Internet Archive (`CC0 1.0`, GRN Music - Languor 12)** | 无 MIDI 真值，**严格只计非准确率代理指标并输出 `.wav`/`.mid` 供人耳试听** | 无（严禁充当准确率） |

> 评测严格遵守**指标分层原则**：仅在拥有参考曲谱的曲目（`cat1–cat10`）上计算转谱 Precision/Recall/F1、八度误差与起音误差；对无参考真值的 `real_cc0_instrumental` 仅标注转录音符数、可演奏占比（相对转录结果）及试听文件路径，绝不把编曲可演奏分当作转谱准确率。

---

## 2. 外部工具参数实测、Demucs 混音核查与跨设备发现

1. **CLI 参数与版本实测验证**：
   - `basic-pitch 0.4.0`：`basic_pitch.predict` 实际接受 `--minimum-note-length`（单位：**毫秒**，默认 `127.70 ms`）、`--minimum-frequency`、`--maximum-frequency`、`--onset-threshold`、`--frame-threshold`。Round 26 前 `_vocal_options()` 被锁死在 `110–1400 Hz` 且未转发 `min_note_ms`；现已按人声音域预设（`auto 73–1760 Hz` / `male 65–700 Hz` / `female 155–1760 Hz`）准确映射。
   - `dettato 2.0.0`：仅接受 `-o <dir>` 与 `--device`；实机在 macOS Apple Silicon 上以 `--device mps` 运行触发 **MPS Tensor float64 崩溃**（而旧版 `resolve_device()` 在检测到 MPS 时默认选用 `mps`）。现 `resolve_device()` 与 `toolchain/runtime.py` 自动路由将 `dettato` 限定为 `cuda` 或 `cpu`（已于 Apple Silicon 端到端实跑通过）。
   - `builtin-mono`（纯 Python YIN）与 `swift-f0 0.3.0`：均明确标记 `polyphonic: False`，仅支持单音主旋律或分离后的干人声。
2. **Demucs 4.0.1 分离、混音与回退真实表现**：
   - `DemucsSeparator` 原先对 `bass.wav` 与 `other.wav` 分别加载后叠加存在削波风险；现改用独立 `demucs` 环境内 **raw float32 `bass + other` 先求和后 0.98 峰值限幅**，写出 `no_drums.wav` 与 `demucs_meta.json`。
   - 实测发现重要边界：在真实人类演唱混音（`cat9`、`cat10`）中，`htdemucs` 能准确将真唱人声分至 `vocals.wav`；而在纯合成声学干人声（`cat1–cat4`）上，`htdemucs` 会把非真人泛音大量路由至 `other.wav`，使 `vocals.wav` 接近静音（`split_lead_swift` 如实报错 `[NO_PLAYABLE_NOTES]`，而 `split_full_swift_dt` 会优雅忽略空人声轨并从伴奏恢复 `FullF1 = 0.889–1.000`）。
   - 若回退至 `no_vocals.wav`（实际仍包含鼓组），系统会在产物与前端显式标记 `drums_removed: false` 与「伴奏含鼓声」警告；当 `vocal_split_full` / `vocal_split_accomp` 缺少 `dettato` 与 `basic-pitch` 时，`PipelineInfo.available = False`（拒绝静默退化为单音），仅在用户主动选配低资源模式时以 `degraded_mode: true` 运行。

---

## 3. 候选专业人声 F0 提取模型实测对照

在同一套 8 类干人声与 **Demucs 分离真唱人声** 评测集（含 `cat1_dry_male`、`cat2_dry_female`、`cat4_dry_jpop`、`cat8_artifacts`、`cat9_real_human_{dry,demucs_vocals}`、`cat10_real_scale_{dry,demucs_vocals}`，精确匹配容差 75ms）上对比现有基线与候选方案：

| 方案 | 平均 F1 | 平均八度误差率 | `cat9` Demucs 真唱 F1 | `cat10` Demucs 真唱 F1 | `cat8` F1 / 重击(`4`) / 气声误报 | 平均 RTF（越低越快） | 代码 / 权重许可与体积 | 结论 |
|---|---:|---:|---:|---:|---|---:|---|---|
| **`swift-f0 (0.3.0, +segment_notes)`** | **0.8416** | **0.0000** | 0.4545 *(整轨优化后 0.4762)* | **0.9412** | **0.8571** / **4/4** / **0** | **0.0063** (~159x CPU) | **MIT**（`model.onnx` **0.13 MB**；隔离环境约 **104.2 MB**），双平台 | **✅ 已采纳为可选人声引擎** |
| `dettato (2.0.0, cpu)` | 0.8394 | 0.0000 | 0.6000 | 0.7027 | 1.0000 / 4/4 / 0 | 4.1369 | Apache-2.0（部分训练数据非商用）；环境约 718 MB | 保留作多音伴奏首选 |
| `basic-pitch (0.4.0, cur 110-1400)` | 0.6341 | 0.0000 | 0.0476 | 0.7027 | 0.8235 / 4/4 / 0 | 0.4853 | Apache-2.0；环境约 397.5 MB | 保留并修复参数转发与宽音域 |
| `builtin-mono` (YIN) | 0.5763 | 0.0000 | 0.0000 | 0.4583 | 0.8000 / 4/4 / 0 | 0.1089 | 项目内置（GPL-3.0） | 保留作纯离线单音低资源兜底 |
| `librosa.pyin` | 0.5002 | 0.0000 | 0.0000 | 0.6667 | 0.6667 / — / 0 | 0.3863 | ISC | ❌ 速度慢且真唱混响段易碎片化 |
| `torchcrepe (tiny, viterbi)` | 0.4968 | 0.0000 | 0.0294 | 0.6818 | 0.6531 / — / 0 | 0.2429 | MIT | ❌ 帧级直出缺少音乐 DP 切分，碎片严重 |
| `torchfcpe (cpu)` | 0.4455 | 0.0000 | 0.0571 | 0.5778 | 0.5517 / — / 0 | 0.0334 | MIT | ❌ 抖动碎片多（`cat8` 颤音碎片 16 个） |
| `mlx-rmvpe` | 0.4248 | 0.0089 | 0.0303 | 0.5778 | 0.5714 / — / 0 | 0.0362 | 代码 MIT / 仅 macOS Apple Silicon + 外部 RMVPE 权重 | ❌ 不兼容 Windows CUDA/CPU 且无 DP 切分 |

> 关键技术说明：本仓库通过向独立 `swift-f0` 进程直接传入 **16 kHz 单声道 WAV**（标准库 `wave` 读取），绕开了 `soxr`（LGPL）传递依赖，使 `swift-f0` 工具链维持 **100% MIT / BSD 宽松许可**，且不随 PyInstaller 安装包分发，仅由用户在设置中按需安装。

---

## 4. BEFORE vs AFTER 四层对照结果

### Layer A & Layer B（真实人声混音与典型合成全流程对照：原始转录 + 人声清理）

下表在 **相同音频输入与参考真值** 下对比 Round 26 前（BEFORE）与后（AFTER）端到端流水线输出（已保持 `direct + classic` 基线不变）：

| 测试曲目 | 流水线配置 | BEFORE `Full F1` / `Vocal F1` | AFTER `Full F1` / `Vocal F1` | AFTER `Vocal` 八度误差 / 平均起音误差 | BEFORE → AFTER `Vocal` 编曲主旋律精确召回 (`21键`) |
|---|---|---|---|---|---|
| `cat9_real_human_vocal_mix` *(VocalSet `singer_9` 真唱 + 乐队)* | `direct_bp_classic`（基线） | 0.544 / 0.071 | 0.544 / 0.071 | 0.0 / 15.67 ms | 0.2857 → 0.2857 *(Cliffs 33)* |
| `cat9_real_human_vocal_mix` | `vocal_split_lead` (`basic-pitch`) | 0.064 / 0.061 | 0.028 / 0.049 | 0.0 / 34.67 ms | 0.0000 → 0.0000 |
| `cat9_real_human_vocal_mix` | **`vocal_split_lead` (`swift-f0`)** | *（无此引擎）* | **0.196 / 0.476** | **0.0 / 8.67 ms** | **0.5714** *(Cliffs 0)* |
| `cat9_real_human_vocal_mix` | **`vocal_split_full` (`swift-f0 + dettato`)** | *（BP+DT: 0.639 / 0.060）* | **0.854 / 0.231** | **0.0 / 7.86 ms** | BP+DT **0.0000** → Swift+DT **0.5714** *(Cliffs 0)* |
| `cat10_real_human_scale_mix` *(VocalSet `singer_12` 真唱 + 乐队)* | `vocal_split_lead` (`basic-pitch`) | 0.419 / 0.703 | **0.492 / 0.833** | 0.0 / 18.88 ms | 0.6471 → **0.7647** *(Cliffs 0)* |
| `cat10_real_human_scale_mix` | **`vocal_split_lead` (`swift-f0`)** | *（无此引擎）* | **0.542 / 0.941** | **0.0 / 5.76 ms** | **0.8235** *(Cliffs 0)* |
| `cat10_real_human_scale_mix` | **`vocal_split_full` (`swift-f0 + dettato`)** | *（BP+DT: 0.864 / 0.413）* | **0.919 / 0.484** | **0.0 / 4.06 ms** | BP+DT 0.6471 → Swift+DT **0.9412** *(Cliffs 0)* |
| `cat7_full_song_structure` | **`vocal_split_full` (`swift-f0 + dettato`)** | *（BP+DT: 0.863 / 0.234）* | **0.969 / 0.289** | 0.0 / 2.00 ms | BP+DT 0.7273 → Swift+DT **1.0000** *(Cliffs 7→0)* |
| `cat5_solo_piano_guitar` *(无人声对照)* | `direct_dettato_classic`（基线） | 1.000 / — | 1.000 / — | — | Playability `95.81`（保持不变） |

### Layer B：人声清理执行顺序、预设与音域对比

1. **`cat8_vocal_artifacts` 清理前后对比（`basic-pitch` 与 `swift-f0` 干声）**：
   - BEFORE（先过滤 `min_note_ms=55` 后合并同音碎片）：4 连同音重击被错并为 **1** 个音符（`repeats_count: 4 → 1`），`65ms` 装饰音丢失 1 个，`vocal_clean_f1` 从 `0.7879` 跌至 **`0.6207`**；
   - AFTER（先做谐波幽灵/+12八度修复/颤音合并/滑音吸收，再保护连续重击与装饰音，最后执行最小时长过滤）：
     - `basic-pitch` 下 4 连重击完整保留 **4/4**，`vocal_clean_f1` 回升并稳定在 **`0.7879`**；
     - `swift-f0 + light` 在 `cat8` 下达到 **`F1 = 0.8571`（`4/4` 连音重击 + 保留 `2` 个短装饰音）**。
2. **真实人声 `cat9`（Demucs 分离）四档清理预设渐变对比**：
   - `basic-pitch`：碎片数量随强度递减 `off (69 音, F1=0.0263)` → `light (59 音, F1=0.0303)` → `standard (34 音, F1=0.0488)` → `strong (31 音, F1=0.0526)`（Recall 全程无损保持 `0.1429`）；
   - `swift-f0`：`off (16 音, F1=0.4348)` → `light (16 音, F1=0.4348，零误删连音)` → `standard (14 音, F1=0.4762)` → `strong (13 音, F1=0.5000)`（Recall 全程无损保持 `0.7143`）。
3. **人声音域预设 (`auto / male / female`) 对照（`cat1` 低音男声含 G2、`cat2` 高音女声含 D6）**：
   - `cat1_male_pop`：选 `female` 窄音域仅得 `swift-f0 F1=0.8148 (R=0.6875)` / `basic-pitch F1=0.6000`；选用 **`auto`（默认，73–1760 Hz / D2–A6）** 即恢复低音男声完整召回：`swift-f0 F1=1.0000 (16/16)`、`basic-pitch F1=0.8485`（`male` 预设 `0.8750`）。
   - `cat2_female_pop`：错选 `male` 音域导致高音截断（`swift-f0 F1=0.6154`、`basic-pitch F1=0.6667`）；选用 **`auto`** 与 **`female`** 均无损保留 D6 高音：`swift-f0 F1=1.0000 (14/14)`、`basic-pitch F1=0.9630 (13/14)`。

### Layer C：21 键 `vocal_lead` vs `classic` 纯无噪真值 MIDI 编曲矩阵

使用参考真值多轨 MIDI 直接评测编曲算法（涵盖「风物之诗琴」「镜花之琴」「老旧的诗琴」× `melody` / `balanced` / `rich`）：

| 曲目（GT Multi-Track MIDI） | 策略与风格 | BEFORE 移调 / 主旋律精确召回 / 八度断崖 (`>10st`) | AFTER 移调 / 主旋律精确召回 / 八度断崖 | 关键听感/乐理改进验证 |
|---|---|---|---|---|
| `cat4_jpop_anime` (`windsong`, `balanced`) | `classic`（兼容基线） | `+7` / `0.4706` / `0` | `+7` / `0.4706` / `0` | `classic` 完全字节一致兼容 |
| `cat4_jpop_anime` (`windsong` & `zither`, `balanced`) | **`vocal_lead`** | `0` / `0.8824` / `1` | **`-7` / `0.9412` / `0`** | 引入连续性崖跳惩罚与低八度舒适项后移调从 `0` 优化到 `-7`，断崖 `1 → 0`，Playability `75.87 → 77.34` |
| `cat4_jpop_anime` (`windsong`, `melody`) | **`vocal_lead`** | `0` / `0.8824` / `1` | **`-7` / `0.9412` / `0`** | 旋律完整度提升，Playability `48.86 → 51.83` |
| `cat3_complex_mix` (`windsong`, `rich`) | **`vocal_lead`** | `+0` / `1.0` / `0` | `+0` / `1.0` / `0` | 保留干净自然调内 `sus2`（大二度从 `3 → 4`），Playability `92.58 → 94.16` |
| `cat6_dense_band` (`windsong`, `balanced`) | **`vocal_lead`** | `+3` / `1.0` / `0` | `+3` / `1.0` / `0` | `classic` 有 `1` 次小二度撞音（m2）；`vocal_lead` 严格剔除且 Playability `72.10 → 74.45` |
| `cat7_full_song_structure` (`windsong`, `balanced`) | `classic` vs `vocal_lead` | `classic`: `+5 / 0.9091`；`vocal_lead`: `0 / 1.0` | `classic`: `+5 / 0.9091`；`vocal_lead`: **`0 / 1.0`** | 均准确释放 `18` 个前奏与 `>=350ms` 间奏伴奏事件，`vocal_lead` 保护全段人声 `1.0` 召回 |

### Layer D：真实 CC0 器乐代理指标与可试听对比样本

1. **`real_cc0_instrumental` (`GRN Music - Languor 12`, 18s 真实 CC0 器乐，无参考真值)**：
   - `direct + basic-pitch + classic`：4.93s | 转录 `134` 音符 → 编曲 `124` 事件（`transpose=+19`，相对转录 MIDI 适配分 `87.05`，**不可作准确率比较**）；
   - `direct + dettato + classic`（自动 Apple Silicon CPU，修复崩溃前须手动覆写）：57.10s | `76` 音符 → `63` 事件（`transpose=+12`，适配分 `85.62`）；
   - `vocal_split_accomp + dettato + classic`（自动去鼓伴奏）：68.69s | `75` 音符 → `61` 事件（`transpose=+12`，适配分 `84.97`）。
2. **BEFORE / AFTER 可直接试听的对比样本**：已全部保存于本会话导出目录 `samples/before/` 与 `samples/after/`（含每首曲目的 `.raw.mid`、`.arranged.mid` 与 22050 Hz 拨弦合成 `.preview.wav`），供维护者直接在本地对照试听。

---

## 5. 环境验证边界（如实声明）

- **本轮已完成实测验证**：macOS Apple Silicon 上真实 `ffmpeg 9.0`、`demucs 4.0.1`、`basic-pitch 0.4.0`、`dettato 2.0.0`（含自动设备避开 MPS 验证）与 `swift-f0 0.3.0` 全链路推理；`cat1–cat10`（含 VocalSet `CC-BY-4.0` 真实人声混音）与 `CC0 1.0` 真实器乐四层对比。
- **本轮未在本机物理机验收范围**：Windows x64 物理 NVIDIA CUDA 卡上运行 `swift-f0` / `demucs` / `dettato` 混合流水线的实测耗时，以及 Windows 物理机《原神》游戏窗口中的实机按键试奏（已交由维护者于最新发行包实测）。
