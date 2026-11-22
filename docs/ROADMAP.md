# LyraForge 实施路线图（Roadmap）

> **更新日期**：2026-11-22  
> **开发策略**：在 macOS Apple Silicon（Mac mini M4）完成核心逻辑、前端 UI、DryRun 模拟与自动化验证；通过 GitHub Actions 双平台流水线验证 Windows 构建与无界面测试；《原神》实际自动演奏在 Windows 10/11 真机单独验收。

---

## 里程碑总览

| 阶段 | 名称 | 状态 | 关键出口判据 |
|---|---|---|---|
| **M0** | 技术验证、许可证审计、音乐核心与 DryRun | **已完成** | `docs/ARCHITECTURE.md`、`docs/LICENSE_AUDIT.md`、`docs/TEST_PLAN.md`、ADR 就绪；CLI 完成 `MIDI -> performance.json -> DryRun`；双平台 CI 配置与 ≥80% 单元测试通过 |
| **M1** | 可用 MVP：MIDI → 曲库 + 双平台桌面壳 + Windows 演奏驱动 | **代码已完成（待 Windows 真机《原神》人工验收）** | SQLite + 文件库持久化（已实现）；离线 WAV 试听合成（已实现）；独立封装 `lyraforge.playback.windows`（已实现）；本地 FastAPI 服务与 Vue 3 + PyWebView 双平台桌面壳（已实现）；Windows 真机 21 键校准与手动演奏验收（待真机执行） |
| **M2** | 音频 / 视频 → MIDI → 原琴 | **核心流水线已完成（可选隔离 ML 引擎待外部安装实测）** | 本地 WAV 标准化 + 受控 FFmpeg 提取 (`lyraforge.media`)；插件化 `Transcriber` 协议 + 纯 Python YIN 单音识别 (`builtin-mono`) + 隔离进程 `basic-pitch` / `dettato` 适配器；MIDI 清理与导出 (`cleanup`/`midi_export`/`export`)；Schema v2 (`transcriptions` 表)、`raw/cleaned/arrangement/performance` 版本链路与异步可取消转录任务 (`api/job_service.py`)；多音混音/带人声真实曲目评测随外部 FFmpeg + Basic Pitch 安装补充 |
| **M3** | 编曲质量提升与可视化工作台 | **已完成** | 新增 `genshin.floral_zither.v1`；主旋律检测与优先保留、柱式和弦琶音 (`arpeggiate_ms`)；多维质量评分 (`QualityBreakdown`) 与 A/B 对比；SQLite v3 (`parent_id`/`score`/`user_vote`/`label`)；Vue 3 `PianoRollEditor`（Undo/Redo、保存子版本）与收藏推荐 |
| **M4** | 关键词 + 授权链接 + AI Agent 编排 | **已完成** | `lyraforge.sources`（本地/目录与 SSRF 守卫授权直链）、`lyraforge.agent`（离线规则 + 可选 OpenAI-compatible Provider、严格禁止 `playback.start` 工具、质量自优闭环）、CLI/API 与桌面自然语言工作台 |
| **M5** | 分享包、打包发布与稳定版 | **已完成（待 Windows 打包 CI 实跑与真机游戏验收）** | `.lyrapack` 版权授权校验导入导出（默认剔除原始音频）与恶意 ZIP 防护；标签/收藏筛选与全库 ZIP 备份恢复；PyInstaller Windows 打包规范 (`packaging/lyraforge.spec`) 与 `package-windows` CI 作业；干净 Windows 环境安装验证与《原神》真机验收待执行 |

---

## M1 紧接任务清单（Next Steps）

完成 M0 验收后，下一阶段（M1）按以下垂直切片推进：

1. **M1-A｜跨平台曲库持久化 (`lyraforge.library`) — 已完成**
   - SQLite（WAL 模式）+ Schema v1 迁移（`songs`、`sources`、`arrangements`、`playback_sessions`、`settings`、`schema_migrations`）。
   - 跨平台数据目录解析（支持 `LYRAFORGE_DATA_DIR` 覆盖，默认 macOS `~/Library/Application Support/LyraForge`、Windows `%LOCALAPPDATA%/LyraForge`、Linux `~/.local/share/LyraForge`）。
   - SHA256 去重、内部复制源 MIDI（删除外部原文件仍可复播）与原子写入，保证重启后歌曲与多版本改编可检索复播。
2. **M1-B｜离线试听合成器 (`lyraforge.preview`) — 已完成**
   - 零外部音频依赖的纯 Python 拨弦泛音合成器，将 `performance.json` 离线渲染为单声道 16-bit PCM WAV（绝不打包未授权游戏采样），使 macOS 与 Windows 在不启动游戏的情况下即可试听最终改编效果。
3. **M1-C｜本地 FastAPI 服务 + Vue 3 / PyWebView 双平台桌面壳 (`apps/desktop`) — 已完成**
   - `lyraforge.api`：`127.0.0.1` 回环绑定 + 会话 Token（`X-LyraForge-Token`）+ 一次性 `prepare_token` 授权门槛 + HTML 注入引导配置。
   - `apps/desktop/web`（Vue 3 + TypeScript + Vite）+ `lyraforge.desktop`（PyWebView）：MIDI 导入、曲库检索、多版本生成、21 键预览、离线 WAV `<audio>` 试听、两步授权控制与紧急停止。macOS 默认启用 `dry-run` 并禁用 `windows` 选项。
4. **M1-D｜Windows 键盘模拟隔离驱动 (`lyraforge.playback.windows`) — 代码已完成，待 Windows 真机验收**
   - 独立子包实现 `WindowsKeyboardDriver`（Win32 `SendInput` 扫描码）与 `ForegroundWindowGuard`（公开窗口标题 API 焦点校验）。
   - 仅在 `sys.platform == "win32"` 时由 `create_playback_backend()` 延迟加载；macOS 等非 Windows 环境默认 `DryRunDriver` 并显式拒绝 `windows` 模式。
   - **Windows 真机独立验收**：完成《原神》风物之诗琴 21 键校准（将 `calibration.status` 升级为 `verified`）、焦点切换急停、ESC 紧急停止与非管理员运行测试。
