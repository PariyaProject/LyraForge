# ADR-0001: 无头跨平台 Python 音乐核心与隔离式音频转谱环境

- **状态**：已采纳（2026-11-22）
- **关联阶段**：M0（音乐核心初始化）与 M2（音频转录引擎集成）

## 背景

1. 产品需要在 M0 交付稳定、离线可用、跨平台的 `MIDI -> 乐器配置适配 -> performance.json -> DryRun` 能力。
2. 在 M2 拟引入 Spotify `basic-pitch` 与 `kobimusic/dettato` 进行本地音频→MIDI 转录。
3. 2026-11-22 对 PyPI 元数据审计发现：`basic-pitch==0.4.0` 在 Windows + Python >=3.11 下默认依赖 `tensorflow<2.15.1,>=2.4.1`，在 macOS Darwin 上条件依赖 `coremltools` 或 `tensorflow-macos<2.15.1`（且与 Python 3.12+ 冲突）；而 `dettato` 依赖 PyTorch 2.2+ 与 HuggingFace 权重。

## 决策

1. **M0 主核心保持极简纯 Python**：`lyraforge.music_core` 仅依赖跨平台纯 Python 库 `mido==1.3.3` 和 `jsonschema==4.26.0`，不引入 TensorFlow、PyTorch、SciPy、NumPy 或编译型音频依赖，确保在 macOS Apple Silicon（M4）、Windows 10/11 与 CI runner 上毫秒级安装与确定性执行。
2. **转录引擎以进程/环境隔离接入（M2）**：将 `Transcriber` 实现作为独立的 Worker 进程或按需安装的独立 Python 环境（或独立 extras/uv 环境）运行，主应用通过标准输入输出/本地 IPC 与可取消任务队列通信，避免 TensorFlow / PyTorch 的版本约束冲突污染主桌面程序与曲库/演奏核心。

## 后果

- **正面**：M0–M1 开发和安装极轻量；无独显用户与 macOS 开发机无需下载数 GB 深度学习框架即可开发和测试；未来同时支持 Basic Pitch、dettato 或其他模型互不打架。
- **负面**：M2 需要设计轻量的 Worker 启动与错误透传机制（`MODEL_MISSING` / `TRANSCRIPTION_FAILED`）及进程取消清理逻辑。
