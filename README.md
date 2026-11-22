# LyraForge

**将 MIDI 和音频转换为游戏内乐器可以演奏的曲谱。**

LyraForge 是一款开源的桌面音乐转谱与游戏乐器编曲工作台，面向《原神》PC 版大世界中的**自由乐器演奏界面**（非下落式音游脚本）。你可以导入 MIDI 或音频、适配游戏乐器键位、在 Piano Roll 中试听微调并保存到本地曲库。

> **当前版本状态：Alpha / 正在积极开发。**  
> 跨平台核心转谱、编曲、Piano Roll 编辑、本地曲库、`.lyrapack` 分享与 MCP 工具链已在 macOS/Windows CI 通过自动化验证；但 **Windows 10/11《原神》真机 21 键实音校准与前景切窗演奏**、**正式稳定安装包发布** 以及 **Basic Pitch / dettato / FFmpeg 外置识别** 尚未在真机/全环境完成实测，请勿将其视为已完成真机验收的稳定版。

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

- **6 视图 Studio Dark 桌面工作台**：固定底部全局试听传输栏跨视图连续播放 WAV 与暂停/恢复/紧急停止，划分首页快速检索与 3 步引导、本地曲库、AI 转谱流水线、Piano Roll 工作室、两段授权演奏控制台与设置/MCP 接入页。
- **多格式导入**：支持本地标准 `.mid`/`.midi` 与 `.wav`；配置系统 `ffmpeg` 后可扩展提取 `.mp3`/`.flac`/`.m4a`/`.ogg`/`.mp4`/`.mkv`/`.webm` 等常见音视频格式；支持经用户明确授权的开放许可曲库（Internet Archive CC0 / PDM / CC-BY）或公开直链导入。
- **游戏乐器智能编曲**：内置**风物之诗琴**（21 键）与**镜花之琴**（21 键）预设，支持主旋律识别优先保留、自动移调寻优、八度折叠、半音处理与柱式和弦琶音。
- **分离式质量评估与 A/B 对比**：区分“**编曲对输入 MIDI 的可演奏适配度**”与“**音频转录对原曲的还原忠实度**”，避免无真值情况下的虚假高分误导。
- **DAW 级 Piano Roll 与离线试听**：交互式 21 键热力图、时间轴缩放（`50%–250%`）与网格吸附（`0–250 ms`）、指针直接拖拽调音与节拍、点击插音、撤销重做与纯 Python 拨弦 WAV 离线试听。
- **本地曲库与安全分享备份**：SQLite 曲库支持精确标签检索、收藏与版本管理；支持导出 MIDI、`performance.json`、强制版权确认且不带原始音频的 `.lyrapack` 分享包，以及桌面端/CLI（`lyraforge library restore`）分阶段校验、故障自动回滚的全库 ZIP 备份恢复。
- **无需 API Key 的三层 AI / MCP 能力**：默认离线运行，无需购买大模型 API Key；提供标准 `stdio` MCP Server（支持协议版本协商与并发请求取消）接入用户自有已登录客户端。

### 音频转谱能做到什么？（真实边界）

- 内置 `builtin-mono`（纯 Python YIN）在**干净单音旋律**合成基准中可达到 `F1 = 1.0000`，但在**多声部和弦**（如合成钢琴三和弦基准 `F1 = 0.0`）或双声部密集混音下存在算法上限。
- 真实流行歌、多乐器编配或人声伴奏混合音频无法只靠内置单音引擎直接“一比一还原”，通常需要在本地另行安装隔离的 Apache-2.0 多音转录模型（`basic-pitch` 或 `dettato`）+ `ffmpeg` 并在 Piano Roll 手动修音。

### 无需 API Key 的三层 AI / MCP 集成

LyraForge **不强制配置任何 OpenAI / Anthropic / Gemini API Key**：

1. **离线零 Key 模式**：所有导入、转谱、编曲、对比、试听、导出和内置规则指令解析（`RuleBasedLLMProvider`）均完全离线使用。
2. **MCP + Skill 模式（推荐给已订阅 AI 工具的用户）**：通过 `uv run lyraforge mcp` 启动本地 `stdio` MCP Server，向用户自己已登录的 **Claude Code**、**Codex CLI** 或 **Antigravity** 提供类型化工具与 [integrations/](integrations/) Skill；安全敏感工具 `play_in_game` 强制返回确认门禁，不会越权向游戏发送按键。详细合规矩阵见 [docs/AI_INTEGRATION.md](docs/AI_INTEGRATION.md)。
3. **可选 HTTP LLM 接口（高级设置）**：如需连接自托管 Ollama 或私有 OpenAI-compatible 端点，可在设置中开启；API Key 优先存入系统 Keychain / 凭据管理器，绝不明文保存在 SQLite 或备份/分享包中。

---

## 三步快速上手（源码运行）

前置环境：Python `3.11` 或 `3.12`、[`uv`](https://docs.astral.sh/uv/)；运行桌面前端还需 Node.js `22+` 与 `pnpm`（`12.6.0`）。

```bash
# 1. 克隆仓库并安装 Python 依赖
git clone https://github.com/PariyaProject/LyraForge.git
cd LyraForge
uv sync

# 2. 尝试查看内置乐器，或直接导入 MIDI 生成编曲与离线 WAV 试听
uv run lyraforge profiles list
uv run lyraforge import tests/fixtures/midi/chords_type1.mid --title "Chords Demo"

# 3. 构建前端并启动桌面工作台（或通过 stdio MCP 连接 AI 客户端）
pnpm --dir apps/desktop/web install --frozen-lockfile
pnpm --dir apps/desktop/web build
uv run lyraforge desktop
```

> 完整 CLI 命令大全、测试门禁、Windows PyInstaller 打包及外置 ML 引擎接入请查看 [开发者文档](docs/DEVELOPMENT.md)。

---

## 支持平台与真实状态

| 平台 | 音乐处理、编辑、曲库与 MCP | 游戏内键盘模拟演奏 |
|---|---|---|
| **macOS Apple Silicon** | 已实现，并通过本地及 GitHub CI 验证 | 仅支持 **DryRun** 模拟验证（不发送系统按键） |
| **Windows 10/11 x64** | 跨平台核心、凭据隔离与 PyInstaller 构建（含 `LyraForge.exe --self-check` 自检）已通过 Windows CI 检验 | **实验性隔离实现（`calibration.status = unverified`），真机《原神》校准与焦点守卫实音演奏待验证** |

---

## 常见问题（FAQ）

- **必须购买 API Key 才能使用吗？**  
  不需要。本地工作台与全部音乐核心完全离线可用；如已登录 Claude Code / Codex CLI / Antigravity，直接挂载 `lyraforge mcp` 即可通过现有客户端会话编排，无需另外填 Key。
- **可以用它自动打音游或后台静默演奏吗？**  
  不可以。LyraForge 仅面向《原神》大世界**自由演奏界面**，采用显式两步用户授权和前景窗口焦点守卫，切窗立即停键并全松键；不读写/注入游戏内存，也不使用反作弊绕过手段。
- **使用第三方自动按键是否绝对安全？**  
  没有任何第三方键盘自动化软件能保证 100% 账号零风险，请自行评估风险并遵守游戏服务条款与本地法律法规。

---

## 安全声明、开源许可与贡献

- **隐私与版权责任**：请仅导入、转谱与分享你拥有合法使用权限的音乐素材；开放平台的自填许可元数据不代表音乐词曲、录音与改编权全部自动授权。
- **开源许可证**：本项目采用 **GNU General Public License v3.0 (GPL-3.0)** 开源，完整文本见 [LICENSE](LICENSE)，第三方组件与参考项目审计见 [docs/LICENSE_AUDIT.md](docs/LICENSE_AUDIT.md)。
- **开发与贡献**：欢迎通过 [Issues](https://github.com/PariyaProject/LyraForge/issues) 反馈问题或提交 Pull Request。提交前请阅读 [AGENTS.md](AGENTS.md) 与 [docs/MAINTAINER_WORKFLOW.md](docs/MAINTAINER_WORKFLOW.md)，切勿附带 API Key、OAuth 凭据或受版权保护的原始音频。

### 文档导航

- [开发者文档](docs/DEVELOPMENT.md) — 完整 CLI 命令、目录结构、Windows 打包与外置模型配置
- [开发进度与五态成熟度](docs/PROGRESS.md) — 各模块真实已测/未验证/外部阻塞清单
- [AI 与 MCP 集成手册](docs/AI_INTEGRATION.md) — 无需 API Key 的 MCP/Skill 配置与客户端条款矩阵
- [项目维护工作流](docs/MAINTAINER_WORKFLOW.md) — 分支、PR、CI 诊断与自主推进规范
- [产品需求规格 (PROJECT_SPEC)](docs/PROJECT_SPEC.md) · [系统架构](docs/ARCHITECTURE.md) · [测试计划](docs/TEST_PLAN.md) · [第四轮全面审查报告](docs/FOURTH_REVIEW_REPORT.md) · [第四轮测试与基准报告](docs/TEST_REPORT.md) · [第四轮 UI/UX 审查报告](docs/UI_REVIEW.md) · [第三轮 UI 报告](docs/THIRD_REVIEW_UI_REPORT.md) · [第一/二轮复核报告](docs/SECOND_REVIEW_REPORT.md)

---

*LyraForge 是独立开源社区项目，与米哈游 / HoYoverse 及各 AI 模型提供商无官方关联。*
