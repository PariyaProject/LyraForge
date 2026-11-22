# LyraForge 开发进度总览（Progress）

> **更新时间**：2026-11-22  
> **状态分类标准（FIX-009）**：`已实现且已测试` ｜ `已实现但未完成真实环境验收` ｜ `部分实现` ｜ `未实现` ｜ `因外部环境阻塞`  
> **主要开发环境**：macOS Apple Silicon（Mac mini M4, Python 3.11.13, Node v24.14.0, pnpm 12.6.0）  
> **目标运行平台**：Windows 10/11 x64（核心、曲库、FastAPI 与 Vue 3 + PyWebView 双平台兼容）

---

## 1. 模块成熟度清单（严格五态分类）

| 里程碑 | 功能编号 | 模块 / 能力 | 成熟度状态 | 依据与边界说明 |
|---|---|---|---|---|
| **M0** | F01–F03 | 仓库骨架、GPL-3.0 许可审计、MIDI 解析、`TempoMap`、`Arranger`、乐器配置、`performance.json`、`DryRunDriver` | **已实现且已测试** | `src/lyraforge/music_core/*`, `src/lyraforge/instruments/*`, `docs/LICENSE_AUDIT.md`, `tests/unit/test_*.py` |
| **M1** | F05, F06 | SQLite (WAL v3) 曲库持久化、SHA256 去重、版本树、离线 WAV 拨弦试听合成 | **已实现且已测试** | `src/lyraforge/library/*`, `src/lyraforge/preview/synth.py`, `tests/unit/test_library.py`, `test_preview.py` |
| **M1** | F04–F06 | 本地 FastAPI 服务 (`127.0.0.1` + 会话 Token)、Vue 3 工作台与 PyWebView 桌面壳启动器 | **已实现且已测试** | `src/lyraforge/api/*`, `src/lyraforge/desktop/*`, `apps/desktop/web/*` |
| **M1/M5** | FIX-002 | 跨平台系统凭据安全存储（macOS Keychain / 受限权限密钥文件 `0o600` / 环境变量 `LYRAFORGE_LLM_API_KEY`）、旧版明文迁移、日志脱敏与备份/分享包秘钥清洗 | **已实现且已测试** | `src/lyraforge/secrets.py`, `library/{store,packaging}.py`, `agent/llm.py`, `tests/unit/test_secrets_and_security.py` |
| **M1/M5** | FIX-002 | Windows Credential Manager (`advapi32.dll` `CredReadW`/`CredWriteW`/`CredDeleteW`) | **已实现但未完成真实环境验收** | `src/lyraforge/secrets_win32.py`；macOS 端已隔离依赖并通过分层测试，Windows 真机 `ctypes` 实测待目标机运行 |
| **M1/M5** | F04, FIX-003 | 隔离 Windows `SendInput` 自动演奏驱动（含松键重试、失败保留 `pressed` 状态与后续 `release_all` 修复）与焦点窗急停守卫 | **已实现但未完成真实环境验收** | `src/lyraforge/playback/windows/*`, `tests/unit/test_windows_playback.py`；macOS 通过 Mock 校验，需 Windows 10/11 + 《原神》21 键校准 (`calibration.status="unverified"`) 与切窗/ESC 实音验收 |
| **M2** | F07 | 原生 WAV 音频导入与单声道重采样标准化 | **已实现且已测试** | `src/lyraforge/media/extract.py`, `tests/unit/test_media.py` |
| **M2** | F07 | 基于 FFmpeg 的 MP3 / MP4 / MKV 非 WAV 音视频提取 | **因外部环境阻塞** | `src/lyraforge/media/extract.py`（受控子进程与错误校验通过 Mock 测试；当前 macOS 未安装 `ffmpeg`，真机真实视频提取未跑） |
| **M2** | F08, F09, FIX-007 | 内置纯 Python YIN 单音转录 (`builtin-mono`)、MIDI 清理与导出、可取消后台任务流水线 | **部分实现** | 核心流水线、任务取消及基准脚本 `scripts/eval_transcribers.py` 已实现且已测试；**性能实测边界**：单音旋律 `solo_melody` F1=`1.0000`，但多音和弦 `polyphonic_piano_chords` F1=`0.0`、双声部 `dense_multi_register` F1=`0.3333`（纯 Python YIN 算法天限，复杂多声部依赖隔离 ML 模型） |
| **M2** | F08, FIX-007 | 独立隔离进程神经网络转录（`basic-pitch` / `dettato`） | **因外部环境阻塞** | `src/lyraforge/transcribers/{basic_pitch,dettato,_subprocess}.py` 已实现并通过环境变量/子进程 Mock 测试；当前开发机未安装 `basic-pitch` 与 `dettato` 环境 |
| **M3** | F09, F13, F15 | 镜花之琴预设、主旋律追踪、和弦琶音、多维质量评分、A/B 对比、Piano Roll 可视化编辑与 Undo/Redo | **已实现且已测试** | `instruments/data/genshin.floral_zither.v1.json`, `music_core/{arranger,scoring}.py`, `PianoRollEditor.vue`, `tests/unit/test_scoring_and_m3.py` |
| **M4** | F10–F12, FIX-005, FIX-006 | 本地曲库/目录搜索、DNS 固定防 SSRF 外网直链下载（重定向/超时/体量上限）、开放许可曲库检索（Internet Archive CC/PD `OpenMusicCatalogSourceAdapter`）与 LLM/规则编曲自优 Agent | **部分实现** | 本地元数据检索、开放曲库（Mock Internet Archive HTTP 测试）、DNS 重绑定/重定向 SSRF 拦截与音频自动转谱链路已通过测试；受限于版权边界未接入商业音乐平台检索（商业受权内容需用户提供授权本地文件或开放许可直链），且公网实时连通性需用户在运行时勾选联网授权实测 |
| **M5** | F14, F21, FIX-004 | `.lyrapack` 分享包（默认剔除原始音频、强制授权确认、防恶意 ZIP）、全库 ZIP 备份与**分阶段原子恢复 + 自动回滚** | **已实现且已测试** | `src/lyraforge/library/packaging.py`, `tests/unit/test_lyrapack_and_m5.py`（已验证损坏 DB / 错误 Schema / 中途 `OSError` 自动回滚恢复原库） |
| **M5** | F21, FIX-001 | GitHub Actions 双平台 CI 配置（修复 `pnpm@12.6.0` `packageManager` 锁文件同步与 Windows `LyraForge.exe` 产物存在性强制检查）与 PyInstaller 打包脚本 | **已实现但未完成真实环境验收** | `.github/workflows/ci.yml`, `apps/desktop/web/package.json`, `packaging/lyraforge.spec`, `scripts/build_windows.ps1`；本地 `pnpm install --frozen-lockfile && make check` 通过，远程仓库远端运行状态待推送后在 GitHub Actions 验证 |
| **未在当前范围** | — | Windows 真实桌面打包二进制 `.exe` 运行冒烟与真实登录凭据加解密联调 | **未实现** | 需直接在 Windows 10/11 Runner 或实体机运行 `./scripts/build_windows.ps1` 并启动 `dist/LyraForge/LyraForge.exe` 后验证 |

---

## 2. 最新实测验证记录（FIX-001 ~ FIX-009 落地后实跑）

测试环境：`macOS Darwin (Apple Silicon)`，`Python 3.11.13`，`pnpm 12.6.0`：

1. **锁文件与前端依赖一致性 (`pnpm --dir apps/desktop/web install --frozen-lockfile`)**
   - 结果：`Done in 50ms using pnpm v12.6.0`（与 `apps/desktop/web/package.json` `"packageManager": "pnpm@12.6.0"` 严格一致）
2. **静态检查 (`uv run ruff check .`)**
   - 结果：`All checks passed!`（0 错误）
3. **Python 单元、分层门禁与集成测试 (`uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80`)**
   - 结果：**111 passed, 1 warning in 24.80s**（覆盖率 **90.17%**，4692 行语句 / 1114 条分支；涵盖 Keychain/凭据隔离、旧明文迁移、备份清洗与崩溃回滚、DNS 固定防 SSRF 与重定向拦截、Windows 松键重试与 `pressed` 一致性、Internet Archive 开放曲库排序与音频回退转谱等）
4. **Vue 3 前端测试与构建 (`pnpm --dir apps/desktop/web test` / `build`)**
   - `vitest run`：**Test Files 3 passed (3), Tests 5 passed (5)**
   - `vue-tsc --noEmit && vite build`：成功（697ms）
5. **CLI 端到端冒烟 (`make smoke`)**
   - 结果：退出码 `0`（配置查询、MIDI 适配、Schema 验证与 `DryRunDriver` 模拟演奏完成 48 个动作、0 残留按键）
6. **转录引擎可用性与合成基准 (`uv run python scripts/eval_transcribers.py`)**
   - 环境探测：`ffmpeg_available = false`，`basic-pitch.available = false`，`dettato.available = false`，`builtin-mono.available = true`
   - `builtin-mono` 实测（22.05kHz 多谐波合成音频 → 转谱 → 清理 → 风物之诗琴编曲）：
     - `solo_melody` (8 notes): precision `1.0`, recall `1.0`, F1 `1.0`, `playable_ratio = 1.0`, `overall_score = 100.0`, `elapsed_ms = 167.16`
     - `polyphonic_piano_chords` (12 notes): raw/cleaned `4` events, F1 `0.0`, `elapsed_ms = 142.91`
     - `dense_multi_register` (16 notes): raw/cleaned `8` events, precision `0.5`, recall `0.25`, F1 `0.3333`, `elapsed_ms = 151.37`

---

## 3. 明确阻塞项与 Windows 真机验收清单

1. **Windows 10/11 + 《原神》真机独立验收（M1-D / M5）**：
   - `genshin.windsong_lyre.v1` 与 `genshin.floral_zither.v1` `calibration.status` 均为 `unverified`。
   - 需在 Windows PC 上验证非管理员运行 `LyraForge.exe`、Windows Credential Manager 读取/保存 API Key、自由演奏界面 21 键实音校准、切窗焦点守卫停键、ESC/Stop 全部松键。
2. **GitHub Actions 远端 CI 验证**：
   - 此前 `origin/main`（commit `a682716`）在 CI 中因缺少 `pnpm` 版本失败（`Error: No pnpm version is specified.`）。本次修复提交待推送到 GitHub 后再验证 `macos-latest`、`windows-latest` 与 `package-windows` 三项作业全绿。
3. **可选外部多媒体与神经网络依赖**：
   - 需按需安装 `ffmpeg`（解锁 MP3/MP4/MKV），并通过 `LYRAFORGE_BASIC_PITCH_PYTHON` / `LYRAFORGE_BASIC_PITCH_BIN` 或 `LYRAFORGE_DETTATO_PYTHON` / `LYRAFORGE_DETTATO_BIN` 配置独立 Python 环境以获得多声部音乐的高准确率转录。
