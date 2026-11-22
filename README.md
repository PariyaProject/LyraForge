# LyraForge

> AI 音乐转谱与游戏乐器自动演奏一体化工作台（当前进度：**M0–M5 本机 macOS Apple Silicon 可验证范围已全部完成**：跨平台音乐核心与多维质量评分、风物之诗琴/镜花之琴、SQLite v3 曲库与 Piano Roll 编辑、音频提取/转录、离线与可配置 AI Agent 编排、`.lyrapack` 分享包与备份恢复、Vue 3 + PyWebView 桌面端、Windows `SendInput` 隔离驱动与 PyInstaller 打包脚本已就绪；**Windows 10/11 真机《原神》校准实音演奏、GitHub Actions Windows 打包流水线及可选外部 FFmpeg/Basic Pitch/dettato 模型实测待在对应环境验收**）

- **主要开发环境**：macOS Apple Silicon（Mac mini M4）
- **首发目标运行平台**：Windows 10/11 x64（支持《原神》PC 版大世界自由演奏；核心模块、曲库、Agent 与 Vue 3 + PyWebView 桌面壳跨平台兼容 macOS 与 Windows）
- **重要安全声明**：本软件不读取、不注入、不修改任何游戏内存或进程，不使用任何反作弊绕过手段；macOS 仅提供零系统按键的 `DryRunDriver`。第三方自动按键操作可能违反游戏条款，Windows 实音演奏强制要求用户两步显式授权、焦点窗校验与急停全松键，不可消除账号风险。

---

## 快速开始（macOS Apple Silicon / Windows 通用）

前置要求：Python `3.11`（或 `3.12`）与 [`uv`](https://docs.astral.sh/uv/)。

```bash
# 1. 安装/同步依赖（macOS 与 Windows 均适用，核心不含 Windows 专属依赖）
uv sync

# 2. 运行代码风格检查与全部测试（含分层门禁与覆盖率）
make lint
make test

# 或者在未安装 make 的环境直接运行：
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

# M2：查看转录引擎、导入音频或转录为 MIDI，并导出 MIDI/JSON
uv run lyraforge engines list
uv run lyraforge import /path/to/solo.wav --title "Solo WAV"
uv run lyraforge transcribe /path/to/solo.wav --engine builtin-mono -o /tmp/raw.mid --cleaned-out /tmp/cleaned.mid --arrange-out /tmp/perf.json
uv run lyraforge export <arrangement_id> --format midi -o /tmp/arrangement.mid

# M4：AI Agent 自然语言检索与自动编曲优化（默认完全离线规则解析，无需 Antigravity CLI）
uv run lyraforge agent "搜索《Chords Demo》转成镜花之琴主旋律并优化"

# M5：.lyrapack 分享包导出/导入（默认剔除原始音频并强制授权确认）与全库备份
uv run lyraforge pack export <arrangement_id> -o /tmp/demo.lyrapack --confirm-rights
uv run lyraforge pack import /tmp/demo.lyrapack
uv run lyraforge library backup -o /tmp/lyraforge-backup.zip
```

### Windows 10/11 独立桌面版打包与运行

```powershell
# 在 Windows 10/11（无需管理员权限）生成便携目录 dist/LyraForge/LyraForge.exe
./scripts/build_windows.ps1
```

也可推送代码至 GitHub，触发 [ci.yml](file:///Users/wuzhao/Program/Github/lyraforge_starter/.github/workflows/ci.yml) 中的 `package-windows` 作业下载 `LyraForge-windows-x64` 构建产物。启动后进入《原神》大世界**自由演奏乐器界面**，先通过两步授权检查并完成 21 键校准后再开启真实按键演奏；切换窗口或按 Stop / ESC 会立即终止并释放所有按键。

也可用 `make smoke` 一键运行完整 CLI 端到端冒烟流程。

---

## 仓库结构（M0）

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
│  ├─ TEST_PLAN.md            # 自动测试与 Windows 真机验收清单
│  └─ adr/                    # 架构决策记录 (ADR-0001, ADR-0002)
├─ src/lyraforge/
│  ├─ errors.py               # 统一错误码 ErrorCode / LyraError
│  ├─ fs.py                   # 跨平台原子文件写与路径穿越防护
│  ├─ cli.py                  # 命令行入口（转谱/编曲/Agent/分享包/服务/桌面）
│  ├─ music_core/             # 无头纯 Python 核心（MIDI 导入/清理/导出、TempoMap、Arranger、质量评分与 A/B 对比、Performance）
│  ├─ instruments/            # 内置乐器配置 JSON（风物之诗琴、镜花之琴，当前 unverified 待 Windows 校准）
│  ├─ media/                  # 跨平台 WAV 标准化与受控 FFmpeg 音视频提取
│  ├─ transcribers/           # 插件化音频转 MIDI（内置 YIN 单音引擎 + Basic Pitch / dettato 隔离适配器）
│  ├─ sources/                # 来源适配器（本地库/目录 + SSRF/授权守卫公网直链下载）
│  ├─ agent/                  # 离线规则与可选 LLM Provider、Tool Allowlist、自动编曲自优 Agent
│  ├─ library/                # SQLite (WAL, v3) 曲库索引、`.lyrapack` 分享包、备份恢复与原子存储
│  ├─ preview/                # 零外部依赖离线 WAV 试听合成器
│  ├─ api/                    # 本地 127.0.0.1 FastAPI 服务 + 会话 Token + 静态资源托管 + 授权播放控制
│  ├─ desktop/                # PyWebView 双平台桌面壳启动器
│  └─ playback/               # 跨平台调度器、DryRunDriver 与隔离的 windows/ SendInput 子包
├─ apps/desktop/
│  ├─ main.py                 # 桌面端 Python 启动入口
│  └─ web/                    # Vue 3 + TypeScript + Vite 工作台（Piano Roll、A/B 对比、Agent、分享包）
├─ scripts/
│  ├─ make_fixtures.py        # 重新生成自制回归 MIDI 测试集
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
