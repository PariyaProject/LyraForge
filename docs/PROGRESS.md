# LyraForge 开发进度总览（Progress）

> **更新时间**：2026-11-22  
> **状态分类标准**：`已实现且已测试` ｜ `已实现但未完成真实环境验收` ｜ `部分实现` ｜ `未实现` ｜ `因外部环境阻塞`  
> **开源许可**：GNU General Public License v3.0 ([LICENSE](../LICENSE))  
> **主要开发环境**：macOS Apple Silicon（Python 3.11.13, Node.js, pnpm 12.6.0）  
> **目标运行平台**：Windows 10/11 x64（核心、曲库、FastAPI、MCP 与 Vue 3 + PyWebView 跨平台兼容）

---

## 1. 模块成熟度清单（严格五态分类）

| 领域 / 编号 | 模块 / 能力 | 成熟度状态 | 依据与边界说明 |
|---|---|---|---|
| **M0 / M1** | MIDI 导入、`TempoMap`、`Arranger`、乐器预设、SQLite (WAL v3) 曲库、拨弦试听、`DryRunDriver` | **已实现且已测试** | `src/lyraforge/music_core/*`, `library/*`, `preview/synth.py`, `playback/driver.py` |
| **M1 / Desktop** | 本地 `127.0.0.1` FastAPI + 会话 Token、Vue 3 工作台（含真实界面截图 [lyraforge-workbench.png](assets/lyraforge-workbench.png)）与 PyWebView 桌面壳 | **已实现且已测试** | `src/lyraforge/api/*`, `desktop/*`, `apps/desktop/web/*` |
| **Round 1 P0** | API Key 安全凭据（Env / macOS Keychain / `0o600` 文件）、旧明文迁移、日志脱敏与备份/`.lyrapack` 清洗 | **已实现且已测试** | `src/lyraforge/secrets.py`, `library/{store,packaging}.py`, `tests/unit/test_secrets_and_security.py` |
| **Round 1 P0** | Windows Credential Manager (`advapi32.dll` `CredReadW`/`CredWriteW`/`CredDeleteW`) | **已实现但未完成真实环境验收** | `src/lyraforge/secrets_win32.py`；macOS 端已隔离依赖并通过分层测试，Windows 真机存取待验证 |
| **Round 1 P1** | 隔离 Windows `SendInput` 驱动（`key_up` 成功后更新 `pressed` + 重试恢复）与前景焦点守卫 | **已实现但未完成真实环境验收** | `src/lyraforge/playback/windows/*`, `tests/unit/test_windows_playback.py`；`calibration.status="unverified"`，需 Windows 《原神》真机校准与切窗/ESC 实音验收 |
| **Round 1 P1** | 全库备份分阶段暂存、SQLite 完整性校验与故障自动回滚 + DNS 固定防 SSRF 直链下载 | **已实现且已测试** | `library/packaging.py`, `sources/url.py`, `tests/unit/test_lyrapack_and_m5.py`, `test_secrets_and_security.py` |
| **Round 2 P0** | GitHub Actions 双平台 CI（`pnpm@12.6.0` + `.gitattributes` 二进制保护 + Windows `LyraForge.exe` 强校验）与 CI 诊断脚本 `scripts/check_ci.py` | **已实现且已测试**（真机 `.exe` 启动待 Windows 验收） | [ci.yml](../.github/workflows/ci.yml), [.gitattributes](../.gitattributes), [check_ci.py](../scripts/check_ci.py)；基线提交 `1f2b34d` 在 Run `#44980488436` 三作业全绿；本轮 PR 与 merge 后 CI 将继续追验 |
| **Round 2 P1** | 规范化开放曲库许可分类器（`classify_license_url()`：剔除 `mit`/`gpl`/`local` 弱子串，拒收 `NoDerivatives` 与混合私有文件）及完整权利 provenance | **已实现且已测试** | `src/lyraforge/sources/{base,local,online}.py`, `tests/unit/test_license_and_quality.py` |
| **Round 2 P1** | 转录准确率（`TranscriptionAccuracy`）与编曲可演奏性（`score_scope=arrangement_vs_input_midi`）严格分离评价 | **已实现且已测试** | `src/lyraforge/music_core/scoring.py`, `scripts/eval_transcribers.py`, `apps/desktop/web/src/App.vue`, `tests/unit/test_license_and_quality.py` |
| **Round 2 P1** | 零依赖 `stdio` MCP Server（`lyraforge mcp`，10 工具、`MCPTaskRegistry` 取消与 `play_in_game` 强制门禁）与客户端 Skill/配置 | **已实现且已测试**（Codex / 独立 Antigravity CLI 待目标客户端环境运行验证） | `src/lyraforge/mcp/*`, `integrations/{claude-code,codex,antigravity}/*`, [AI_INTEGRATION.md](AI_INTEGRATION.md), `tests/unit/test_mcp_server.py`（含真实子进程 `stdio` 全链路测试 + 本机 `claude 2.1.267` `mcp add`/`get` 校验） |
| **Round 2 P1** | 公开产品主页版 [README.md](../README.md)、[DEVELOPMENT.md](DEVELOPMENT.md)、[MAINTAINER_WORKFLOW.md](MAINTAINER_WORKFLOW.md)、[SECOND_REVIEW_REPORT.md](SECOND_REVIEW_REPORT.md) 与 [AGENTS.md](../AGENTS.md) 规则持久化 | **已实现且已测试** | 已清除文档内全部本地目录绝对路径，`AGENTS.md` 为 38 行（≤120 行） |
| **Round 3 UI/UX** | Studio Dark 设计系统（`tokens.css` / `@layer` / `StudioIcon` / `ToastStack`）、6 视图独立工作区、DAW Piano Roll（缩放/吸附/标尺/拖拽/快捷键）、IME 防护与内置 MCP 配置页 | **已实现且已测试** | `apps/desktop/web/src/*`, [THIRD_REVIEW_UI_REPORT.md](THIRD_REVIEW_UI_REPORT.md), [assets/ui/](assets/ui/)；实时 FastAPI + Chrome CDP 12 次截屏 0 溢出 0 控制台报错 |
| **M2 / 音频** | 原生 WAV 提取标准化 + 内置单音 YIN 转谱（`builtin-mono`） | **部分实现** | 核心与任务取消可用；单音旋律 `F1=1.0`，多声部钢琴和弦 `F1=0.0`，真实复杂音频受纯单音算法限制 |
| **M2 / 外部 ML** | `ffmpeg` 非 WAV 音视频提取 + 隔离进程 `basic-pitch` / `dettato` 多音转录 | **因外部环境阻塞** | 适配器和环境变量协议已实现并通过 Mock 测试；当前开发机未安装 `ffmpeg`、`basic-pitch`、`dettato` |
| **M5 / 发行** | Windows 实体机运行 `LyraForge.exe` 冒烟、`原神` 21 键校准与正式 Stable Release | **未实现** | 需下载 CI 产物 `LyraForge-windows-x64` 后在 Windows 10/11 实体机完成验收 |

---

## 2. 最新实测结果

1. **GitHub Actions CI 验收**
   - `main` 基线（`1f2b34db8dc6911d33ddd4fc9b4f56f7b25475db`）→ [Run #44980488436](https://github.com/PariyaProject/LyraForge/actions/runs/44980488436)：**`success`**（三作业全绿并产出 `LyraForge-windows-x64`）。
   - [PR #1](https://github.com/PariyaProject/LyraForge/pull/1) 合入提交（`a872f664c5e9dd0b05976bcccc1e9260803c0ba2`）→ [Run #45003219667](https://github.com/PariyaProject/LyraForge/actions/runs/45003219667)：**`success`**（`Test (macos-latest)`、`Test (windows-latest)`、`Build Windows Bundle (PyInstaller)` 全绿）。
2. **本地完整门禁（`pnpm --dir apps/desktop/web install --frozen-lockfile && make check`）**
   - `pnpm v12.6.0` frozen-lockfile 一致（`42ms`）
   - `uv run ruff check .` → `All checks passed!`
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **117 passed, 1 warning in 24.63s**，总覆盖率 **87.13%**（5228 语句 / 1298 分支）
   - `vitest run` → **Test Files 4 passed (4), Tests 6 passed (6)**（含 `App.spec.ts`、`PianoRollInteractions.spec.ts`、`PianoRollEditor.spec.ts`、`LyreKeyboard.spec.ts`）
   - `vue-tsc --noEmit && vite build` → 构建成功（`787ms`，`152.57 kB` JS / `19.86 kB` CSS）
   - `make smoke` → 退出码 `0`（DryRun 48 动作，0 残留按键）
3. **无头 Chrome + 实时 FastAPI 视觉/响应式复核**
   - 6 视图（`1440×900`）+ 紧凑 (`1024×720`) + 宽屏 (`1920×1080`) 共 12 次 CDP 采集全部 `docScrollW <= winInnerW`、`mainScrollW == mainClientW` 且 `console_errors = []`。
4. **分离式转谱与编曲质量基准（`uv run python scripts/eval_transcribers.py`）**
   - `ffmpeg_available = false`，`basic-pitch.available = false`，`dettato.available = false`，`builtin-mono.available = true`
   - `builtin-mono` 实测数据：
     - `solo_melody`: 转谱 F1 `1.0` | 端到端召回 `1.0` | 相对转录 MIDI 适配分 `100.0` | `166.86 ms`
     - `polyphonic_piano_chords`: 转谱 F1 `0.0` | 端到端召回 `0.0` | 相对转录 MIDI 适配分 `100.0` | `139.19 ms`
     - `dense_multi_register`: 转谱 F1 `0.3333` | 端到端召回 `0.1875` | 相对转录 MIDI 适配分 `100.0` | `148.4 ms`
     - `fixture_c_major_scale_wav` (自制 MIDI 渲染 WAV): 转谱 F1 `1.0` | 端到端召回 `1.0` | 适配分 `100.0` | `205.06 ms`
     - `fixture_chords_type1_wav` (自制 MIDI 渲染 WAV): 转谱 F1 `0.1818` | 端到端召回 `0.1429` | 适配分 `91.98` | `677.71 ms`
