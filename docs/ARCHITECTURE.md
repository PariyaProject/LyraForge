# LyraForge 架构设计（Architecture）

> **更新日期**：2026-11-22  
> **适用范围**：M0 已实现架构 + M1–M5 演进边界  
> **平台模型**：macOS Apple Silicon（Mac mini M4）为主开发环境；Windows 10/11 x64 为主目标运行平台

---

## 1. 核心架构原则

1. **跨平台核心与服务层**：`music_core`、MIDI 解析/写出、编曲、乐器配置、SQLite 曲库（M1+）、AI Agent 编排（M4+）、本地 FastAPI 服务（M1+）全部使用纯跨平台 Python，在 macOS Apple Silicon 与 Windows x64 上行为一致。
2. **双平台桌面壳**：规划 UI 采用 Vue 3 + TypeScript + Vite + PyWebView（macOS 使用 WKWebView/Cocoa，Windows 使用 WebView2），通过本地 `127.0.0.1` 随机端口 + 会话 Token 与 Python 服务通信，不绑定单个桌面操作系统。
3. **Windows 键盘模拟严格隔离**：跨平台层仅定义 `PlaybackDriver` 与 `FocusGuard` 协议；`DryRunDriver` 与 `Player` 可在 macOS 和 Windows 无差异运行。Windows `SendInput` 与 `ForegroundWindowGuard` 在 M1 作为独立子包 `lyraforge.playback.windows` 实现，并仅在 `sys.platform == "win32"` 时按需延迟加载。
4. **核心依赖零 Windows 污染**：`pyproject.toml` 主依赖不含任何 `pywin32`、`comtypes` 或 Win32 原生库；未来平台专属包必须通过 PEP 508 环境标记或 optional extras 隔离。
5. **AI 模型与转录环境隔离**：Audio→MIDI 转录（Basic Pitch / dettato）通过独立子进程或独立虚拟环境接入（参见 [ADR-0001](adr/0001-headless-python-core-and-isolated-transcribers.md)），不与主核心共享强约束的 TensorFlow/PyTorch 依赖。

---

## 2. 分层与依赖方向

```text
+----------------------- Desktop Shell (M1+) -----------------------+
|  Vue 3 + TypeScript + Vite                                        |
|  PyWebView Host: macOS (WKWebView/Cocoa) | Windows (WebView2)     |
+-------------------------- Local API / CLI ------------------------+
|  FastAPI 127.0.0.1 + Session Token (M1+)  |  lyraforge.cli (M0)   |
+---------------------------- Service Layer ------------------------+
|  Library (M1+)  |  Transcriber Worker (M2+)  |  Agent (M4+)       |
+---------------------------- Domain Core --------------------------+
|  lyraforge.music_core       (pure cross-platform Python)          |
|  lyraforge.instruments      (JSON profile registry)               |
|  lyraforge.errors           (ErrorCode, LyraError)                |
+--------------------------- Playback Layer ------------------------+
|  Cross-platform: Player, Clock, DryRunDriver, StopToken           |
|  Windows-only (M1, isolated): lyraforge.playback.windows          |
|    - WindowsKeyboardDriver (Win32 SendInput)                      |
|    - ForegroundWindowGuard (Win32 public window APIs only)        |
+-------------------------------------------------------------------+
```

### 强制依赖边界（由 `tests/unit/test_layering.py` AST 静态检查强制保证）

| 模块 | 允许依赖 | 严禁导入 |
|---|---|---|
| `lyraforge.errors` | Python 标准库 | 一切第三方库与项目内部模块 |
| `lyraforge.music_core` | 标准库、`mido`、`jsonschema`、`lyraforge.errors` | GUI（`webview`/`tkinter`/`PyQt*`）、OS 输入（`ctypes`/`win32*`/`msvcrt`/`winsound`/`pynput`/`keyboard`/`comtypes`）、网络（`urllib`/`http`/`requests`/`httpx`/`socket`）、`subprocess`、LLM SDK、`lyraforge.playback`、`lyraforge.cli` |
| `lyraforge.instruments` | 标准库、`lyraforge.errors`、`lyraforge.music_core.profile` | GUI、OS 输入、网络、`playback`、`cli` |
| `lyraforge.library` | 标准库、`sqlite3`、`lyraforge.errors`、`music_core`、`instruments`、`media`、`transcribers`、`playback`、`preview` | GUI、Win32/OS 输入（含 `library.packaging` `.lyrapack` / ZIP 备份防护） |
| `lyraforge.sources` | 标准库（`urllib`、`socket`、`ipaddress`）、`lyraforge.errors`、`fs`、`media` | GUI、Win32/OS 输入、`lyraforge.playback`、禁止内网/本地 SSRF |
| `lyraforge.agent` | 标准库（`urllib`、`re`）、`lyraforge.library`、`sources`、`music_core` | GUI、Win32/OS 输入、`lyraforge.playback`（严禁自动触发演奏）、不依赖 Antigravity CLI 运行时 |
| `lyraforge.media` | 标准库（`wave`/`subprocess`）、`lyraforge.errors`、`lyraforge.fs`、`playback.guards` | GUI、Win32/OS 输入、`shell=True` |
| `lyraforge.transcribers` | 标准库（`math`/`subprocess`/`wave`）、`mido`、`media`、`music_core.midi_import` | GUI、Win32/OS 输入、主进程直接 import TensorFlow/PyTorch |
| `lyraforge.preview` | 标准库（`wave`/`math`/`array`）、`lyraforge.errors`、`fs`、`music_core.performance` | GUI、Win32/OS 输入、未经许可游戏采样 |
| `lyraforge.api` | `fastapi`、`uvicorn`、`pydantic`、`library`、`playback.factory`、`preview` | GUI（`pywebview`/`tkinter`）、Win32/`ctypes` |
| `lyraforge.desktop` | `uvicorn`、`lyraforge.api`；延迟加载 `webview`（optional extra `desktop`） | Win32/`ctypes` 键盘输入 |
| 跨平台 `lyraforge.playback`（`windows/` 之外） | 标准库、`lyraforge.errors` | `win32*`、`ctypes`、`msvcrt`、`winsound`、`pynput`、`keyboard`、`comtypes` |
| `lyraforge.playback.windows` | 仅在 `sys.platform == "win32"` 时延迟导入 `ctypes`（公开 Win32 `SendInput` 与窗口标题 API） | 不得被核心模块直接导入；仅由 `playback.factory.create_playback_backend()` 在 Windows 延迟加载 |

---

## 3. M0 已实现数据流与模块说明

```text
MIDI 文件 (.mid)
  │
  ▼  lyraforge.music_core.midi_import.load_midi_file / parse_midi_bytes
NormalizedScore
  │  - 解析 SMF Type 0 / Type 1，拒绝 Type 2 与 SMPTE 分辨率
  │  - 全局 TempoMap（跨音轨汇总 set_tempo，Fraction 精确累计微秒避免浮点漂移）
  │  - 处理 vel=0 note_off、同音高重叠 FIFO 配对、未闭合音符兜底、孤立 note_off 警告
  │  - ImportLimits（文件大小 / 最大音符数 / 最大时长保护）
  │
  ├──▶ lyraforge.instruments.load_builtin_profile ("genshin.windsong_lyre.v1")
  │       └─▶ InstrumentProfile (JSON Schema Draft 2020-12 + 语义校验 + sha256)
  │
  ▼  lyraforge.music_core.arranger.arrange
Arrangement (events, dropped_notes, transpose_candidates, stats)
  │  1. 音轨过滤（默认剔除 GM 第 9 通道打击乐）
  │  2. 全局移调搜索（整数惩罚成本：直接命中=0、八度折叠=1、缺失半音=2）
  │  3. 超音域整八度折叠（记录 octave_folded）
  │  4. 缺失半音策略（nearest 最近音<=2半音替换 或 drop）
  │  5. 同毫秒同按键去重（保留原音高优先、力度大、时值长）
  │  6. 和弦聚类上限（melody=1, balanced=3, rich=6；保留最高音、最低音与高到低其余音）
  │  7. 同键连击最小间隔保护（min_same_key_interval_ms）
  │  8. tap 保持时长裁剪（夹紧到 [min_key_hold_ms, max_key_hold_ms] 且不重叠下次同键）
  │
  ▼  lyraforge.music_core.performance.build_performance / validate_performance
performance.json (v1) + report.json
  │  - 确定性内容哈希与 UUIDv5（无墙钟时间、无绝对路径，同输入+配置字节级一致）
  │  - JSON Schema + 语义校验（时间非递减、同键不重叠按住、profile_hash 一致）
  │
  ▼  lyraforge.playback.Player + DryRunDriver (macOS / Windows CI 通用)
PlaybackResult + 动作日志（JSONL）
  - UP 先于同毫秒 DOWN；基于 Clock（VirtualClock / MonotonicClock）
  - 每次等待与发送前轮询 StopToken 与 FocusGuard
  - try/finally 保证所有退出路径调用 release_all()，失败时降级逐键 key_up()
```

---

## 4. 数据目录与跨平台路径规范（M1+）

从 M1 引入本地持久化时，采用跨平台数据目录解析（优先 `platformdirs` 或内置兼容实现，支持设置中迁移与环境变量覆盖）：
- **macOS**：`~/Library/Application Support/LyraForge`
- **Windows**：`%LOCALAPPDATA%\LyraForge`
- **Linux（CI/备选）**：`~/.local/share/LyraForge`

---

## 5. 统一错误码（`lyraforge.errors.ErrorCode`）

包含 `docs/PROJECT_SPEC.md` §12.4 全部 11 个标准错误码及 4 个 M0 域内补充错误码：
- **规范标准码**：`SOURCE_UNAVAILABLE`、`PERMISSION_REQUIRED`、`MEDIA_DECODE_FAILED`、`MODEL_MISSING`、`TRANSCRIPTION_FAILED`、`NO_PLAYABLE_NOTES`、`PROFILE_INVALID`、`GAME_NOT_FOCUSED`、`PLAYBACK_ABORTED`、`DISK_FULL`、`PACKAGE_INVALID`
- **M0 补充码**：
  - `MEDIA_UNSUPPORTED`：文件头合法但属于不支持的变体（如 SMF Type 2、SMPTE 时间格式）
  - `LIMIT_EXCEEDED`：触发防 DoS 上限（文件过大、音符数超限、时长超限）
  - `PERFORMANCE_INVALID`：`performance.json` 未通过 Schema 或语义验证
  - `INVALID_ARGUMENT`：非法参数（如越界速度/移调/和弦窗参数）

---

## 6. M0 遗留/待验证边界说明

1. `genshin.windsong_lyre.v1` 的 21 键键位与八度命名（MIDI 48–83，Z–M / A–J / Q–U）已与 MIT 参考项目对照，但 `calibration.status` 显式标记为 `unverified`，必须在 M1 于 **Windows《原神》真机界面**逐键实测校准后方可改为 `verified`。
2. 当前（M0）仅实现 `DryRunDriver`，绝不触发任何操作系统键盘模拟。
