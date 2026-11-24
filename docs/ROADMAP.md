# LyraForge 产品与工程路线图（Roadmap）

> **更新日期**：2026-11-24  
> **定位**：汇总项目里程碑完成状态及 Alpha 向 Beta / Stable 演进的核心优先级；详细实时状态见 [PROGRESS.md](PROGRESS.md)，实测数据见 [TEST_REPORT.md](TEST_REPORT.md)。

---

## 一、既定里程碑回顾（M0 ~ M5）

| 阶段 | 名称 | 当前状态 | 说明与剩余门槛 |
|---|---|---|---|
| **M0** | 技术验证、许可审计与音乐核心 | **已完成** |确立 GNU GPL-3.0、核心无头架构与 DryRun 基准 |
| **M1** | MIDI 曲库、试听、桌面壳与 Windows 驱动 | **已完成** | 跨平台曲库、拨弦试听、FastAPI + PyWebView 与隔离 `WindowsKeyboardDriver` 已通过 CI 测试，且 Windows 10/11《原神》自由演奏实机流程已由维护者验证通过 |
| **M2** | 音视频导入、内置与隔离音频转谱 | **已完成（复杂混音听感持续优化）** | 原生 WAV + YIN 独奏识别与任务取消链路已跑通；`ffmpeg` / `basic-pitch` / `dettato` 应用内一键安装与 CUDA GPU 加速均已在 Windows 落地实测，复杂混音转谱效果持续迭代 |
| **M3** | 智能编曲、评分分离与 DAW Piano Roll | **已完成** | 主旋律优先保留、和弦琶音、适配/还原评分分离及缩放吸附拖拽式 Piano Roll 已落地 |
| **M4** | 授权在线检索、零 Key Agent 与 MCP | **已完成** | DNS 固定 SSRF 防护、规范 CC/PD 许可判定、离线规则 Agent、可选 HTTP LLM 与 `stdio` MCP 工具链已就绪 |
| **M5** | 分享包、备份恢复与便携打包 | **已实现（双平台预发行就绪；待正式 Stable 发版）** | `.lyrapack`、事务目录切换备份恢复、Windows + macOS PyInstaller 打包、统一应用图标与 `dev-latest` CI 发布流水线均已就绪；Windows 实机已启动验证，待正式 Stable SemVer 发版决策 |

---

## 二、当前收尾基线总结

经过多轮深度审查与稳定性收敛，工程基础（MCP 协议与取消安全、曲库事务恢复与锁隔离、有界子进程与并发试听保护、Studio Obsidian UI 重设计与双平台 CI/打包门禁）已稳定可用，**不再进行无针对性的大型内部架构重构**。接下来的投入全面转向真实音乐转谱听感质量、多乐器细节完善与正式版发布准备。

---

## 三、下一阶段演进规划（Alpha → Beta / Stable）

### 优先级 A：真实音乐转谱与编曲听感提升

以有合法使用权或开放许可的真实音频与曲谱素材为中心，系统性评估并打磨实际效果：

1. **主旋律识别与剥离**：验证纯钢琴、吉他、带前奏流行歌的旋律线提取准确性。
2. **多音与和弦转谱调优**：结合外部 `basic-pitch` / `dettato` + `ffmpeg` 真实输出，补强多声部转谱后的节奏量化、八度归位与碎音清洗策略。
3. **人声伴奏混合场景**：评估混音输入下转录信噪比与编曲可演奏性之间的权衡策略。
4. **音高/节奏直观可听性**：统计从“音频导入 → 转谱 → 自动编曲 → 可直接试听/游玩”的端到端可用成功率，改善不和谐半音与密度突变问题。

### 优先级 B：Windows 10/11 长时稳定性与发布细节收尾（基础实机演奏已验证）

Windows 10/11《原神》自由演奏基础实机流程已由维护者验证通过，剩余发布前可选收尾项包括（参考 [TEST_REPORT.md](TEST_REPORT.md) §5）：

1. **元数据与逐键档案更新**：视需要发起单独 PR，将三件乐器 JSON 中的 `calibration.status` 元数据由 `"unverified"` 升级并同步测试断言。
2. **长曲目耐久实测**：进一步积累 3–5 分钟持续演奏与跨焦点切换下的极端场景回归样本。
3. **macOS / Windows 发布体验评估**：评估后续正式 SemVer 发版时的代码签名 / Apple 公证方案。

### 优先级 C：面向普通用户的产品交付打磨

优先解决真实用户的安装与上手痛点，而非继续堆积内部工程报告：

1. **开箱体验简化**：应用内一键安装外部工具链（[PR #12](https://github.com/PariyaProject/LyraForge/pull/12)）、Studio Obsidian UI/UX 重设计（[PR #22](https://github.com/PariyaProject/LyraForge/pull/22)）及极简图标与 Windows + macOS 双端打包（[PR #23](https://github.com/PariyaProject/LyraForge/pull/23)）均已落地；后续补首次启动引导与失败重试提示。
2. **工作流连贯性**：打磨“导入 / 搜索 → 一键转谱与 A/B 选版 → Piano Roll 快速改音高/拍点 → 试听 → 演奏或导出”操作路径。
3. **Beta / Release 准备**：完成优先级 A 核心音质评估、整理发布说明并经所有者确认后，筹备首个正式版本 `vX.Y.Z`。
