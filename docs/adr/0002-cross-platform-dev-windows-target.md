# ADR-0002: macOS Apple Silicon 主开发 + Windows 10/11 主运行平台的跨平台架构

- **状态**：已采纳（2026-11-22）
- **关联要求**：开发环境规划调整（Mac mini M4 开发，Windows 10/11 目标运行与真机验收）

## 背景

开发者主要使用 **macOS Apple Silicon（Mac mini M4）** 进行日常编码与调试，而 LyraForge 的主要目标发行与游戏内自动演奏运行环境为 **Windows 10/11 x64**（PC 版《原神》）。若代码库直接绑定 Win32 API 或依赖仅支持 Windows 的包，将导致无法在 macOS 本地运行测试、UI 调试与自动化验证；反之若忽略 Windows 输入差异，则会造成目标机不可用。

## 决策

1. **全链路核心跨平台**：`music_core`、`instruments`、曲库（M1 SQLite + 文件存储）、音频试听（M1）、AI Agent 编排（M4）全部使用纯跨平台 Python（兼容 macOS arm64 与 Windows x64），并遵循系统规范数据路径。
2. **Vue 3 + PyWebView 双平台桌面壳**：PyWebView 同时支持 macOS（WKWebView/Cocoa）与 Windows（WebView2），前端 Vue 3 代码完全共用一套代码库；本地 API 仅绑定 `127.0.0.1` + 会话 Token。
3. **Windows 游戏键盘模拟物理隔离**：跨平台 `lyraforge.playback` 只保留抽象协议（`PlaybackDriver`、`FocusGuard`、`Clock`）、`Player` 调度器与 `DryRunDriver`。Windows `SendInput` 与窗口焦点守卫在 M1 放入独立子包 `lyraforge.playback.windows`，仅在 `sys.platform == "win32"` 时按需加载；非 Windows 环境严禁导入 Win32/ctypes 输入代码（由 AST 分层测试强校验）。
4. **核心依赖零 Windows 专属包**：`pyproject.toml` 主依赖禁止出现 Windows 专属包；任何平台特定依赖均使用 PEP 508 环境标记（如 `; sys_platform == "win32"`）或独立 optional dependency group。
5. **macOS 开发期采用 DryRun 模拟演奏**：在 macOS 上点击演奏默认使用 `DryRunDriver` 与试听输出，完整模拟时间轴、按键释放和焦点退出逻辑，不向 macOS 发送系统级游戏按键。
6. **GitHub Actions 双平台 CI + Windows 构建**：配置 `.github/workflows/ci.yml` 在 `macos-latest` 与 `windows-latest` 上同步运行 lint、单测、集成测试与 CLI 冒烟；M1 起由 `windows-latest` 执行 Windows 打包构建校验。
7. **《原神》实际演奏单独真机验收**：Windows PC 游戏内的按键校准与自动演奏可靠性列为独立真机验收项，不与单元测试混为一谈，绝不在 macOS 上宣称已验证游戏内演奏。

## 后果

- **正面**：开发者在 Mac mini M4 上即可完成 95%+ 的功能开发、UI 联调与核心测试，同时保持 Windows 产物的可持续集成与干净边界。
- **负面**：需要严格维护平台接口抽象与 AST 分层门禁测试，并确保每次涉及 `playback.windows` 或 Windows 打包的变更都在 Windows 真机上完成最终手工回归。
