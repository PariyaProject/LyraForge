# LyraForge

**将 MIDI 和音频转换为游戏内自由演奏乐器可用的曲谱。**

LyraForge 是一款基于 **GNU GPL-3.0** 协议开源的跨平台桌面音乐转谱与游戏乐器编曲工作台，面向《原神》PC 版大世界中的**自由乐器演奏界面**（非下落式音游脚本）。你可以导入 MIDI 或音频、适配游戏乐器 21 键范围、在交互式 Piano Roll 中试听与微调，并保存到本地曲库或导出分享。

![LyraForge 工作台实时渲染截图](docs/assets/lyraforge-workbench.png)

> 查看全套 6 视图实机截图：
> [首页](docs/assets/ui/home.png) ·
> [本地曲库](docs/assets/ui/library.png) ·
> [AI 转谱](docs/assets/ui/transcribe.png) ·
> [编曲工作室 & Piano Roll](docs/assets/ui/studio.png) ·
> [试听与演奏](docs/assets/ui/playback.png) ·
> [设置与 MCP 接入](docs/assets/ui/settings.png)

---

## 核心功能

- **六视图 Studio Dark 桌面工作台**：固定底部全局试听传输栏支持跨视图持续试听 WAV 并随时暂停、继续与急停，整合首页向导、本地曲库、AI 转谱、Piano Roll 工作室、演奏控制台与设置/MCP 接入页面。
- **多格式曲谱与媒体导入**：原生支持本地 `.mid` / `.midi` 与 `.wav`；在本机安装 `ffmpeg` 后可扩展提取 `.mp3` / `.flac` / `.m4a` / `.ogg` / `.mp4` / `.mkv` / `.webm` 等格式；支持由用户明确确认后检索 Internet Archive 开放许可条目或通过公开直链导入合法素材。
- **音频转谱与独立评价**：内置零外部依赖单音识别引擎（`builtin-mono` YIN）用于干净独奏旋律，并支持接入本地隔离的开源多音转录引擎（`basic-pitch` / `dettato`）；编曲报告将“可演奏适配度”与“转录还原度”严格分开展示，避免无参考真值时产生误导。
- **面向游戏乐器的智能编曲**：内置**风物之诗琴**（21 键）与**镜花之琴**（21 键）预设，支持主旋律识别与优先保留、自动移调寻优、八度折叠、半音策略调整以及柱式和弦自动琶音。
- **DAW 级 Piano Roll 编辑与离线 WAV 试听**：提供 21 键位热力图、时间轴缩放、网格吸附、拖拽调整音高与拍点、点击增删音符、撤销/重做与版本对比，并利用纯 Python 拨弦合成器离线渲染 WAV，在不打开游戏的情况下即可试听效果。
- **本地曲库、`.lyrapack` 分享与安全备份**：内置 SQLite 曲库，支持精确标签筛选、收藏与版本分支；支持导出标准 MIDI、`performance.json`、强制确认版权且不包含原始音频或个人凭据的 `.lyrapack` 分享包，以及支持原子切换与故障自动回滚的全库 ZIP 备份恢复。
- **安全游戏演奏控制（Windows 实验性）**：仅面向大世界自由演奏界面，采用准备/授权两步确认机制、前景窗口焦点校验与 `Esc` 紧急停键全松键，不读取、挂钩或修改游戏内存；macOS 下默认使用零按键的 `DryRun` 模拟模式。
- **无需 API Key 的三层 AI / MCP 集成**：
  1. **完全离线模式**：所有音乐处理、编曲、试听及内置规则指令解析均可零配置、零联网本地运行，无需购买任何大模型 API Key。
  2. **MCP + Skill 接入**：通过标准 `stdio` 协议运行 `lyraforge mcp`，供你自己的 Claude Code、Codex CLI 或 Antigravity 会话安全编排转谱与编曲；敏感工具 `play_in_game` 默认拦截，绝不会绕过桌面确认自动向游戏发送按键。配置说明见 [AI 与 MCP 集成手册](docs/AI_INTEGRATION.md)。
  3. **可选 HTTP LLM 接入**：如需在桌面端连接本地 Ollama 或私有 OpenAI-compatible 接口，可在设置页配置，API Key 优先写入系统凭据库而不落明文。

---

## Quick Start

### Windows 10/11 便携预发行版（免安装 Python / Node）

- **最新开发构建（Pre-release，实验性）**：[Latest Dev Pre-release (`dev-latest`)](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest)（查看全部历史预发行与正式版本请前往 [Releases](https://github.com/PariyaProject/LyraForge/releases)）。
- 下载页面内的 `LyraForge-dev-*-windows-x64.zip` 与 `SHA256SUMS.txt`，校验哈希后解压运行（请保持 `LyraForge.exe` 与 `_internal\` 位于同一解压目录）：

```powershell
Get-FileHash .\LyraForge-dev-*-windows-x64.zip -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
.\LyraForge\LyraForge.exe --self-check --check-gui
.\LyraForge\LyraForge.exe
```

- 需要 Microsoft Edge WebView2 Runtime（Windows 11 已内置；Windows 10 请安装 Evergreen Runtime）。
- 需要 `ffmpeg` / 多音转谱引擎时，无需手工配置：桌面 **设置 →「外部工具与转谱引擎」** 点「安装」即可（应用内下载并校验，安装到用户目录，不改系统环境变量）；命令行等价入口为 `lyraforge tools install`。
- 若双击后没有出现窗口，启动失败详情会写入 `%LOCALAPPDATA%\LyraForge\logs\startup.log`，同时弹出原生错误对话框；提交 Issue 时请附上该日志。

### 从源码运行（macOS Apple Silicon / Windows）

前置环境：Python `3.11` 或 `3.12`、[`uv`](https://docs.astral.sh/uv/)；运行桌面前端还需 Node.js `22+` 与 `pnpm`（`12.6.0`）。

```bash
# 1. 克隆仓库并安装依赖（--extra desktop 用于启动桌面应用窗口）
git clone https://github.com/PariyaProject/LyraForge.git
cd LyraForge
uv sync --extra desktop

# 2. 快速体验命令行：查看内置乐器，并导入示例 MIDI
uv run lyraforge profiles list
uv run lyraforge import tests/fixtures/midi/chords_type1.mid --title "Chords Demo"

# 3. 构建前端并启动桌面工作台
pnpm --dir apps/desktop/web install --frozen-lockfile
pnpm --dir apps/desktop/web build
uv run --extra desktop lyraforge desktop
```

如果你只想以 `stdio` MCP Server 形式连接现有 AI 客户端：

```bash
uv sync
uv run lyraforge mcp
```

更多 CLI 命令、测试门禁、Windows 便携打包以及外置 `ffmpeg` / `basic-pitch` / `dettato` 配置方式，请查看 [开发者文档](docs/DEVELOPMENT.md)。

---

## 平台兼容与使用限制

| 平台 | 转谱、编曲、Piano Roll、曲库与 MCP | 游戏内自由演奏模式 |
|---|---|---|
| **macOS Apple Silicon** | 支持 | 仅支持 **DryRun** 虚拟试跑，不触发系统级按键 |
| **Windows 10/11 x64** | 支持 | **实验性功能**（键位校准与游戏内实机演奏尚未完成验证） |

开始使用前请了解以下真实限制：

- **复杂音频转谱存在客观上限**：内置 `builtin-mono` 仅适合干净的单音独奏；流行歌曲、人声与伴奏混音或密集多声部和弦音频需要用户自行配置 `ffmpeg` 及隔离的开源多音引擎（`basic-pitch` 或 `dettato`），并在 Piano Roll 中人工校音调整，无法保证从复杂混音一键还原完整原曲。
- **外置媒体与识别模型需额外准备**：出于许可证与体积考虑，仓库不捆绑 `ffmpeg` 与神经网络权重文件。
- **游戏键盘自动化风险**：Windows 游戏内演奏仅在用户主动触发并保持游戏前台窗口时发送常规扫描码输入；**任何第三方自动按键工具均不能保证 100% 账号零风险**，请自行遵守游戏服务条款与适用法规，切勿用于下落式音游活动或任何合规受限场景。

---

## Documentation

| 文档 | 内容说明 |
|---|---|
| [开发者文档](docs/DEVELOPMENT.md) | 完整 CLI 工具链、外置识别引擎安装、安全架构要点与 Windows 打包 |
| [AI 与 MCP 集成手册](docs/AI_INTEGRATION.md) | 无需 API Key 的 MCP Server、`integrations/` 模板及权限边界说明 |
| [开发进度总览](docs/PROGRESS.md) | 各功能模块真实成熟度分类、阶段推进与已观测记录 |
| [测试报告与基准](docs/TEST_REPORT.md) | 本地与双平台检查结果、覆盖率、五类转谱评测基准与真机待办清单 |
| [产品路线图](docs/ROADMAP.md) | 里程碑完成情况与下一阶段产品演进方向（转谱、Windows 真机、交付体验） |
| [变更记录](CHANGELOG.md) | 面向用户的版本与功能更新记录 |
| [系统架构设计](docs/ARCHITECTURE.md) | 跨平台核心分层、桌面宿主及 Windows 驱动隔离原则 |
| [项目维护工作流](docs/MAINTAINER_WORKFLOW.md) | 开发分支、PR、GitHub CI 检查与发布门禁规范 |

---

## License & Contributing

- **开源协议**：本项目基于 **GNU General Public License v3.0 (GPL-3.0)** 开源，完整条款见 [LICENSE](LICENSE)，第三方组件与授权审计见 [docs/LICENSE_AUDIT.md](docs/LICENSE_AUDIT.md)。
- **版权与隐私声明**：请仅导入、转谱和分享你拥有合法使用权限的音频或 MIDI 素材；在线开放目录的元数据由外部来源填写，使用前请自行核实词曲、录音与改编授权。
- **参与贡献**：欢迎提交 [Issues](https://github.com/PariyaProject/LyraForge/issues) 与 Pull Request。提交改动前请先阅读 [AGENTS.md](AGENTS.md) 与 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)，切勿上传 API Key、个人 OAuth 凭据或受版权保护的音频文件。

*LyraForge 为独立开源社区项目，与米哈游 / HoYoverse 及各第三方 AI 提供商无官方关联。*
