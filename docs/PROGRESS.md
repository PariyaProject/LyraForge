# LyraForge 开发进度总览（Progress）

> **更新时间**：2026-11-23  
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
| **Round 4 加固 / Alpha 验收** | 子进程临时文件防管道死锁 + `.webm`、`PlaybackView` Win32 检测修复、`VK_ESCAPE`/`PauseToken`/混合精密时钟、`windows_allowed_titles` + `POST /v1/library/restore`、MCP 并发取消 + 线程局部 SQLite、`ProxyHandler({})` + ZIP DOS 保留名拦截、`LyraForge.exe --self-check` CI 门禁、固定全局底部传输栏与 4 项交互 CDP 实测 | **已实现且已测试**（Windows《原神》真机校准与外置 ML 仍待实机验收） | [FOURTH_REVIEW_REPORT.md](FOURTH_REVIEW_REPORT.md), [TEST_REPORT.md](TEST_REPORT.md), [UI_REVIEW.md](UI_REVIEW.md), `tests/unit/test_round4_hardening.py`, `scripts/eval_transcribers.py` |
| **Round 5 深度 Review 加固** | MCP 统一协议/初始化校验与有界线程池 (`max_pending`、前中后无竞态取消、断连清理、`-32603`)；曲库恢复独占维护门控（暂停新任务、等待确认线程退出、`409 LIBRARY_BUSY`、SQLite WAL/锁校验与并发幂等写入）；子进程有界滚动日志与 `seek()` 读尾；SQLite JSON1 (`json_each` + `py_lower`) 精确标签分页查询；LLM `math.isfinite()` 有限数值解析 | **已实现且已测试** | [PR #4](https://github.com/PariyaProject/LyraForge/pull/4) 合入 `34f08ce`（[Run #45031231498](https://github.com/PariyaProject/LyraForge/actions/runs/45031231498) 全绿）；`src/lyraforge/{mcp,api,library,media,agent}/*`, `tests/unit/test_round5_review_fixes.py` |
| **Round 6 稳定性收敛加固** | 曲库恢复目录原子切换事务（`.restore-txn.json` + 只读/文件锁前置预检 + 故障保全快照与人工恢复指引 + 启动自动恢复）；`MCPTaskRegistry` `finished` 状态与活动任务零驱逐（满载返回可恢复 `LIMIT_EXCEEDED`）；全非转录 MCP 工具 (`search_music`/`import_media`/`arrange`/`evaluate`/`preview`/`save_to_library`/`export_score`) 与核心/来源/合成/入库路径协作式取消；子进程独立进程组/派生树清理（POSIX `killpg` + Windows `taskkill /T`/PowerShell 后代清扫）、孤儿管道防挂死与排空后无竞态清理 | **已实现且已测试**（Windows《原神》真机校准与外置 ML 仍待实机验收） | [PR #5](https://github.com/PariyaProject/LyraForge/pull/5) 合入 `e9570fa`（[Run #45040399874](https://github.com/PariyaProject/LyraForge/actions/runs/45040399874) 全绿）；`src/lyraforge/library/{packaging,store,__init__}.py`, `src/lyraforge/mcp/tools.py`, `src/lyraforge/music_core/arranger.py`, `src/lyraforge/preview/synth.py`, `src/lyraforge/sources/{local,url,online}.py`, `src/lyraforge/media/{subprocess_utils,extract}.py`, `src/lyraforge/transcribers/_subprocess.py`, `tests/unit/test_round6_review_fixes.py`, [TEST_REPORT.md](TEST_REPORT.md) |
| **Round 7 并发与文档收尾** | 并发试听取消防误删（`LibraryStore.render_preview()` 改用每请求独立临时 WAV + 互斥锁/Windows 重试原子发布 `atomic_replace_file` + 提交前/后与硬盘一致性保证）；`subprocess_utils.py` 终态清理与脱管进程树加固（POSIX `selectors` FIFO 排空防 `BufferedReader.read(4096)` 阻塞与线程泄漏、`_BoundedRotatingLog.read_tail()` 持锁快照、`_safe_terminate_process_tree()` 回退兜底、`reap_attempted` 时序修正、`stop_drain.set()` 先于最终 `join` 与先关闭日志再清理）；`packaging.py`/`mcp/tools.py`/`test_round6_review_fixes.py` 深度源码核验通过（未作多余重构）；规范化 [README.md](../README.md)、[CHANGELOG.md](../CHANGELOG.md)、[ROADMAP.md](ROADMAP.md) 与 [AGENTS.md](../AGENTS.md) 长期文档分工 | **已实现且已测试** | `src/lyraforge/{fs.py,library/paths.py,library/store.py,media/subprocess_utils.py}`, `tests/unit/test_round7_review_fixes.py`, [TEST_REPORT.md](TEST_REPORT.md) §8；历史审查档案：[REVIEW_FIX_REPORT.md](REVIEW_FIX_REPORT.md)、[SECOND_REVIEW_REPORT.md](SECOND_REVIEW_REPORT.md)、[THIRD_REVIEW_UI_REPORT.md](THIRD_REVIEW_UI_REPORT.md)、[FOURTH_REVIEW_REPORT.md](FOURTH_REVIEW_REPORT.md)、[UI_REVIEW.md](UI_REVIEW.md) |
| **Round 8 发行修复** | Windows 便携包 GUI 宿主缺失导致「双击无反应」：PyInstaller 补齐 `webview` / `clr` / `webview.platforms.edgechromium` 与 WebView2 + pythonnet payload，构建期 payload 断言、`--self-check --check-gui` 发布门禁、致命启动异常写入 `startup.log` 并弹出原生错误对话框、便携 ZIP `README.txt` 与归档校验 | **已实现且已测试**（本机 Windows 重建冻结包实测开窗；CI 门禁待推送后实测确认） | `packaging/lyraforge.spec`, `src/lyraforge/{cli,startup_report}.py`, `apps/desktop/main.py`, `scripts/release_helper.py`, `.github/workflows/ci.yml`, `tests/unit/test_desktop_startup.py`, [TEST_REPORT.md](TEST_REPORT.md) §10 |
| **M2 / 音频** | 原生 WAV 提取标准化 + 内置单音 YIN 转谱（`builtin-mono`） | **部分实现** | 核心与任务取消可用；单音旋律 `F1=1.0000`、钢琴主旋律+琶音 `F1=0.6667`，和弦 `F1=0.0000`、人声伴奏 `F1=0.2000`、多乐器混音 `F1=0.2222` |
| **M2 / 外部 ML** | `ffmpeg` 非 WAV 音视频提取 + 隔离进程 `basic-pitch` / `dettato` 多音转录 | **因外部环境阻塞** | 适配器和环境变量协议已实现并通过 Mock 测试；当前开发机未安装 `ffmpeg`、`basic-pitch`、`dettato` |
| **M5 / 发行** | Windows 便携 ZIP 自动预发行与 SemVer 正式 Tag 发布流水线；实体机运行 `LyraForge.exe` 冒烟、`原神` 21 键校准与正式 Stable Release | **部分实现**（自动化 ZIP 发布已完成，真机《原神》校准与正式 Release 待实机验收） | [.github/workflows/ci.yml](../.github/workflows/ci.yml) + [scripts/release_helper.py](../scripts/release_helper.py) 在双平台测试与解压 `--self-check --check-gui` 全绿后自动发布实验性 Pre-release（固定 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) + 不可变 `dev-<YYYYMMDD>-<sha7>`）与独立 `vX.Y.Z` 正式通道；真机 21 键校准仍按 [TEST_REPORT.md](TEST_REPORT.md) §5 待 Windows 10/11 实体机执行 |

---

## 2. 最新实测结果

1. **GitHub Actions CI 验收**
   - `main` 基线（`1f2b34db8dc6911d33ddd4fc9b4f56f7b25475db`）→ [Run #44980488436](https://github.com/PariyaProject/LyraForge/actions/runs/44980488436)：**`success`**（三作业全绿并产出 `LyraForge-windows-x64`）。
   - [PR #1](https://github.com/PariyaProject/LyraForge/pull/1) 合入提交（`a872f664c5e9dd0b05976bcccc1e9260803c0ba2`）→ [Run #45003219667](https://github.com/PariyaProject/LyraForge/actions/runs/45003219667)：**`success`**（`Test (macos-latest)`、`Test (windows-latest)`、`Build Windows Bundle (PyInstaller)` 全绿）。
   - Round 4 基准 `9123a950ea362e59e714fb6b4127fe6cb79a2212` → [Run #45006178921](https://github.com/PariyaProject/LyraForge/actions/runs/45006178921)：**`success`**；[PR #3](https://github.com/PariyaProject/LyraForge/pull/3) 合入提交（`051a222b10aa7a4dc175748ada8b42ec67b8c48a`）→ [Run #45009837274](https://github.com/PariyaProject/LyraForge/actions/runs/45009837274)：**`success`**；[PR #4](https://github.com/PariyaProject/LyraForge/pull/4) 合入提交（`34f08ce7045e415588a3352141819555e17bedba`）→ [Run #45031231498](https://github.com/PariyaProject/LyraForge/actions/runs/45031231498)：**`success`**；[PR #5](https://github.com/PariyaProject/LyraForge/pull/5) 合入提交（`e9570fa43da7176447a071ca002a783a8c3dd523`）→ [Run #45040399874](https://github.com/PariyaProject/LyraForge/actions/runs/45040399874)：**`success`**；[PR #6](https://github.com/PariyaProject/LyraForge/pull/6) 合入提交（`dda4ef7fd53e196f6064bcff26802b2e9f1eaef8`）→ [Run #45101013055](https://github.com/PariyaProject/LyraForge/actions/runs/45101013055)：**`success`**。
2. **本地完整门禁（`pnpm --dir apps/desktop/web install --frozen-lockfile && make check`）**
   - `uv run ruff check .` → `All checks passed!`
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **139 passed, 2 warnings in 41.56s**，总覆盖率 **86.52%**（6615 语句 / 1830 分支；含 `test_round7_review_fixes.py` 与 `test_release_workflow.py` 专项回归）
   - `vitest run` → **Test Files 4 passed (4), Tests 6 passed (6)**（含 `App.spec.ts`、`PianoRollInteractions.spec.ts`、`PianoRollEditor.spec.ts`、`LyreKeyboard.spec.ts`）
   - `vue-tsc --noEmit && vite build` → 构建成功（`775ms`，`158.80 kB` JS / `20.52 kB` CSS）
   - `make smoke` → 退出码 `0`（DryRun 48 动作，0 残留按键）
   - `uv run lyraforge desktop --self-check` → 退出码 `0`（`ok: true`, `profiles: 2`, `windows_modules_loaded: false`）
3. **无头 Chrome + 实时 FastAPI 视觉与交互复核**
   - `1440×900@1x`（6 视图）、`1440×900@2x` High-DPI、紧凑 (`1024×720`) 与宽屏 (`1920×1080`) 共 **14 次 CDP 采集**全部 `docScrollW <= winInnerW`、`mainScrollW == mainClientW`、`hasFooterTransport == true` 且 `console_errors = []`；4 项端到端前端点击交互全过。
4. **五类音频转谱与编曲分离式基准（`uv run python scripts/eval_transcribers.py`）**
   - `ffmpeg_available = false`，`basic-pitch.available = false`，`dettato.available = false`，`builtin-mono.available = true`
   - `builtin-mono` 实测（详见 [TEST_REPORT.md](TEST_REPORT.md) §3）：
     - `solo_melody`（单音旋律）: 转谱 F1 `1.0` | 主旋律 F1 `1.0` | 相对转录 MIDI 适配分 `100.0` | 端到端召回 `1.0` | `169.88 ms`
     - `solo_piano_arpeggio`（钢琴独奏主旋律+琶音）: 转谱 F1 `0.6667` | 主旋律 R `1.0` (F1 `0.5714`) | 适配分 `92.36` | 端到端总/主召回 `0.5455` / `1.0` | `137.61 ms`
     - `polyphonic_piano_chords`（和弦与多声部）: 转谱 F1 `0.0` | 适配分 `100.0` | 端到端召回 `0.0` | `134.39 ms`
     - `vocal_with_accompaniment`（人声伴奏混合）: 转谱 F1 `0.2` | 适配分 `90.91` | 端到端召回 `0.1` | `192.38 ms`
     - `multi_instrument_complex`（多乐器混音）: 转谱 F1 `0.2222` | 适配分 `96.65` | 端到端召回 `0.1667` | `161.66 ms`
     - `fixture_c_major_scale_wav` / `fixture_chords_type1_wav`: 转谱 F1 `1.0` / `0.1818` | 适配分 `100.0` / `91.98` | `208.6 ms` / `677.75 ms`
     - `pipeline_roundtrip`（音频导入→转录→编曲→试听→编辑→保存新版→再试听）: `ok = true`, `preview_wav_bytes = 155276`
5. **Windows 预发行包「双击无反应」根因定位与修复（2026-11-23，针对 `dev-latest` / `a8a42de`）**
   - 本机 Windows 实测：解压后双击 `LyraForge.exe` 无窗口，约 `1.0 s` 后退出码 `1`，stderr 仅 `error [SOURCE_UNAVAILABLE]: pywebview is not installed; install desktop extra with 'uv sync --extra desktop'`；同一 EXE 的 `--self-check` 却返回 `0`，说明旧门禁只校验 Web 资源与服务端，未校验 GUI 宿主。
   - 根因：`desktop/launcher.py` 以 `importlib.import_module("webview")` 动态导入 pywebview，spec 未列入 `hiddenimports`，导致 pywebview / pythonnet 的 `pyinstaller40` hook 从未加载，`_internal` 缺少 WebView2 互操作 DLL、`WebView2Loader.dll` 与 `Python.Runtime.dll`；`console=False` 又让错误无处可见。
   - 修复后本机重建冻结包：`--self-check --check-gui` 退出码 `0`（`gui_host.backend = edgechromium`，`version = 6.2.1`），实际启动观察到窗口标题 `LyraForge`，正常关闭退出码 `0`；`release_helper.py package` 生成的真实 ZIP（`18,591,276` bytes）通过新归档校验，解压后同一流程再次实测通过；`ruff check` 通过，`pytest` **150 passed**，总覆盖率 **85.86%**。详见 [TEST_REPORT.md](TEST_REPORT.md) §10。
   - 未覆盖：本机无 `pnpm`，前端 `vitest`/`vite build`/`make smoke` 未重跑；CI `windows-latest` 的 `--self-check --check-gui` 门禁需推送后实测。
