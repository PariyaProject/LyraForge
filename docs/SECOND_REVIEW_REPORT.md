# LyraForge 第二轮 Code Review 修复与自主维护验收报告

> **仓库地址**：`https://github.com/PariyaProject/LyraForge`  
> **起始基线（`main`）**：`1f2b34db8dc6911d33ddd4fc9b4f56f7b25475db`（[Run #44980488436](https://github.com/PariyaProject/LyraForge/actions/runs/44980488436) 三作业全绿）  
> **开发分支 / PR**：`feat/second-review-hardening-mcp-docs` → [PR #1](https://github.com/PariyaProject/LyraForge/pull/1)  
> **主代码与文档提交 SHA**：`a86a52f0cf8e0628d234314888266b10c4dc2605`  
> **PR CI 验证（`a86a52f`）**：[Run #45002653088](https://github.com/PariyaProject/LyraForge/actions/runs/45002653088)（`macos-latest`、`windows-latest`、`Build Windows Bundle (PyInstaller)` 全部 **`success`**）  
> **开源许可**：严格维持 **GNU General Public License v3.0 (GPL-3.0)**（见 [LICENSE](../LICENSE) 与 [LICENSE_AUDIT.md](LICENSE_AUDIT.md)）

---

## 一、逐项审查问题核对与修复证据

### 1. P0 — 远程仓库核查与 CI 自动诊断闭环

- **真实远端复核**：通过 `git fetch origin --prune`、`gh auth status`、`gh repo view` 与 `gh run list` 验证真实远端状态，识别历史失败 `44977619933` 已在 `1f2b34d` 修复并于 [Run #44980488436](https://github.com/PariyaProject/LyraForge/actions/runs/44980488436) 通过；本轮分支开发继续通过 PR 与 CI 实时门禁验证。
- **CI 诊断脚本与工作流手册**：
  - 新增 [scripts/check_ci.py](../scripts/check_ci.py)：依据 `HEAD` 或 `--sha` 精确匹配 GitHub Actions Run，支持 `--watch` 等待完成、结构化输出各 Job/步骤结果，并在非成功时调用 `gh run view --log-failed` 截取失败日志。
  - 在 [AGENTS.md](../AGENTS.md) 与 [docs/MAINTAINER_WORKFLOW.md](MAINTAINER_WORKFLOW.md) 固化“每次修改自动提交 → 推分支 → 建 PR → 实时跟踪真实 CI → 最多 3 轮自愈修复 → 合入并再验 `main` CI”的持久机制。

### 2. P1 — 开放曲库许可元数据严格解析与权利 provenance

- **缺陷核实**：此前 [src/lyraforge/sources/online.py](../src/lyraforge/sources/online.py) 的 `_is_open_license()` 通过弱子串（含 `mit`、`gpl`、`local` 等）判断开放版权，存在误判软件许可证文本、假冒域名、Query 参数注入及忽略 `NoDerivatives` 限制的风险。
- **修复实现**：
  - 新增 `classify_license_url()` 与 `LicenseClassification`：强制规范解析 `http(s)` URL，严格白名单匹配 `creativecommons.org` / `www.creativecommons.org` 下的 CC0 1.0、PDM 1.0、CC-BY / CC-BY-SA / CC-BY-NC / CC-BY-NC-SA 规范路径；明确标记 `CC-BY-ND` / `CC-BY-NC-ND` 为 `allow_derivative = False` 并禁止自动改编；任何软件许可、缺失字段、伪造域名或查询参数伪装统一返回 `license_status = "unknown"` 并拒收。
  - 在 `OpenMusicCatalogSourceAdapter.search()` 同步检查 `/metadata/<id>/files` 文件级字段：剔除 `private="true"` 或文件级显式非兼容许可，完整记录 `source_url`、`license_id`、`license_status`、`license_url`、`fetched_at` 及 `rights_scope_note`（声明词曲、录音、编曲、MIDI 权利独立，Archive 元数据可能误标）。
  - 扩展 [SourceCandidate](../src/lyraforge/sources/base.py) 与 [LocalLibrarySourceAdapter](../src/lyraforge/sources/local.py) 并导出工具；在 [test_license_and_quality.py](../tests/unit/test_license_and_quality.py) 覆盖 12 种反例与混合文件恶意元数据测试。

### 3. P1 — 转录准确率与编曲可演奏性分离评价

- **缺陷核实**：旧基准与评分字段易导致外部误解“多音钢琴和弦 `F1 = 0.0` 时 `overall_score = 100.0` 代表音频识别准确”。
- **修复实现**：
  - 在 [src/lyraforge/music_core/scoring.py](../src/lyraforge/music_core/scoring.py) 新增 `TranscriptionAccuracy`、`evaluate_transcription_against_reference()`、`evaluate_events_against_reference()` 与 `evaluate_arrangement_against_reference()`；在 `QualityBreakdown.to_json()` 增加 `"score_scope": "arrangement_vs_input_midi"`、`"arrangement_playability_score"` 与 `"subjective_listening_status": "unrated_manual_preview_required"`。
  - 更新 [scripts/eval_transcribers.py](../scripts/eval_transcribers.py)，增加自制已提交 MIDI 样例渲染 WAV 的闭环基准，并将输出清晰拆分为：
    1. `transcription_fidelity`（真值对照精确率、召回率、F1、节拍对齐率与平均误差毫秒）
    2. `arrangement_playability_vs_transcribed_midi`（相对输入 MIDI 的可演奏比例与适配分）
    3. `end_to_end_vs_reference`（最终产物事件相对于原参考真值的音高召回率与起音覆盖）
    4. `subjective_preview_quality`（`unrated_manual_listening_required`）
  - 桌面端 [App.vue](../apps/desktop/web/src/App.vue) 指标卡更名为 `编曲适配分 (相对输入 MIDI)`。
  - **实测基准输出**（`uv run python scripts/eval_transcribers.py`，当前环境 `ffmpeg=false`、`basic-pitch=unavailable`、`dettato=unavailable`）：

| 用例 | 来源 | 转谱 F1 | 端到端真值音高召回 | 相对转录 MIDI 适配分 | 耗时 (ms) |
|---|---|---:|---:|---:|---:|
| `solo_melody` | 合成多谐波单音 | **1.0000** | **1.0000** | 100.0 | 161.96 |
| `polyphonic_piano_chords` | 合成钢琴三和弦 | **0.0000** | **0.0000** | 100.0 | 133.73 |
| `dense_multi_register` | 合成双声部 | **0.3333** | **0.1875** | 100.0 | 142.36 |
| `fixture_c_major_scale_wav` | 自制 `c_major_scale.mid` 渲染 | **1.0000** | **1.0000** | 100.0 | 199.87 |
| `fixture_chords_type1_wav` | 自制 `chords_type1.mid` 渲染 | **0.1818** | **0.1429** | 91.98 | 664.98 |

### 4. P1 — 无需 API Key 的三层 AI 架构、MCP Server 与客户端接入

- **MCP Server 实现**：新增零外部依赖 `src/lyraforge/mcp/`（[__init__.py](../src/lyraforge/mcp/__init__.py)、[tools.py](../src/lyraforge/mcp/tools.py)、[server.py](../src/lyraforge/mcp/server.py)）并注册 CLI 子命令 `lyraforge mcp`（[cli.py](../src/lyraforge/cli.py)），支持 JSON-RPC 2.0 `stdio` 传输、`MCPTaskRegistry` 进度日志与 `notifications/cancelled` 取消、敏感密钥脱敏及 10 个类型化工具：
  - `search_music`、`import_media`、`transcribe`、`arrange`、`evaluate`、`preview`、`save_to_library`、`export_score`、`get_task_status`、`play_in_game`。
  - 安全敏感工具 `play_in_game` 严格返回 `blocked_requires_interactive_confirmation`（`executed=false`、`requires_user_confirmation=true`），AST 分层测试 `test_mcp_has_no_windows_input_imports` 确认 MCP 包绝不引入 Win32 按键接口。
- **客户端接入与条款合规**：
  - 提供 [integrations/claude-code/](../integrations/claude-code/)、[integrations/codex/](../integrations/codex/)、[integrations/antigravity/](../integrations/antigravity/) Skill 与配置示例，以及详细架构与官方条款合规表 [docs/AI_INTEGRATION.md](AI_INTEGRATION.md)。
  - 在 [App.vue](../apps/desktop/web/src/App.vue) 助手与设置面板明示基础功能**无需 API Key**、推荐使用 `lyraforge mcp`、HTTP LLM 仅作为可选高级配置。
  - **实测验证**：
    - `tests/unit/test_mcp_server.py` 真实 `subprocess.Popen` 启动 `python -m lyraforge.cli mcp` 完成全流程 `stdio` 管道交互并退出码 `0`。
    - 本机已安装 `claude 2.1.267` 在隔离临时目录中实跑 `claude mcp add -s project lyraforge -- uv run --directory <repo> lyraforge mcp` 及 `claude mcp get lyraforge` 通过，确认生成的 `.mcp.json` 与示例模板一致；Codex 与独立 Antigravity CLI 因本机未安装，如实标为配置待目标环境验证。

### 5. P1 & 持久化维护规则 — 公开 README、真实截图、仓库治理与临时文件清理

- **真实桌面工作台截图**：构建 Vue 前端并通过无头 Google Chrome 访问本地回环临时服务端捕获真实渲染截图 [docs/assets/lyraforge-workbench.png](assets/lyraforge-workbench.png)（271,152 字节，经人工视觉检查确认列表、统计卡、21 键分布与 Piano Roll 全部正常渲染）。
- **文档拆分与公开首页重写**：
  - 根目录 [README.md](../README.md) 重写为面向用户的产品主页（诚实 Alpha 说明、三步快速上手、音频转谱真实边界、无需 API Key 说明、平台状态、FAQ、GPL-3.0 声明）。
  - 开发者命令清单、打包、依赖结构下沉至 [docs/DEVELOPMENT.md](DEVELOPMENT.md)。
  - 清理 [docs/REVIEW_FIX_REPORT.md](REVIEW_FIX_REPORT.md) 中全部本地目录绝对路径；全仓库文档 `git grep` 确认零绝对路径泄露。
  - 通过 `gh repo edit` 更新 GitHub 仓库简介与 7 个 Topic（`genshin-impact`, `midi`, `music-transcription`, `mcp`, `vue3`, `python`, `lyre`）。
- **维护规则持久化与清理**：[AGENTS.md](../AGENTS.md) 精简持久化至 38 行（≤120 行），完整运维手册落盘 [docs/MAINTAINER_WORKFLOW.md](MAINTAINER_WORKFLOW.md)；已确认内容整合后删除临时文件 `LyraForge_第二轮Review与自主维护Goal.md`、`README_public_draft.md` 与 `docs/.DS_Store`。

### 6. P2 — 前期安全与可靠性回归核验

- 重跑 `test_secrets_and_security.py`、`test_lyrapack_and_m5.py`、`test_windows_playback.py` 与新增 `test_license_and_quality.py`、`test_mcp_server.py`，全量通过；Windows 真实键盘输出与 Credential Manager 依旧严格标记为 `unverified`。

---

## 二、验证汇总

1. **本地全量门禁（`pnpm --dir apps/desktop/web install --frozen-lockfile && make check`）**
   - `uv run ruff check .` → `All checks passed!`
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **117 passed, 1 warning in 23.97s**，总覆盖率 **87.13%**（5228 语句 / 1298 分支）
   - `pnpm --dir apps/desktop/web test` → **Test Files 3 passed (3), Tests 5 passed (5)**
   - `pnpm --dir apps/desktop/web build` → `vue-tsc --noEmit && vite build` 成功（`602ms`）
   - `make smoke` → 退出码 `0`
2. **PR 远端 GitHub Actions CI（[Run #45002653088](https://github.com/PariyaProject/LyraForge/actions/runs/45002653088) on `a86a52f`）**
   - `Test (macos-latest, Python 3.11)`：`success`（`49s`）
   - `Test (windows-latest, Python 3.11)`：`success`（`1m47s`）
   - `Build Windows Bundle (PyInstaller)`：`success`（`1m8s`，生成 `dist/LyraForge/LyraForge.exe` 并上传 `LyraForge-windows-x64`）

---

## 三、未解决的运行环境限制与下一阶段最优先任务

- **尚未完成真机/外部环境验证的项目**：
  1. **Windows 10/11 真机《原神》自由演奏实音验收**：`genshin.windsong_lyre.v1` 与 `genshin.floral_zither.v1` 仍为 `calibration.status="unverified"`；`LyraForge.exe`、`secrets_win32.py` 真实 Credential Manager 读写与 `SendInput` 切窗/ESC 急停均需在实体 Windows PC 验证。
  2. **多声部神经网络转录依赖**：本机未安装 `ffmpeg`、`basic-pitch` 与 `dettato`。
  3. **独立 Codex CLI / Antigravity CLI 运行时连接测试**：示例配置与 Skill 已就绪，待在安装对应客户端的用户环境实际审批连接试跑。
- **下一阶段最优先任务**：
  1. **P0 真机验收与校准回填**：下载 CI Artifact `LyraForge-windows-x64` 在 Windows PC 实测非管理员启动、Windows 凭据管理器、以及《原神》风物之诗琴/镜花之琴 21 键逐键校准与焦窗保护实音，将核实后的映射数据更新至乐器 JSON。
  2. **P1 真实多音音频测试环境搭建**：在开发或测试机安装 `ffmpeg` 与隔离的 `basic-pitch` 环境，针对真实授权多音音乐补充 `eval_transcribers.py` 的真实识别基准数据。
  3. **P1 CI 增强与 Windows Bundle 运行时烟测**：在 `.github/workflows/ci.yml` 的 `package-windows` 步骤中尝试无头启动 `LyraForge.exe --version`（CLI 参数转发）验证便携二进制可启动性。
