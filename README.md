# LyraForge

> AI 音乐转谱与游戏乐器自动演奏一体化工作台（以 **GNU GPL-3.0** 开源；**macOS Apple Silicon 可验证范围已完成并经过安全/可靠性加固**：跨平台音乐核心与多维质量评分、风物之诗琴/镜花之琴、SQLite v3 曲库与 Piano Roll 编辑、System Keychain/凭据隔离、分阶段原子备份恢复、DNS 固定防 SSRF 开放曲库检索与离线/LLM Agent 编排、`.lyrapack` 分享包、Vue 3 + PyWebView 桌面端；**Windows 10/11 真机《原神》校准实音演奏、Windows 便携包真机运行、GitHub Actions 修复后远端重跑及可选外部 FFmpeg/Basic Pitch/dettato 模型实测待在对应环境验收**）

- **主要开发环境**：macOS Apple Silicon（Mac mini M4）
- **首发目标运行平台**：Windows 10/11 x64（支持《原神》PC 版大世界自由演奏；核心模块、曲库、Agent 与 Vue 3 + PyWebView 桌面壳跨平台兼容 macOS 与 Windows）
- **重要安全声明**：本软件不读取、不注入、不修改任何游戏内存或进程，不使用任何反作弊绕过手段；macOS 仅提供零系统按键的 `DryRunDriver`。第三方自动按键操作可能违反游戏条款，Windows 实音演奏强制要求用户两步显式授权、焦点窗校验与急停全松键，不可消除账号风险。

---

## 快速开始（macOS Apple Silicon / Windows 通用）

前置要求：Python `3.11`（或 `3.12`）、[`uv`](https://docs.astral.sh/uv/)，以及前端测试/打包所需的 Node.js + `pnpm`（`apps/desktop/web/package.json` 已通过 `packageManager` 固定为 `pnpm@12.6.0`）。

```bash
# 1. 安装/同步依赖（macOS 与 Windows 均适用，核心不含 Windows 专属依赖）
uv sync
pnpm --dir apps/desktop/web install --frozen-lockfile

# 2. 一键运行全量质检门禁（ruff + pytest 覆盖率>=80% + vitest + vite build + make smoke）
make check

# 或者分步运行：
uv run ruff check .
uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80
```

---

## M0 CLI 使用示例

> 以下示例使用本项目自制的无版权测试 MIDI（`tests/fixtures/midi/`）。

```bash
# 查看内置乐器配置
uv run lyraforge profiles list
uv run lyraforge profiles show genshin.windsong_lyre.v1

# 解析并检查 MIDI 摘要（支持 Type 0/1、多轨、Tempo 变化、损坏诊断）
uv run lyraforge inspect tests/fixtures/midi/chords_type1.mid

# 适配为风物之诗琴可演奏事件 JSON（可选输出质量分析报告）
uv run lyraforge arrange tests/fixtures/midi/chords_type1.mid \
  -o /tmp/chords_perf.json \
  --report /tmp/chords_report.json \
  --style balanced

# 校验生成的 performance.json Schema 与语义一致性
uv run lyraforge validate /tmp/chords_perf.json

# DryRun 模拟演奏（macOS/Windows 均不发送任何系统按键，可模拟中途停止释放全部按键）
uv run lyraforge playback dry-run /tmp/chords_perf.json --log /tmp/dryrun.jsonl
uv run lyraforge playback dry-run /tmp/chords_perf.json --stop-after-ms 1500

# M1-A / M1-B：导入本地曲库、生成多版本改编、离线 WAV 试听与记录 DryRun 会话
uv run lyraforge import tests/fixtures/midi/chords_type1.mid --title "Chords Demo" --tags demo,lyre
uv run lyraforge library list
uv run lyraforge library search "Chords"
uv run lyraforge library arrange <song_id> --style balanced
uv run lyraforge preview <arrangement_id> -o /tmp/preview.wav
uv run lyraforge playback dry-run <arrangement_id>

# 启动本地回环 FastAPI 服务（127.0.0.1 + 会话 Token）
uv run lyraforge serve --host 127.0.0.1 --port 8765 --token dev-token

# 构建前端并启动 PyWebView 双平台桌面应用（macOS WKWebView / Windows WebView2）
make web-setup
make desktop

# M2：查看转录引擎、评估合成基准、导入音频或转录为 MIDI
uv run lyraforge engines list
uv run python scripts/eval_transcribers.py
uv run lyraforge import /path/to/solo.wav --title "Solo WAV"
uv run lyraforge transcribe /path/to/solo.wav --engine builtin-mono -o /tmp/raw.mid --cleaned-out /tmp/cleaned.mid --arrange-out /tmp/perf.json
uv run lyraforge export <arrangement_id> --format midi -o /tmp/arrangement.mid

# M4：AI Agent 自然语言检索与自动编曲优化（默认离线规则解析，无需 Antigravity CLI；联网搜索开放曲库需 --allow-network）
uv run lyraforge agent "搜索《Chords Demo》转成镜花之琴主旋律并优化"
uv run lyraforge agent "搜索开放曲库 Clair de Lune 转成风物之诗琴曲谱" --allow-network

# M5：.lyrapack 分享包导出/导入（默认剔除原始音频与凭据）与全库备份（自动清洗敏感密钥与原子回滚恢复）
uv run lyraforge pack export <arrangement_id> -o /tmp/demo.lyrapack --confirm-rights
uv run lyraforge pack import /tmp/demo.lyrapack
uv run lyraforge library backup -o /tmp/lyraforge-backup.zip
```

### 安全存储、合法联网搜索与音频转谱说明

- **API Key 安全存储**：OpenAI-compatible LLM API Key 支持环境变量 `LYRAFORGE_LLM_API_KEY`，或通过 UI/API 保存至系统安全凭据库（macOS Keychain / Windows Credential Manager，无系统密钥环时回落至 `0o600` 权限独立密钥文件），不再明文保存于 SQLite。旧版明文配置会在初始化时自动迁移并清除，且完整库备份（`backup.zip`）、日志、错误堆栈与 `.lyrapack` 分享包均会剥离/脱敏敏感凭据。
- **合法联网检索与直链导入**：启用 `allow_network=True` 后，Agent 可通过 `OpenMusicCatalogSourceAdapter` 检索 **Internet Archive** 中的开放许可/公共领域音乐元数据（优先挑选 MIDI 并对其候选排序，缺失 MIDI 时下载音频自动转谱），或导入用户提供的外部直链；所有出站请求均经过 DNS 解析固定（防 DNS 重绑定 SSRF）、私有/回环/CGNAT IP 段拦截、重定向跳数上限与总耗时/体量上限保护，不绕过版权或 DRM。
- **音频转谱能力边界与可选外部引擎**：内置 `builtin-mono` 为纯 Python 离线 YIN 单音算法，在单音旋律基准下达到 `F1=1.0000`，但在复调和弦与双声部下准确率受限（见 `uv run python scripts/eval_transcribers.py` 实测）。如需处理非 WAV 视频（MP3/MP4/MKV）或复杂多声部混音，请按需安装 `ffmpeg` 以及独立的隔离转录环境并配置环境变量：
  - `LYRAFORGE_BASIC_PITCH_PYTHON` 或 `LYRAFORGE_BASIC_PITCH_BIN`（Spotify Basic Pitch, Apache-2.0）
  - `LYRAFORGE_DETTATO_PYTHON` 或 `LYRAFORGE_DETTATO_BIN`（dettato 多乐器转录, Apache-2.0）

### Windows 10/11 独立桌面版打包与运行

```powershell
# 在 Windows 10/11（无需管理员权限）生成便携目录 dist/LyraForge/LyraForge.exe
./scripts/build_windows.ps1
```

也可推送代码至 GitHub，触发 [ci.yml](file:///Users/wuzhao/Program/Github/lyraforge_starter/.github/workflows/ci.yml) 中的 `package-windows` 作业下载 `LyraForge-windows-x64` 构建产物（CI 构建结束后会显式校验 `dist/LyraForge/LyraForge.exe` 是否生成）。启动后进入《原神》大世界**自由演奏乐器界面**，先通过两步授权检查并完成 21 键校准后再开启真实按键演奏；切换窗口或按 Stop / ESC 会立即终止并释放所有按键（`WindowsKeyboardDriver` 仅在收到 `SendInput` 成功反馈或重试恢复后才移除按下状态）。

也可用 `make smoke` 一键运行完整 CLI 端到端冒烟流程。

---

## 仓库结构

```text
lyraforge_starter/
├─ AGENTS.md                  # Antigravity CLI 工作区规则
├─ pyproject.toml / uv.lock   # 跨平台锁定依赖 (mido, jsonschema, pytest, ruff)
├─ Makefile                   # macOS POSIX 优先开发常用命令
├─ .github/workflows/ci.yml   # GitHub Actions: macos-latest + windows-latest 测试与 Windows 打包
├─ packaging/lyraforge.spec   # PyInstaller Windows 便携桌面打包配置
├─ docs/
│  ├─ PROJECT_SPEC.md         # 产品需求与技术规格总纲
│  ├─ ARCHITECTURE.md         # 跨平台分层架构与 Windows 隔离边界
│  ├─ PROGRESS.md             # 实时进度、实测记录与环境边界清单
│  ├─ ROADMAP.md              # M0-M5 里程碑与下一步计划
│  ├─ LICENSE_AUDIT.md        # 上游参考仓库/模型权重/依赖许可证审计
│  ├─ REVIEW_FIX_REPORT.md    # 首轮 Code Review 修复与回归验收报告 (FIX-001 ~ FIX-009)
│  ├─ TEST_PLAN.md            # 自动测试与 Windows 真机验收清单
│  └─ adr/                    # 架构决策记录 (ADR-0001, ADR-0002)
├─ src/lyraforge/
│  ├─ errors.py               # 统一错误码 ErrorCode / LyraError
│  ├─ fs.py                   # 跨平台原子文件写与路径穿越防护
│  ├─ secrets.py              # 跨平台系统凭据存取（macOS Keychain / CredMan / 0o600 / Env）与脱敏
│  ├─ secrets_win32.py        # 隔离的 Windows Credential Manager (advapi32) 封装
│  ├─ cli.py                  # 命令行入口（转谱/编曲/Agent/分享包/服务/桌面）
│  ├─ music_core/             # 无头纯 Python 核心（MIDI 导入/清理/导出、TempoMap、Arranger、质量评分与 A/B 对比、Performance）
│  ├─ instruments/            # 内置乐器配置 JSON（风物之诗琴、镜花之琴，当前 unverified 待 Windows 校准）
│  ├─ media/                  # 跨平台 WAV 标准化与受控 FFmpeg 音视频提取
│  ├─ transcribers/           # 插件化音频转 MIDI（内置 YIN 单音引擎 + Basic Pitch / dettato 隔离适配器）
│  ├─ sources/                # 来源适配器（本地库/目录 + Internet Archive 开放曲库 + DNS 固定防 SSRF 直链下载）
│  ├─ agent/                  # 离线规则与可选 LLM Provider、Tool Allowlist、自动编曲自优 Agent
│  ├─ library/                # SQLite (WAL, v3) 曲库索引、`.lyrapack` 分享包、分阶段原子备份恢复与回滚
│  ├─ preview/                # 零外部依赖离线 WAV 试听合成器
│  ├─ api/                    # 本地 127.0.0.1 FastAPI 服务 + 会话 Token + 静态资源托管 + 授权播放控制
│  ├─ desktop/                # PyWebView 双平台桌面壳启动器
│  └─ playback/               # 跨平台调度器、DryRunDriver 与隔离的 windows/ SendInput 子包
├─ apps/desktop/
│  ├─ main.py                 # 桌面端 Python 启动入口
│  └─ web/                    # Vue 3 + TypeScript + Vite 工作台（Piano Roll、A/B 对比、Agent、分享包）
├─ scripts/
│  ├─ make_fixtures.py        # 重新生成自制回归 MIDI 测试集
│  ├─ eval_transcribers.py    # 转录引擎可用性探测与多场景合成音频基准评估
│  └─ build_windows.ps1       # Windows 便携端一键构建脚本
└─ tests/
   ├─ fixtures/               # 12 份有效 + 5 份损坏/不支持自制 MIDI 样例
   ├─ unit/                   # 单元测试 + AST 分层静态门禁测试
   └─ integration/            # Fixture 一致性与 CLI 端到端集成测试
```

---

## 平台分工与验收边界

| 能力模块 | macOS Apple Silicon (Dev) | Windows 10/11 x64 (Target) |
|---|---|---|
| `music_core` / MIDI / 编曲 / 曲库 / Agent | 原生运行 & 全量测试 | 原生运行 & CI 全量测试 |
| 桌面 UI (Vue 3 + PyWebView, M1+) | WKWebView / Cocoa 本地联调 | WebView2 目标发布 & CI 构建 |
| 自动演奏输出 | `DryRunDriver` 模拟与试听 | 独立 `lyraforge.playback.windows` (`SendInput`) |
| 《原神》21 键校准与真机演奏 | **不适用** | **需单独在 Windows 真机完成手动验收** |

---

## 开源许可（License）

本项目以 **GNU General Public License v3.0 (GPL-3.0)** 开源发布，完整许可文本见 [LICENSE](LICENSE)，第三方依赖与参考项目审计见 [docs/LICENSE_AUDIT.md](docs/LICENSE_AUDIT.md)。
