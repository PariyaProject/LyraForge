# LyraForge 开发进度总览（Progress）

> **更新时间**：2026-11-22  
> **当前阶段**：**M0–M5 本机 macOS Apple Silicon 可验证范围已全部完成（待 Windows 真机《原神》校准实音验收、GitHub Actions Windows 打包流水线实跑与可选外部 ML 引擎实测）**  
> **主要开发环境**：macOS Apple Silicon（Mac mini M4, Python 3.11.13, Node v24.14.0, pnpm 12.6.0）  
> **目标运行平台**：Windows 10/11 x64（核心、曲库、FastAPI 与 Vue 3 + PyWebView 双平台兼容）

---

## 1. 里程碑与需求对照（F01–F21）

| 里程碑 | 功能编号 | 模块 / 能力 | 当前状态 | 关键依据 / 备注 |
|---|---|---|---|---|
| **M0** | F01–F03 | 仓库骨架、许可审计、MIDI 导入/TempoMap/Arranger/Profile、`performance.json`、DryRun | **已完成** | `src/lyraforge/music_core/*`, `src/lyraforge/instruments/*`, `docs/LICENSE_AUDIT.md`, `docs/adr/0001`, `docs/adr/0002` |
| **M1** | F06 | SQLite (WAL) 曲库持久化、SHA256 去重、多版本不覆盖、设置表与重启恢复 | **已完成** | `src/lyraforge/library/*`（迁移 v1→v2，`export_arrangement` 支持 MIDI/JSON 导出） |
| **M1** | F05 | 本地离线试听（纯 Python 拨弦 WAV 合成，无未授权游戏采样） | **已完成** | `src/lyraforge/preview/synth.py` + CLI `preview` + UI `<audio>` |
| **M1** | F04 | 跨平台调度器 (`Player`) + `DryRunDriver` + 隔离的 Windows `SendInput` 与焦点守卫 | **代码与 Mock 测试已完成；Windows 真机待验收** | `src/lyraforge/playback/windows/*`, `factory.py`；macOS 默认安全运行 DryRun |
| **M1** | F04–F06 | 本地 FastAPI 服务 (`127.0.0.1` + 会话 Token) + Vue 3 + Vite + PyWebView 双平台桌面壳 | **已完成** | `src/lyraforge/api/*`, `src/lyraforge/desktop/*`, `apps/desktop/web/*` |
| **M2** | F07 | 本地音频/视频导入与提取（原生 WAV 标准化 + 受控 FFmpeg 子进程） | **原生 WAV 已实测；FFmpeg 子进程 Mock 已验证** | `src/lyraforge/media/extract.py`（本机未装 `ffmpeg`，真实 MP3/MP4 需安装后测） |
| **M2** | F08, F09 | 插件化音频转 MIDI（`builtin-mono` YIN + 隔离进程 `basic-pitch` / `dettato` 适配器）、清理与导出 | **核心流水线已完成；隔离 ML 模型未在本机安装** | `src/lyraforge/transcribers/*`, `music_core/{cleanup,midi_export}.py`；`basic-pitch`/`dettato` 已按 ADR-0001 隔离并完成 Mock 测试 |
| **M2** | F14, F15 | `raw.mid` / `cleaned.mid` / `arrangement.mid` / `performance.json` 版本树与异步可取消转录任务 | **已完成** | `api/job_service.py`（`GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel`）、`export.mid/.json` |
| **M3** | F09, F13, F15 | 镜花之琴预设、主旋律识别与优先保留、柱式和弦琶音、多维质量评分、A/B 对比、Piano Roll 编辑与 Undo/Redo | **已完成** | `instruments/data/genshin.floral_zither.v1.json`, `music_core/{arranger,scoring}.py`, `library/schema.py` v3 (`parent_id`/`score`/`user_vote`/`label`), `PianoRollEditor.vue`, `POST /v1/jobs/arrange-ab`, `POST /v1/arrangements/{id}/{edit,favorite,vote}` |
| **M4** | F10–F12 | 关键词检索、合法来源适配器（SSRF/授权守卫）、可配置 LLM Provider 与 AI Agent 编排/自优闭环 | **已完成** | `src/lyraforge/sources/{base,local,url}.py`, `src/lyraforge/agent/{llm,orchestrator}.py`, `GET /v1/agent/tools`, `POST /v1/agent/run`, CLI `lyraforge agent`, 前端智能编曲助手与授权拦截 |
| **M5** | F14, F21 | `.lyrapack` 分享包（默认不含原始音频）、标签收藏筛选、备份恢复与 Windows PyInstaller 发行配置 | **已完成（Windows 构建产物与真机实音待目标环境验收）** | `src/lyraforge/library/packaging.py`, `POST /v1/arrangements/{id}/export.lyrapack`, `POST /v1/imports/lyrapack`, `GET /v1/library/backup.zip`, CLI `pack` / `library backup`, `packaging/lyraforge.spec`, `scripts/build_windows.ps1`, `.github/workflows/ci.yml` (`package-windows`) |

---

## 2. 本轮实测结果（真实运行记录，未虚构）

测试运行环境：`macOS Darwin (Apple Silicon)`，`Python 3.11.13`，执行命令与实测结果如下：

1. **静态检查 (`uv run ruff check .`)**
   - 结果：`All checks passed!`（0 错误）
2. **Python 单元、分层门禁与集成测试 (`uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80`)**
   - 结果：**104 passed, 1 warning in 21.25s**（Starlette 关于 `httpx` 的 `StarletteDeprecationWarning`）
   - 总分支/语句覆盖率：**91.10%**（门槛 ≥80%）
   - 覆盖范围：M0–M3 全量回归 + M4 合法来源适配器（本地库/目录 + SSRF/大小/未授权拦截直链下载）、离线规则与 OpenAI-compatible LLM 解析、`AgentOrchestrator`（自动转录 + 质量低分重编择优 + 严禁 `playback.start` + 外网授权二次确认）+ M5 `.lyrapack` 版权门槛/不打包原始音频/恶意 ZIP 防护（路径穿越/软链/超限/校验篡改）、标签收藏筛选、库 ZIP 备份恢复、FastAPI `/v1/agent/*` `/v1/imports/lyrapack` `/v1/library/backup.zip` 与 CLI `agent` / `pack` / `library backup`。
3. **Vue 3 前端测试 (`pnpm --dir apps/desktop/web test`)**
   - 结果：**Test Files 3 passed (3), Tests 5 passed (5)**（`LyreKeyboard.spec.ts`、`PianoRollEditor.spec.ts`、`App.spec.ts`，0 报错/stderr 干净）
4. **Vue 3 TypeScript 编译与打包 (`pnpm --dir apps/desktop/web build`)**
   - 结果：`vue-tsc --noEmit && vite build` 成功（640ms，输出 `dist/index.html`、`dist/assets/*`）
5. **CLI 端到端冒烟 (`make smoke`)**
   - 结果：退出码 0（含 `genshin.windsong_lyre.v1` 与 `genshin.floral_zither.v1` 展示、`inspect`、`arrange`、`validate`、`preview`、`playback dry-run`、库导入/编曲/试听/DryRun 全通）
6. **本地服务真实启动校验（`uvicorn` 绑定 `127.0.0.1` 随机端口 + `apps/desktop/web/dist`）**
   - 结果：`LIVE_HTTP_CHECK_OK`（端口 `55801`），`/health`、`GET /`（注入 `__LYRAFORGE_CONFIG__` 与 Token）、`GET /v1/profiles`、`GET /v1/agent/tools`、`GET /v1/library/backup.zip` 全部返回 `200 OK` 并安全退出。

---

## 3. 明确的环境阻塞与待真机验收项

以下项目受限于当前设备为 **macOS Apple Silicon（无 Windows 游戏环境、未安装 FFmpeg / Basic Pitch / dettato）**，**不得**宣称已通过实机或外部模型验证：

1. **Windows 10/11 + 《原神》真机独立验收（M1-D / M5）**：
   - `genshin.windsong_lyre.v1` 与 `genshin.floral_zither.v1` 当前 `calibration.status` 均为 `unverified`。
   - `WindowsKeyboardDriver` (`SendInput`) 与 `ForegroundWindowGuard` (`GetForegroundWindow`/`GetWindowTextW`) 需在 Windows PC 上对照《原神》自由演奏界面完成 21 键实音校准、焦点离开急停、ESC 紧急停止、非管理员权限及帧率负载实测。
2. **GitHub Actions `windows-latest` 流水线与便携包试运行**：
   - 已配置 [.github/workflows/ci.yml](file:///Users/wuzhao/Program/Github/lyraforge_starter/.github/workflows/ci.yml)（`macos-latest` + `windows-latest` 测试 + `package-windows` PyInstaller 打包）与 [scripts/build_windows.ps1](file:///Users/wuzhao/Program/Github/lyraforge_starter/scripts/build_windows.ps1)，待在 Windows 环境或推送 GitHub 后触发真实 runner 验证便携 `.exe`。
3. **外部多媒体与神经网络转录模型实测（M2 扩展）**：
   - 本机未安装 `ffmpeg`（MP3/MP4/MKV 等非 WAV 提取需用户安装 FFmpeg 后实测）。
   - `basic-pitch` 与 `dettato` 隔离适配器已就绪并通过子进程 Mock 验证，真实人声/复杂混音曲目的识别准确率需按需在独立 Python 环境中安装模型权重后评估。

---

## 4. 后续验收入口（Windows 真机与打包）

1. **GitHub Actions Windows 打包**：推送至 GitHub 触发 `package-windows` 下载 `LyraForge-windows-x64`，或在 Windows 10/11 直接运行 `./scripts/build_windows.ps1` 生成便携版。
2. **Windows 真机验收**：对照 [TEST_PLAN.md](file:///Users/wuzhao/Program/Github/lyraforge_starter/docs/TEST_PLAN.md) 第 4 节完成《原神》风物之诗琴/镜花之琴实音校准、切窗停键、ESC 全松键与端到端实测后更新 `calibration.status`。
