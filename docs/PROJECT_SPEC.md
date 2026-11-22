# LyraForge（暂定名）｜AI 音乐转谱与游戏乐器自动演奏一体化工作台

> **状态**：产品需求与实施蓝图（PRD + 技术设计草案），供 Google Antigravity CLI 开发使用  
> **版本**：v1.1（2026-11-22，补充 macOS Apple Silicon 开发与 Windows 目标运行跨平台约束）  
> **主要开发环境**：macOS Apple Silicon（Mac mini M4），优先兼容 macOS 的开发命令与初始化脚本  
> **首发目标运行平台**：Windows 10/11 x64；优先支持《原神》PC 版大世界内的自由乐器演奏（桌面壳与核心同时支持 macOS 开发调试与 DryRun 模拟演奏）  
> **开发工具**：Google Antigravity CLI（`agy`）及其模型／Orchestrator  
> **项目定位**：独立桌面应用；不依赖 BetterGI 或某个现成弹琴程序才可运行  
> **重要**：本文件规定“要做什么、为何这样做、验收什么”，并不意味着功能已实现。Agent 必须分阶段交付真实可运行的软件。

---

## 0. 一页概览（首先阅读）

用户希望获得一款**真正一体化的 AI 音乐工作台**：输入歌曲名称、音乐／视频链接或本地音视频文件，程序能够自动寻找**可合法获取**的乐谱或音频，在必要时使用本地 AI 音频转谱模型生成 MIDI，再针对《原神》的具体乐器自动改编成可弹奏的按键谱，支持试听、修谱、保存，并在用户明确启动后通过普通键盘模拟完成游戏内自动演奏。

理想交互：

> “帮我找《千本樱》的合适版本，优先用 MIDI；没有就从我选定的视频提取音频，转成原神风物之诗琴曲谱，突出主旋律，生成两个版本让我试听，保存到曲库。等我切到原神并打开琴后，再一键演奏。”

**必须实现的完整闭环**：

```text
关键词 / URL / 本地音频视频 / 现有 MIDI
       ↓
[搜索与来源选择] → [合规获取 / 用户导入]
       ↓
[现成 MIDI 解析] 或 [音频→MIDI 音符识别]
       ↓
[节奏清理 / 主旋律选择 / 音轨处理]
       ↓
[目标游戏 + 乐器配置 → 智能编曲与自动适配]
       ↓
[游戏实际可演奏曲谱 + 本地试听 + 可视化编辑]
       ↓
[保存到本地曲库 / 版本管理 / 导出和分享]
       ↓
[用户授权启动] → [Windows 键盘模拟] → [游戏中自动弹奏]
```

### 核心原则（优先级由高至低）

1. **端到端真实可用**：不是做一个只能展示按钮的 Demo。必须能从合法取得的 `.mid` 到游戏弹奏，再扩展从音频识别。
2. **不承诺“任意曲目无损还原”**：对复杂多音轨歌曲，允许降级、推荐更合适音源、给出客观质量评估和可编辑候选谱。
3. **专业音乐处理优先**：音乐转录使用专用模型与确定性算法；LLM 负责理解意图、工具编排、编曲策略、解释与交互，不把“让大语言模型凭空猜每个音符”作为核心方案。
4. **独立、离线优先**：已保存曲谱的浏览、编辑、试听、自动演奏在无网络／无 LLM 的条件下也应可工作。
5. **默认安全与合规**：不注入游戏、不读取／修改游戏内存、不规避反作弊；自动按键存在游戏规则风险，必须显著告知。搜索与获取音源遵守平台条款、用户授权及版权要求。
6. **可维护与可扩展**：音乐核心与 UI、AI Provider、平台输入、游戏乐器配置相互解耦；将来可扩展其他游戏或真实乐器。

---

## 1. 用户场景与产品边界

### 1.1 目标用户与典型场景

- **A：只想自动弹奏**：手头已有 MIDI，导入、选琴、试听后直接在原神里播放。
- **B：只有歌曲／视频**：拖入 MP3/WAV/FLAC/M4A/MP4 等，自动识别旋律、改编并保存。
- **C：只知道歌名**：输入关键词，优先搜索可用的 MIDI／琴谱，其次展示用户可选择的音视频来源；自动完成后续处理。
- **D：追求效果**：选择“主旋律优先／平衡／丰富和弦”，对两种候选方案 A/B 试听、对比和重新生成。
- **E：长期曲库使用**：下次打开软件搜索歌曲，一键选取此前保存的乐器版本并继续演奏；导入导出和备份。
- **F：社区交流**：导出标准 MIDI／结构化可弹奏谱／分享包；后期在授权条件下共享自制曲谱。

### 1.2 明确不属于核心范围

- 不做《原神》“千音雅集”等下落式音游自动打谱／自动通关功能。
- 不自动完成剧情、战斗、采集、登录等游戏行为。
- 不承诺自动搜到任何歌曲的可下载正版音频；搜索结果可能只有元数据、播放页或不可下载来源。
- 不实现付费站点绕过、DRM 解密、盗链、破解反作弊、账号凭据抓取。
- 不在首版追求系统声卡“边播放边实时无延迟转谱并同步原琴演奏”；该能力列为研究性质。
- 不把完整商业音乐录音上传共享服务器作为默认产品功能。

### 1.3 用户体验目标

- 新手体验：“导入文件 → 选乐器 → 生成 → 试听 → 保存 → 开始弹奏”，尽可能少操作。
- 高级体验：可查看转录模型、来源、音轨、BPM、移调、失真／丢音统计和参数。
- 每步明确显示“正在做什么”、耗时／进度、错误原因、重试／取消操作。
- 支持中文 UI 首发；文案与国际化资源预留英文／日文。
- 异常不会覆盖原版谱，也不会丢失已成功生成的中间成果。

---

## 2. 功能需求（MoSCoW / 交付优先级）

优先级：`P0` = MVP 必须，`P1` = 稳定版应有，`P2` = 后续扩展，`R` = 研发探索。

| 编号 | 功能 | 优先级 | 验收要点 |
|---|---|---|---|
| F01 | 本地 MIDI 导入与标准化 | P0 | 可解析常见 SMF Type 0/1、多轨、Tempo、拍号、延音等；错误文件可诊断 |
| F02 | 可配置游戏乐器与音高／键位映射 | P0 | 至少风物之诗琴，明确 21 键布局；支持增添配置 |
| F03 | MIDI→可弹奏事件序列（内部 JSON） | P0 | 处理音域、半音、冲突、按键密度；输出确定性结果 |
| F04 | Windows 游戏内自动演奏 | P0 | 手动开始／暂停／停止、倒计时、焦点安全控制、释放按键 |
| F05 | 本地试听与按键可视化 | P0 | 不启动游戏也能试听最终演奏结果 |
| F06 | SQLite 曲库、搜索、版本持久化 | P0 | 重启后所有已生成谱可查、可选、可复播 |
| F07 | 本地音频／视频导入 + 提取 | P1 | FFmpeg 转 WAV；错误反馈、媒体格式检测 |
| F08 | 音频自动转 MIDI（多引擎） | P1 | 基础引擎可用；可安装／切换高质量引擎 |
| F09 | 主旋律提取、移调和编曲策略 | P1 | 至少三档预设；可对比候选质量 |
| F10 | 关键词检索与曲源选择 | P1 | 优先合法 MIDI；其次候选音视频；用户许可后获取 |
| F11 | URL 导入与授权下载插件 | P1 | 只接收可支持的站点／合法来源；可取消，保留来源记录 |
| F12 | AI Agent 自然语言任务 | P1 | 自然语言拆解、调用白名单工具、透明进度、错误恢复 |
| F13 | 音轨编辑 / Piano Roll 轻量修谱 | P1 | 改音高、增删音符、调整节拍、撤销／重做 |
| F14 | JSON、MIDI、独立分享包导入导出 | P1 | 其他电脑可还原曲谱及必要配置 |
| F15 | 曲谱版本比较与历史记录 | P1 | 原始／清理／适配／手修均保留 |
| F16 | 批量转换、播放列表、标签收藏 | P2 | 批处理可靠，失败不影响其他歌曲 |
| F17 | 社区谱库、搜索和投稿审核 | P2 | 首先明确运营及版权规则；可举报和下架 |
| F18 | 跨游戏与其他乐器适配 | P2 | 无需重写核心转录器，只增 Instrument Profile |
| F19 | 流式实时听音→弹奏 | R | 需独立延迟／精度可行性验证，不纳入初版 |
| F20 | 歌词/段落对齐，自动寻找副歌 | P2 | 选段重生成，支持识别失败时手动截取 |
| F21 | 自动模型下载／资源管理 | P1 | 显示体积、许可证、进度、校验、磁盘空间、卸载 |

---

## 3. 输入、获取与转谱策略

### 3.1 输入类型

1. **文件**：`.mid`/`.midi`、`.mp3`、`.wav`、`.flac`、`.ogg`、`.m4a`、`.mp4`、`.mkv`（以 FFmpeg 实测支持为准）。
2. **文本**：歌名、歌名＋歌手、风格偏好，例如“这首歌突出人声旋律，保留副歌”。
3. **链接**：可合法访问的音频／视频文件 URL 或支持网站的公开链接；不得暗中使用用户身份登录或绕过访问控制。
4. **已有谱**：用户持有的简谱、键盘谱、社区谱结构文件（P1 插件），必要时让用户确认格式。

### 3.2 搜索和选源（先找 MIDI，后 AI 扒谱）

优先路径：

1. 查询用户已有曲库和本地文件索引，避免重复。
2. 查询可授权使用或用户指定的 MIDI／乐谱来源，按歌曲名、演奏者、版本、时长等进行排序。
3. 若没找到合适谱，呈现符合平台规则的公开视频／音频候选来源和元数据。
4. 获取文件前明确确认来源、版权使用权限和下载行为；若平台只允许在线观看，就不能将其视为可下载来源。允许用户自行导入已获得授权的本地文件。
5. 对搜索结果实行可信度评分：曲名匹配、版本类型（钢琴独奏＞复杂混音）、时长、音轨结构、用户评分、来源许可证。
6. 保存来源 URL、标题、作者（若可得）、许可证／权利声明、获取时间、hash，不自动公开原媒体。

**安全规则**：URL 拒绝回环／局域网／文件协议／非授权主机，防止 SSRF；白名单来源适配器、下载尺寸／时长上限、类型探测、超时和取消；禁止 Agent 自行执行未知网页给出的 shell 命令。

### 3.3 音频→MIDI：可替换引擎

引擎 Adapter 协议（概念）：

```python
class Transcriber(Protocol):
    id: str
    def probe(self) -> ModelInfo: ...
    def transcribe(self, audio_path: Path, options: TranscribeOptions,
                   on_progress: ProgressCallback) -> TranscriptionResult: ...
```

建议首选引擎评估：

| 候选 | 角色 | 选择理由／注意 |
|---|---|---|
| **Basic Pitch** | MVP/P1 基础引擎 | 较轻量，尤其适合独奏或分离后的单轨输入；代码见 Apache-2.0；复杂混音效果有限 |
| **dettato** | P1 高质量多乐器候选 | 可产出分轨 MIDI，代码／权重标记 Apache-2.0；项目较新，需验证 Windows/CPU/GPU 兼容、真实效果及下游权利条款 |
| **Demucs** | 可选预处理 | 将人声／伴奏等分离以提高目标旋律可辨性；项目源代码 MIT；实际模型和依赖许可单独审计 |
| **MuScriptor** | 研究备选 | 多乐器模型；**代码 MIT 不等于权重可商用**，其权重访问／CC BY-NC 条件需核查，不应默认打包进公开发行版 |
| **pianoize** | Agent 编曲参考 | Claude Code + Python 编曲思路，研究其策略与验证方法；非原琴专用，直接复用须核查许可证 |

必须支持：音频预处理、可选 source separation、模型热加载（受资源限制）、后台队列、取消、进度、模型版本与指标记录。GPU 为加速可选，不得让无独显用户完全无法使用基础转换。

**转录不是无损**：对高密度混音、人声、打击乐和半音丰富曲目，可能出现漏音／多音／错音。应提供“换源、换模型、只保留主旋律、人工微调”等补救路径。

### 3.4 三层输出与版本不覆盖

- `raw.mid`：模型原始识别／用户导入的 MIDI，尽量不改动。
- `cleaned.mid`：去抖、节拍量化、BPM、片段清理、音轨选择后的 MIDI。
- `arrangement.mid`：针对目标乐器适配后形成的 MIDI。
- `performance.json`：真正用于自动演奏的规范化事件序列，带目标乐器配置版本、按键映射和排序。
- `preview.wav`（可选）：本地合成试听缓存；不默认复制第三方商业音频进入分享包。
- `report.json`：转谱质量、丢音类型、参数、模型版本、源信息与统计。

所有变换必须具备输入参数和 provenance（输入 hash、模型版本、算法版本、时间、父版本）以便重现与比较。

---

## 4. 原神乐器适配：这是核心竞争力

### 4.1 不要用“简单取模塞进 21 键”糊弄

首个目标：**风物之诗琴**。它的 21 个琴键是三个八度内按既定音阶分布的按键，并非完整的 36 个半音；不同游戏乐器的布局、音色、和弦／打击机制可不同。**先建可配置乐器模型，再适配 MIDI**，不要把所有乐器硬编码成一个映射。

`InstrumentProfile` 至少包括：

```json
{
  "id": "genshin.windsong_lyre.v1",
  "display_name": "风物之诗琴",
  "game_id": "genshin",
  "kind": "pitched_diatonic",
  "key_count": 21,
  "available_pitches": ["TODO: 由真实游戏音域与校准结果填写"],
  "keybindings": {"TODO": "由真实 21 键键盘布局校准填写"},
  "polyphony_limit": null,
  "minimum_inter_onset_ms": "calibrate",
  "minimum_key_hold_ms": "calibrate",
  "supports_sustain": false,
  "calibration_version": 1
}
```

**注意：以上是配置格式例子，不是已经验证的具体音高／按键数据。** 要求 Agent 以游戏实际演奏和可信项目对照完成校准，测试所有 21 键。对和弦吉他／鼓类乐器另设专用 profile 与 adapter。

### 4.2 编曲流水线（可重复、可比较）

1. 标准化 MIDI：绝对时间、音轨、音高、起止、力度、节拍信息。
2. **主旋律筛选**：基于音轨、持续时间、音高分布、显著性、和声结构与用户偏好，必要时从音频转录结果中提取 melody track。
3. **调性和移调搜索**：在可接受的移调范围内比较音符覆盖率、旋律走向失真、听感；禁止仅凭“被映射的音符数最高”就选明显走调的版本。
4. **音域处理**：优先全局八度平移；局部八度纠偏只在连续性合适时执行，记录改变。
5. **不可用半音处理**：按配置选择最近可用音、邻近调性调整或删除；展示哪些音被改变，以及风险。
6. **和弦与复音简化**：保留主旋律优先；允许保留合理和声／改为琶音；按模拟键盘能力和当前乐器实际复音限制裁剪。
7. **节奏和密度控制**：最短间隔、密集重复键、延迟和跨轨合并；保持节拍感。
8. **按键事件生成**：用时间调度器生成 `down/up` 或 `tap`；相同时间点的优先顺序、重叠事件、释放策略必须定义并测试。
9. **质量报告**：可弹音比例、删除比例、移调量、最长高密度段、主旋律保留率、节奏偏差、主观试听选项。不可把“映射率 100%”当作“还原率 100%”。
10. **生成多个候选**：`Melody`（主旋律）、`Balanced`（旋律＋部分和弦）、`Rich`（密度更高）。用户 A/B 试听后再决定默认版本。

### 4.3 自动编曲质量打分（建议，权重通过回归测试调优）

```text
score = w1 * melody_preservation
      + w2 * rhythmic_fidelity
      + w3 * pitch_contour_preservation
      + w4 * harmonic_coherence
      - w5 * missing_note_penalty
      - w6 * dense_key_conflict_penalty
      - w7 * large_leap_penalty
```

必须留出 `user_quality_vote` 和 A/B 人工选择；对音频的自动客观评测不能替代听感。先做规则编曲基线，再用 Agent 根据报告调参；**LLM 不负责精确毫秒级事件循环**。

### 4.4 预览／编辑

- 双视图：简洁的 21 键虚拟琴 + Piano Roll（下落动画仅作为**预览可视化**，绝非下落音游作弊功能）。
- 听的是**最终可演奏版本**，不只是原始音频或原始 MIDI。
- 时间轴、循环片段、变速、BPM、移调、乐器、音轨开关、主旋律权重、最大和弦键数。
- 高亮改动：红色＝删除音、橙色＝替换／挪八度、蓝色＝保留（实际 UI 可采用无障碍友好的颜色＋图标）。
- `Undo/Redo`，保存为**新版本**、对比来源、导出 MIDI 与 JSON。
- 支持基本波形预览和音轨声部可视化（可以分阶段补充）。

---

## 5. Windows 游戏自动演奏模块

### 5.1 目标行为

1. 用户启动软件、选择已保存曲谱及目标乐器。
2. 用户自行在游戏里**打开对应自由演奏乐器界面**。
3. 软件提供倒计时与用户可配置热键；用户明确点击／按热键后才开始。
4. 使用 Windows 普通输入事件（如 `SendInput` 的受控实现）模拟按键，不接触游戏内存和进程内部结构。
5. 显示时间、进度、当前键位、暂停／停止状态；焦点离开或检测到异常立即停止并释放所有按下键。
6. 不保证所有游戏版本、全屏模式、键盘布局都能接受模拟输入；提供可重复的安全诊断和校准流程。

### 5.2 可靠性与安全设计

- 输入驱动单独隔离：`IPlaybackDriver`，初版 `WindowsKeyboardDriver`，同时提供**不发送系统按键**的 `DryRunDriver` 用于测试。
- `ForegroundWindowGuard`：白名单目标窗口 + 焦点校验；用户可手动指定窗口；不通过读写游戏内存来鉴别。
- 任何退出路径（停止、异常、焦点变化、关闭窗口、Ctrl+C 等）都执行 `release_all_keys()`。
- 独立的高精度调度器：基于 monotonic clock 和到期队列；不要依赖 React／网页定时器保证音符时序。
- 全局热键不能覆盖游戏常见交互；支持快捷键冲突检测、随时停止和紧急停止。
- 初版只支持**用户在场并已打开琴界面**；不自动切换账户、不做无人值守游戏脚本。
- 非管理员权限可用为目标，不建议以“关闭安全软件／管理员启动”作为标准解决方案。
- 必须有独立提示：第三方自动操作可能违反游戏条款，账号受罚风险**不能保证为零**；软件不得宣传“绝对安全／不会封号”。

### 5.3 真机验证矩阵

| 测试 | 应证明什么 |
|---|---|
| 21 键映射校准 | 每个按键触发预期琴音 |
| 单音 10～20 秒 | 节奏可靠，没有明显卡住／粘键 |
| 和弦与密集音符 | 同时键与重复键按可配置策略正确发出 |
| 焦点切走 | **立即停止**且释放全部键 |
| ESC／紧急停止 | 无遗留输入、下次还能播放 |
| 桌面预览模式 | 不向游戏或任何应用发送系统按键 |
| 不同帧率／负载 | 播放节奏误差可测量，超过阈值时给用户报告 |
| 不同键盘布局／缩放 | 标准键位校准和错误提示有效 |

实际游戏规则与安全策略可能变化，应允许完全关闭游戏自动演奏模块而保留所有曲库、试听和编辑能力。

---

## 6. AI Agent：以工具编排为核心，不把全部功能塞给模型

### 6.1 两个不同的 AI 层（必须分清）

**开发期 AI**：Google **Antigravity CLI**，用来架构、编写、测试和迭代本项目。用户在 CLI 中选择可用的 Gemini／Orchestrator 模型。

**产品运行期 AI**：LyraForge 运行时调用的 LLM Provider；应可关闭或替换。首选可接入正式 SDK/API 的 Gemini Provider；可选 OpenAI-compatible 接口／本地模型。运行时**不依赖**用户始终打开 Antigravity CLI。

可探索 `AntigravityCliAdapter` 作为个人本地试验，通过受控子进程执行 `agy -p ...`，但须先验证接口稳定性、授权方式和服务条款；不要把它当成未经确认可商用、可嵌入的正式推理 API，正式发行默认禁用。

### 6.2 Agent 可用白名单工具

```text
library.search(query)
library.get(song_id)
source.search(query, kind, filters)
source.inspect(candidate_id)
source.import_local(path)
source.acquire(candidate_id, user_consent_token)
media.extract_audio(asset_id)
transcribe.run(asset_id, engine_id, settings)
arrange.generate(transcription_id, instrument_id, style, settings)
arrange.compare(candidate_ids)
preview.render(arrangement_id)
library.save(arrangement_id, metadata)
library.export(arrangement_id, package_type)
playback.prepare(arrangement_id)
```

`playback.start` **不得由 LLM 自主调用**；必须通过用户在前台 UI 明确授权的操作触发。批量下载、文件删除、上传、分享均需单独授权。

**Agent 可做**：解析用户任务、选择候选、比较识别器结果、自动制定“先换 MIDI 源还是重转录”的优化计划、解释失败、生成个性化编曲参数。  
**Agent 不做**：无限制浏览下载、操作 shell 安装未知依赖、使用高权限访问游戏、对未授权文件私自公开分享。

### 6.3 Agent 任务状态机

`QUEUED → SEARCHING → AWAITING_SOURCE_CHOICE/CONSENT → FETCHING/IMPORTING → TRANSCRIBING → ARRANGING → REVIEW_READY → SAVED`  
可转入：`CANCELLED / FAILED / RETRYABLE / PARTIAL_SUCCESS`。

- 可暂停／取消／重试单步，支持断点复用已完成结果。
- Agent 必须给出短计划和实际进度，禁止“凭空声称转换完成”。
- 设置搜索步数、模型推理 token／费用上限、最大音频分钟数、下载次数和重试次数。
- 外部搜索文本不可信，防提示注入；下载／联网通过经过审核的 SourceAdapter。

### 6.4 示例用户命令

- “搜索《Lemon》的钢琴版，别用太吵的混音，生成原琴主旋律。”
- “这首听着乱，删掉伴奏，把主旋律的关键音留下。”
- “已经有 MIDI 就别再跑 AI，直接改编并保存。”
- “做一个节奏慢 15% 的版本，再给我 A/B 试听。”
- “把这首的原琴版本导出分享包，但不要带原始 MP3。”

---

## 7. 桌面应用架构与技术选型

### 7.1 推荐第一版方案

沿用用户熟悉的 Python + Vue3 技术，避免初版跨 Python/Rust/C# 多栈复杂度：

| 分层 | 推荐 |
|---|---|
| UI | Vue 3 + TypeScript + Vite + Pinia + 组件库（选择维护活跃者） |
| 桌面容器 | **PyWebView**（双平台支持：macOS 使用 WKWebView/Cocoa 开发与预览，Windows 使用 WebView2 作为目标发布；通过平台条件依赖隔离） |
| 本地 API | Python 3.11/3.12 + FastAPI（127.0.0.1 随机端口 + 会话授权）；也可先桥接，需隔离长任务 |
| 任务 | asyncio / worker process / bounded queue，CPU 密集与模型推理放进独立进程 |
| 数据库 | SQLite + WAL + 迁移系统（如 Alembic），大文件存在跨平台用户数据目录（macOS `~/Library/Application Support/LyraForge`，Windows `%LOCALAPPDATA%/LyraForge`） |
| 音频 | FFmpeg、librosa、soundfile（按用途引入，不一次装齐） |
| MIDI | mido / pretty_midi（核心先用纯 Python `mido` 解析／写出／结构转换，避免跨平台原生编译负担） |
| 推理 | Basic Pitch 基础；dettato／Demucs 插件化、按需下载、独立环境隔离 |
| 试听 | MIDI 合成器／合法授权 SoundFont；绝不默认打包未经许可游戏采样 |
| 输入 | 跨平台 `PlaybackDriver` / `FocusGuard` 抽象：macOS 提供 `DryRunDriver` 模拟演奏；Windows `SendInput` 与窗口守卫严格隔离在独立子包 |
| LLM | 独立 Provider Adapter：Gemini API、可选本地／OpenAI-compatible |
| 构建 | uv 锁定 Python 依赖（核心依赖不含 Windows 专属包）、pnpm 锁定前端；开发脚本优先兼容 macOS POSIX shell；Windows 打包通过 GitHub Actions 评估 PyInstaller |
| 测试 | pytest、Vitest、端到端 UI 冒烟测试、GitHub Actions `macos-latest` + `windows-latest` 矩阵构建测试（《原神》真机演奏另行人工验收） |

**不要求死守**：如果 Spike 证明 PyWebView 对全局热键、焦点与打包造成阻碍，可提交 ADR（架构决策记录）比较 Tauri 2 + Python sidecar 或 .NET UI，但必须提供迁移理由和样机；不得未经验证就大规模改栈。

### 7.2 原则：核心是 headless SDK/CLI，GUI 是壳

```text
+--------------------- Vue3 / PyWebView Desktop ---------------------+
| 搜索 | 转换任务 | 试听/编辑 | 本地曲库 | 分享 | 模型设置 | 播放控制 |
+------------------------ Local API / Bridge -----------------------+
                              |
    +-------------------------+--------------------------+
    |                         |                          |
 Music Service          Agent Orchestrator          Playback Service
    |                         |                          |
 Source Adapters         LLM Provider             Driver / Focus Guard
 FFmpeg/Transcribers     Tool Registry            Scheduler / DryRun
 Arranger / Validator
    |                         |                          |
    +-------------------------+--------------------------+
                              |
                      SQLite + File Store
                              |
              Standalone CLI (same core, used in tests)
```

### 7.3 建议目录结构

```text
lyraforge/
├─ AGENTS.md                      # Antigravity CLI workspace rules
├─ README.md
├─ pyproject.toml
├─ uv.lock
├─ package.json / pnpm-workspace.yaml
├─ docs/
│  ├─ PROJECT_SPEC.md
│  ├─ ARCHITECTURE.md
│  ├─ ROADMAP.md
│  ├─ LICENSE_AUDIT.md
│  ├─ TEST_PLAN.md
│  ├─ adr/
│  └─ api/
├─ apps/
│  └─ desktop/                    # Vue3 + PyWebView host
├─ packages/
│  ├─ music_core/                 # MIDI/音符事件/转换/安排；纯跨平台，不依赖 GUI/Win32
│  ├─ instrument_profiles/        # 游戏／乐器定义、键位校准
│  ├─ playback/                   # 跨平台 Scheduler + DryRun；windows/ 子包独立封装 SendInput 与 FocusGuard
│  ├─ source_adapters/            # 授权来源、合法获取
│  ├─ transcribers/               # Basic Pitch / dettato adapters
│  ├─ agent/                      # LLM + Tool registry + state machine
│  ├─ library/                    # SQLite models & file store
│  └─ api/                        # 本地 API
├─ tests/
│  ├─ fixtures/                   # 自制/许可测试 MIDI 与音频
│  ├─ unit/
│  ├─ integration/
│  └─ e2e/
├─ scripts/
└─ packaging/
```

**依赖方向**：UI/API → 服务层 → 领域层；领域层与所有跨平台核心模块（`music_core`、`instruments`、`library`、`agent`、跨平台 `playback` 调度器）严禁反向 import Vue/PyWebView/Win32/Windows 专属依赖/LLM；Windows 键盘模拟仅在 `playback.windows` 子包内通过平台条件延迟加载；插件通过接口和注册表接入。

### 7.4 建议的内部事件格式（示例）

统一以 `milliseconds` 或微秒整数保存内部时轴，避免 float 漂移；MIDI ticks 与 tempo 作为导入元信息保留。

```json
{
  "schema_version": 1,
  "song_id": "uuid",
  "arrangement_id": "uuid",
  "instrument_profile_id": "genshin.windsong_lyre.v1",
  "instrument_profile_hash": "sha256:...",
  "tempo_map": [{"tick": 0, "bpm": 120}],
  "duration_ms": 120000,
  "events": [
    {"at_ms": 0, "key_id": "TOP_ROW_01", "action": "tap", "hold_ms": 45,
     "source_pitch": 60, "mapped_pitch": 60, "source_track": 0}
  ],
  "transform": {"strategy": "melody", "transpose_semitones": 0, "speed": 1.0},
  "provenance": {"input_sha256": "...", "transcriber": "none", "arranger_version": "0.1.0"}
}
```

注：`TOP_ROW_01` 为演示 ID，不是实际游戏键名。应建立 JSON Schema + 版本迁移，严格验证顺序、界限、负数时间、重复键冲突和超时值。

---

## 8. 本地曲库、版本、备份与分享

### 8.1 本地数据设计

建议数据目录遵循系统规范（Windows 使用 `%LOCALAPPDATA%/LyraForge`，macOS 开发环境使用 `~/Library/Application Support/LyraForge`，可在设置中迁移曲库），SQLite 只保存索引／结构化数据；大文件按歌曲 UUID 组织：

```text
LyraForgeData/
├─ library.db
├─ songs/<song_uuid>/
│  ├─ source/                  # 可选：用户允许留存的原始媒体
│  ├─ midis/<version_uuid>/
│  │  ├─ raw.mid
│  │  ├─ cleaned.mid
│  │  └─ arrangement.mid
│  ├─ performance/<version_uuid>.json
│  ├─ reports/<version_uuid>.json
│  └─ previews/<version_uuid>.wav
├─ models/                     # 可选模型和下载校验文件
├─ caches/                     # 可清理、可重建的缓存
├─ exports/
├─ logs/                       # 默认脱敏
└─ backups/
```

### 8.2 推荐 SQLite 实体

| 表 | 关键字段／关系 |
|---|---|
| `songs` | id, title, artist, aliases, tags, created_at, updated_at |
| `sources` | id, song_id, type, original_url, provenance, license_info, sha256, local_path, imported_at |
| `assets` | id, song_id, kind, path, sha256, size, retained_policy |
| `transcriptions` | id, song_id, source_id, engine, engine_version, options_json, output_asset_id, status |
| `arrangements` | id, song_id, parent_id, transcription_id, profile_id, style, parameters, score, is_favorite |
| `playback_sessions` | id, arrangement_id, started_at, duration_ms, ended_state, error_summary |
| `jobs` | id, stage, status, retries, progress, checkpoint_json, error_code |
| `instrument_profiles` | id, version, config_json, calibration_hash, enabled |
| `share_exports` | id, arrangement_id, exported_path, manifest_hash, rights_ack, created_at |
| `settings` | key, value_json, updated_at |

使用事务、外键、迁移；文件先写临时文件并校验，再原子替换路径索引。对音乐源使用 SHA256 去重，相同转录参数＋模型版本可复用缓存结果。

### 8.3 一首歌保留多个乐器／版本

如《千本樱》：

```text
千本樱
├─ source: 用户导入 MP3 / 合法 MIDI / 视频元数据
├─ raw transcription: dettato vX
├─ optimized version A: 主旋律优先
├─ optimized version B: 旋律 + 和弦
├─ Windsong Lyre: A (收藏)
├─ Windsong Lyre: B
├─ 其他目标乐器: 未来扩展
└─ 演奏记录与导出历史
```

同一曲目不同版本不覆盖；支持“复制设置生成新版本”与“清理旧缓存但保留 MIDI/演奏谱”。

### 8.4 分享策略：先本地分享包，再社区平台

**P1 分享包**：建议扩展名 `.lyrapack`（ZIP 容器）。结构：

```text
my-song.lyrapack
├─ manifest.json               # schema、标题、作者、权利／许可、hash、版本
├─ arrangement.mid
├─ performance.json
├─ instrument_profile.json     # 仅最低必需配置
└─ LICENSE.txt                 # 可选：作者许可说明
```

- 默认**不含 MP3／视频／游戏采样**，也不自动上传；可选预览音频须有明确分享权利。
- 分享导入时校验签名／SHA256、ZIP 路径穿越、解压炸弹、最大文件大小和 schema；不执行包内脚本。
- 必须记录用户声明的创作来源与许可；“我自己 AI 转的”不等于自动获得分享原曲编曲的权利。
- P2 社区仅发布用户明确确认拥有发布权利的内容；要做版权投诉、撤稿、举报、限制滥用、审核和版本兼容策略。没有治理能力前**不建公开无审查曲库**。
- 备份支持整个 SQLite + 曲谱文件夹一致性备份／恢复，以及导入冲突处理。

---

## 9. UI 页面信息架构（无须一开始做满）

### 首页 / 智能转换

- 输入框：“输入歌曲名、链接，或拖入音频 / 视频 / MIDI”。
- 选择目标：游戏（原神）→ 乐器（风物之诗琴）→ 风格（主旋律 / 平衡 / 丰富）。
- 开始按钮 + 流程卡：搜索来源 → 音频处理 → 转录 → 编曲 → 试听；可以选择手动来源。
- 提示来源权利、耗时可能受音频时长和计算能力影响、GPU 可选。

### 曲库

- 搜索标题／歌手、标签、收藏、最后播放、乐器、来源类型、转换状态。
- 卡片显示候选版本、可弹率、更新时间；支持立即试听／编辑／导出／准备演奏。
- 可设置默认曲谱目录与备份路径。

### 转换任务详情

- 当前阶段、引擎、CPU/GPU、日志摘要、可取消、失败重试／切换引擎。
- 显示原始 MIDI、清理 MIDI、目标乐器谱三个阶段的质量统计。

### 乐谱工作台

- 曲线／Piano Roll、虚拟琴键、播放控制、A/B 试听。
- 选择音轨、速度、移调、和弦简化、音域、主旋律权重。
- 保存新版本、导出、查看改编报告。

### 游戏演奏

- “请先在原神内打开对应自由演奏乐器”的明确提示。
- 窗口选择／焦点检查／模拟键位校准／倒计时、开始、暂停、停止、紧急停止。
- 热键配置、常见问题、游戏规则风险提示。

### 设置 / 模型管理

- 离线／联网、AI Provider 与 API Key、模型状态与下载体积、设备资源、日志导出（脱敏）。
- 隐私、音乐版权声明、自动更新开关、缓存和模型空间管理。

---

## 10. API 与 CLI：为 GUI 和 Antigravity 自动化打好基础

CLI 命名仅为**规划接口**，不是现有可执行命令：

```bash
lyraforge import ./song.mid --title "My Song"
lyraforge arrange <song-id> --instrument genshin.windsong_lyre.v1 --style melody
lyraforge preview <arrangement-id>
lyraforge library search "千本樱"
lyraforge export <arrangement-id> --format lyrapack
lyraforge playback dry-run <arrangement-id>
# 真机播放必须由人显式交互授权，CLI 不支持静默 unattended 自动演奏
```

本地 API（例）：

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/v1/imports` | 导入媒体／MIDI |
| POST | `/v1/jobs/transcribe` | 提交转录任务 |
| POST | `/v1/jobs/arrange` | 创建编曲版本 |
| GET | `/v1/jobs/{id}` | 状态、日志摘要、错误码 |
| POST | `/v1/jobs/{id}/cancel` | 取消任务 |
| GET | `/v1/library/songs` | 搜索曲库 |
| GET | `/v1/library/songs/{id}` | 版本信息 |
| POST | `/v1/preview` | 生成试听／谱面 |
| POST | `/v1/exports` | 导出 MIDI／分享包 |
| POST | `/v1/playback/prepare` | 校验窗口、乐器映射，不立即按键 |
| POST | `/v1/playback/start` | 仅具备前台用户授权令牌时可开始 |
| POST | `/v1/playback/stop` | 立即停止，释放全部按键 |

API 仅绑定 `127.0.0.1`，随机端口，启动生成单次会话 token；严格限制跨域，禁止将外部网页授权为调用方；不要通过公网暴露。模型密钥仅本地安全存储，不写入日志、repo、分享包。

---

## 11. 开源项目参考与复用策略（必须先审许可证）

以下为**调研入口**，绝非已经证明可直接复制到新项目。Agent 在复制任何源码、模型权重、音色或谱库前，必须在 `docs/LICENSE_AUDIT.md` 中记录许可证、来源版本、改动和分发义务。

| 项目 | 可借鉴的内容 | 当前公开信息／风险 |
|---|---|---|
| [Genshin Music Studio](https://github.com/Akinome/genshin-music-studio) | 搜索→转谱→3 份 MIDI→原神适配→可视化；最佳架构对标之一 | **GPL-3.0**；直接复用源码会触发相应许可义务；需确认哪些功能确实可稳定运行 |
| [AutoMidiPlayer](https://github.com/Jed556/AutoMidiPlayer) | 多游戏乐器配置、曲库 UI、播放体验 | **GPL-3.0**；界面与流程可参考，但不要默认复制代码／品牌 |
| [GenshinLyreMidiPlayer](https://github.com/sabihoshi/GenshinLyreMidiPlayer) | Windows MIDI→键盘播放、历史与设置、多音轨 | **MIT** 主许可证；还需保留第三方 Notices |
| [Genshin Music Player](https://github.com/LanceLRQ/genshin-music-player) | 多种谱格式、按键冲突、音域报告、编辑功能 | **MIT**；使用源码须遵循版权通知 |
| [BetterGI AutoYuanQin scripts](https://github.com/babalae/bettergi-scripts-list) | 社区原琴谱格式、曲谱处理与脚本仓库分类 | 脚本／谱面各自权利不一定相同，须逐一审查；不依赖 BetterGI 运行 |
| [Basic Pitch](https://github.com/spotify/basic-pitch) | 轻量自动音频转 MIDI | **Apache-2.0** 代码；适合作为基础模型评测 |
| [dettato](https://github.com/kobimusic/dettato) | 多声部、乐器分轨、鼓组转录 | **Apache-2.0** 代码和权重；其训练数据／下游条款仍要单独记录 |
| [Demucs](https://github.com/facebookresearch/demucs) | 人声与伴奏分离 | 主仓库 **MIT**；模型权重／训练集另查 |
| [MuScriptor](https://github.com/muscriptor/muscriptor) | 高级多乐器转录 | **代码 MIT、权重可能 CC BY-NC**：默认不得用于商业可分发路径 |
| [pianoize](https://github.com/zeikar/pianoize) | 用 Agent 生成、验证和迭代可演奏编曲 | 主要针对钢琴；许可需审查 |

推荐先**独立实现接口和测试，再从许可证允许的项目选择性集成**。不要因为某个仓库“开源”就假设任何用途都许可。对 GPL 项目做架构／交互参考并自主实现通常比复制核心代码更容易保持许可选择权。

---

## 12. 非功能需求与风险控制

### 12.1 性能与资源

- **首次启动**不应强制下载数 GB 模型；基础 MIDI 功能立即可用。
- 模型和转换任务异步执行，UI 不冻结；可用 CPU，GPU 加速可选；磁盘不足时提前提示。
- 同一首曲目同参数缓存可复用；有限并发，防止同时跑多个 PyTorch 模型导致 OOM。
- 试听、手动编辑、曲库浏览必须能在断网状态下完成。
- 性能目标按测试机配置记录，不做无依据“任何歌曲 N 秒转完”的保证。

### 12.2 安全、隐私与文件处理

- 所有媒体路径和 URL 均按不可信输入处理；限制 ZIP 解压、路径遍历、命令注入、源站私网访问、超大文件和高压缩率包。
- FFmpeg/yt-dlp 通过固定参数列表调用（`subprocess` 不使用 `shell=True`）；并维持可审计版本。
- Antigravity 和运行期 Agent 都不能对未经授权的外部来源进行任意下载和 shell 执行。
- LLM API 调用要明示会发送什么信息。默认只传结构化音乐特征、元数据、用户提示，不主动上传完整商业录音。
- 用户 API Key 用 OS 凭据管理方案；日志不含 token、密码和完整个人路径；可关闭分析与在线调用。
- 危险操作（删除原始文件、发布社区、上传云端、真正发游戏键盘输入）需要明确交互确认。

### 12.3 版权与服务条款

- 搜索、播放、下载三个动作法律／平台条款可能不同；源适配器必须明确各自能力和许可。
- 用户导入受保护作品进行私人转换、复制和分享的合法性取决于当地法律、授权及实际用途；产品不能替用户自动认定“合法”。
- 分享时默认仅谱面和非侵权元数据，且提供权利声明与撤回机制。
- 游戏自动弹奏不是官方认可特权；不声称安全，不做绕过、注入、篡改或隐蔽操作。

### 12.4 可观测性与错误处理

统一错误码：`SOURCE_UNAVAILABLE / PERMISSION_REQUIRED / MEDIA_DECODE_FAILED / MODEL_MISSING / TRANSCRIPTION_FAILED / NO_PLAYABLE_NOTES / PROFILE_INVALID / GAME_NOT_FOCUSED / PLAYBACK_ABORTED / DISK_FULL / PACKAGE_INVALID`。UI 展示中文可操作建议与日志摘要。

---

## 13. 实施路线：切成能独立验收的里程碑

### M0｜技术验证、许可证审计、数据集（先做）

- 新建 Repo、`AGENTS.md`、工程规范、依赖锁定、测试与 CI 基础。
- 用**自己制作或有授权**的短 MIDI/音频建立回归样例：单音、和弦、半音、跨八度、连续重复、节奏变化。
- 核验《原神》目标琴的具体 21 键映射，形成可版本化 Profile。
- 检查参考仓库的功能真伪、许可证、可复用边界；评测 Basic Pitch 和 dettato 最小样例。
- **出口条件**：在 `docs/ARCHITECTURE.md` 和 `docs/LICENSE_AUDIT.md` 有证据、比较结论；CLI 能对样例解析 MIDI 并输出事件 JSON。

### M1｜可用的 MVP：MIDI → 原琴自动演奏 + 保存

- 完成 MIDI 导入、清理、Profile 适配、事件序列、DryRun 与 Windows 演奏驱动。
- Vue3 基础 UI：导入、预览、曲库、播放控制、紧急停止、设置。
- SQLite 保存并能重启恢复，A/B 简单版本可先不做。
- **出口条件**：使用自制测试 MIDI，从文件导入到模拟演奏与持久化全部贯通；macOS 与 Windows 桌面壳（Vue3 + PyWebView）均可启动并执行 DryRun/曲库/试听；所有异常路径释放键；GitHub Actions `macos-latest` + `windows-latest` CI 与单元测试通过；Windows《原神》实际自动演奏由真机单独完成校准与手动验收。

### M2｜音频 / 视频 → MIDI → 原琴

- FFmpeg 解析本地音视频；Basic Pitch 实际执行；支持可选 dettato 质量模式；基础主旋律与移调处理。
- `raw/cleaned/arrangement/performance` 版本树和进度／取消／错误恢复。
- **出口条件**：至少三类授权样例（独奏、含人声、复杂伴奏）完成自动生成；对不理想结果能展示质量和手工参数选项，不虚报准确率。

### M3｜更好听的编曲和工作台

- 主旋律优先／平衡／丰富三档、音轨挑选、可弹率与丢音原因、候选谱 A/B 试听。
- Piano Roll 基础修谱、Undo/Redo、版本比较与改编报告。
- **出口条件**：同一源可生成两个不同版本，能明显比较、独立保存、导出并演奏。

### M4｜关键词 + 链接 + Agent 自动流水线

- 内部曲库搜索、合法来源适配器、候选展示；用户授权后获取媒体／导入。
- 运行期 Provider + Tool registry + Agent 任务状态机；自然语言选择版本并做有界重试。
- **出口条件**：用授权测试源完成“歌曲名 → 选择来源 → 转谱 → 保存”；单一网站失败时不会让整个应用崩溃；断网时仍可用本地功能。

### M5｜分享、打包、稳定版

- `.lyrapack` 导入导出、备份恢复、安装器、模型安装／清理、可诊断日志。
- Windows 正式构建（GitHub Actions `windows-latest`）、自检、恶意包导入测试、异常恢复和文档。
- **出口条件**：另一个干净 Windows 环境在说明的依赖范围内可安装、导入分享包、试听、管理曲库；《原神》实际自动演奏需在 Windows 真机上由用户自行授权并单独验收。

### M6（可选）｜社区与跨游戏

- 权利声明、社区上传／搜索／举报／下架、内容审核与安全扫描。
- 加入新游戏／新乐器 Profile；有独立验收和版权／合规检查。

### 明确延期到研究阶段

- 真正在线流式实时多音轨音频转谱并毫秒级同步游戏播放。
- 自动生成原始完整音乐作品、云端分发商业音乐录音。

---

## 14. 测试计划与完成定义（DoD）

### 14.1 强制测试集

- **音乐核心**：Type 0/1 MIDI、不同 Tempo 事件、音符起止重叠、复音、半音映射、换调、超音域、三连音、密集重复键、空谱、坏文件、百万音符保护。
- **转换**：短音频、长音频分块、空白音频、静音、模型缺失、CUDA 不可用、CPU 降级、用户取消、进程崩溃恢复。
- **乐器映射**：21 键完整快照、Profile 版本兼容、键位配置缺失、相同键重叠去重。
- **播放**：dry-run 时间戳验证、焦点变化紧急停止、键释放、热键冲突、Windows 关机／中断模拟。
- **曲库**：重启后持久化、相同源去重、删除原始文件仍保留生成谱、版本回滚、备份恢复和迁移。
- **安全**：假 URL、超大媒体、恶意 ZIP、绝对路径／`../`、伪造文件扩展名、LLM 提示注入文本、未经授权播放请求。
- **UI**：首启无模型、离线、长任务、失败重试和空状态可用。

### 14.2 验收基线

- 每个里程碑有 `Acceptance Criteria`、CLI/GUI 重现步骤、自动测试、截图或短视频（可自建测试模拟，不以真实账号录像作为 CI 必需品）。
- 核心 MIDI 解析与纯转换单元测试覆盖率目标 ≥80%；对触碰游戏输入的代码使用 DryRun＋人工测试双重覆盖。
- 不假定自动转谱保真度可达到某个万能百分比；使用自制真值 MIDI 的音符 precision/recall/F1、onset 容差、可演奏覆盖率以及人工 A/B 听感来衡量。
- 任何“完成”必须能从干净 checkout 按 README 重建并运行；不能只写文档、空函数和占位按钮。

### 14.3 “一体化 MVP 已完成”的判据

- [ ] 从本地 `.mid` 导入到生成可弹奏谱。
- [ ] 不进入游戏即可试听真正用于输出的谱。
- [ ] 用户可在《原神》乐器界面主动开始、暂停、停止，焦点离开立即中止。
- [ ] 自动播放不会留下卡住的按键。
- [ ] 曲目和版本保存到本地，关闭软件重新打开仍能搜索和演奏。
- [ ] 可导出 MIDI 与 JSON，导入非法文件会安全失败。
- [ ] 完整操作说明及风险提示。

### 14.4 “AI 一键生成版已完成”的判据

- [ ] 本地 MP3 或 WAV 至少经一个真实模型生成 MIDI，而不是假数据。
- [ ] 由歌曲名或链接可进入合法来源选择流程；不允许获取时提示用户改为导入已有授权文件。
- [ ] Agent 能调工具、显示步骤、用户可以中途取消／重试。
- [ ] AI 不会自动执行游戏播放或未经同意上传音频。
- [ ] 同一首歌有多个可独立保存的生成版本和质量报告。

---

## 15. 推荐给 Antigravity CLI 的开发工作流

### 15.1 项目内配置

在 repo 根目录放置 `AGENTS.md`；Antigravity CLI 官方支持读取此文件作为 workspace rules。详细需求统一存 `docs/PROJECT_SPEC.md`。可在 CLI 使用 `/model` 选择账户支持的模型／Orchestrator。

**开发期建议**：架构与跨模块重构使用更强的 Planner／Orchestrator；具体编码、单元测试和样例构建交给 Executor；每个里程碑都要求先提出可执行计划并核实现有源码。可用 `agy` 进入项目交互，而不是每次把 PRD 全文贴进对话。

### 15.2 第一次启动，直接给 CLI 的提示词

```text
请先完整阅读 ./AGENTS.md 和 ./docs/PROJECT_SPEC.md。
目标是开发一个独立 Windows 桌面应用 LyraForge：AI 音频转 MIDI、原神自由乐器适配、曲库持久化、试听与安全的用户触发自动演奏一体化。

现在只执行 M0（技术验证与架构初始化），不要一次性尝试做完整产品：
1. 检查当前仓库，整理可验证的外部开源参考、许可证及技术依赖；不要照抄 GPL 代码。
2. 确定一个最小可运行、可测试的 Python music_core 方案；制定阶段性架构、ADR 和测试计划。
3. 初始化代码、依赖锁定、pytest/CI 基础，并让 CLI 能读取我们自建的测试 MIDI，生成结构化性能事件 JSON。
4. 添加最小的 instrument profile 校验与 DryRunDriver，禁止在 M0 真的操作原神窗口。
5. 实际执行测试并给出运行证据、未完成项目和进入 M1 的下一步任务。

约束：首发 Windows；Vue3+TS+PyWebView 作为默认 UI 方案（M0 暂不强制完成 UI）；Python 核心独立；离线 MIDI 路径优先；不要要求关闭杀毒或提升管理员权限；任何联网下载和执行陌生命令都先征求授权；不得假称已完成音频转谱或游戏真机演奏。
```

### 15.3 后续每个迭代的标准提示词模板

```text
阅读 AGENTS.md、docs/PROJECT_SPEC.md、docs/ROADMAP.md 和当前代码，
只推进里程碑 M<n> 的一组最小、可验证任务。
先列出受影响文件、可复用模块、风险、测试方法和 DoD；
然后实现并执行测试，不允许保留伪实现、无效测试或未说明的占位功能；
完成后更新 README、ROADMAP、必要的架构/许可证记录，提交变更摘要。
如果遇到音乐算法准确率或游戏窗口行为无法自动验证，提供人工复现步骤，绝不自行宣称测试通过。
```

---

## 16. 关键决策、开放问题与默认答案

| 决策 | 当前默认 | 何时重新评估 |
|---|---|---|
| 项目名称 | LyraForge（暂定，不使用官方商标作为产品名称） | 发布前检索重名／商标 |
| 开发 Agent | Google Antigravity CLI | 不影响运行时架构 |
| 运行期 LLM | 可选 Gemini API Provider | 实测成本／授权／本地模型需求 |
| 运行期是否依赖 Antigravity CLI | **否**，只允许试验性适配器 | 官方 SDK 与授权模型确认后 |
| 前端／桌面 | Vue3 + PyWebView（同时支持 macOS 与 Windows） | 实测双平台焦点、播放与打包兼容性后 |
| 主要开发环境 / 目标运行平台 | macOS Apple Silicon (M4) 开发 + DryRun；Windows 10/11 x64 目标发布与真机游戏演奏；GitHub Actions 双平台 CI | 每次里程碑与 CI 构建验证 |
| 主要编程语言 | Python + TypeScript | M0 架构 Spike 后 |
| 首版游戏 | 原神 Windows 大世界乐器 | 后续新增 profile |
| 首版乐器 | 风物之诗琴 21 键 | 完成真实按键音高校准后 |
| 音乐引擎 | 基础 Basic Pitch；评测 dettato | 准确度、CPU/GPU 和许可证审计后 |
| 搜索下载 | 授权来源，用户确认 | 来源适配器合规测试后 |
| 共享 | 离线分享包先行 | 版权治理就绪再做服务端 |
| 实时听音转谱 | 非 MVP | 需求强且延迟测试达标时 |
| 首版代码许可证 | 先不定；优先自主实现保留选择权 | LICENSE_AUDIT 完成后 |

### 风险优先级

1. **高**：复杂音频转 MIDI 的准确度不足 → 先找已有 MIDI、基准测评多引擎、用户可编辑。
2. **高**：游戏第三方输入合规与稳定性 → 明示风险、关闭自动演奏可独立使用、DryRun 与手动授权。
3. **高**：版权与下载／曲库分享 → 来源授权、独立谱版权记录、先离线包。
4. **中**：模型体积、GPU 与 Windows 依赖 → 按需安装、CPU 基础模式、隔离模型环境。
5. **中**：多项目许可证污染 → 分模块许可审计、优先接口／clean-room 实现。
6. **中**：UI／输入时钟精度 → 调度器隔离于网页、monotonic clock、严格停止机制。

---

## 17. 参考资料与核验日期

检索核验时间：**2026-11-22**。项目进展、模型许可证及服务条款会变化；开发开始时再次核查各原仓库的 README、LICENSE、Release、Issues，并把 commit SHA 写入审计文档。

- Google Antigravity CLI 官方文档（安装、`agy`、`/model`）：https://antigravity.google/docs/getting-started?tab=cli ；https://antigravity.google/docs/models
- Antigravity `AGENTS.md` 规则加载：https://antigravity.google/docs/rules/
- 原神相关自动谱工具：https://github.com/Akinome/genshin-music-studio
- 自动演奏参考：https://github.com/Jed556/AutoMidiPlayer ；https://github.com/sabihoshi/GenshinLyreMidiPlayer ；https://github.com/LanceLRQ/genshin-music-player
- BetterGI 谱源参考：https://github.com/babalae/bettergi-scripts-list
- 音乐转谱基础：https://github.com/spotify/basic-pitch
- 多乐器转录：https://github.com/kobimusic/dettato ；https://github.com/muscriptor/muscriptor
- 分离器：https://github.com/facebookresearch/demucs
- Agent 编曲参考：https://github.com/zeikar/pianoize

---

## 18. 最终交付清单

**MVP（M1）**：Windows 可运行桌面包 + MIDI 导入 + 琴谱适配 + 离线试听 + 本地曲库 + 用户触发自动演奏 + 操作文档 + 自动测试。  
**完整 1.0（M2–M5）**：音频／视频转 MIDI + 可选高质量模型 + 搜索与合法来源获取 + Agent 自动化编排 + 版本编辑／A-B 试听 + 分享包 + 备份与发布流程。

**验收的根本标准**：用户既能“一句话生成谱”，又能“以后不联网也找到、试听并再次演奏同一首歌”；所有阶段真实可用、可复现、可维护。
