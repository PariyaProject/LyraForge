# LyraForge 开源许可证与依赖审计（License Audit）

> **审计日期**：2026-11-22  
> **审计原则**：在引入任何外部源码、模型权重、SoundFont、测试曲谱或第三方库前，核验仓库实际 LICENSE、Commit SHA、权重条款与平台兼容性；严禁将 GPL-3.0 源码混入未明确授权的代码库。

---

## 1. LyraForge 自身许可证与依赖状态

- **项目自身许可证**：**GNU General Public License v3.0 (GPL-3.0)**（完整条款见根目录 [LICENSE](../LICENSE)）。本项目主模块全部为自主 clean-room 实现，已锁定的 MIT / Apache-2.0 / BSD-3-Clause 第三方依赖均与 GPL-3.0 兼容。
- **核心运行依赖无 Windows 专属污染**：`pyproject.toml` 中的 `[project].dependencies` 仅包含纯跨平台 Python 包，可在 macOS Apple Silicon、Linux 与 Windows x64 一致安装。

### 1.1 已锁定 Python 依赖（见 `pyproject.toml` & `uv.lock`）

| 包名 | 锁定版本 | 分组 | 许可证 | 平台兼容 | 用途说明 |
|---|---|---|---|---|---|
| `mido` | `1.3.3` | runtime | MIT | 纯 Python 跨平台 | 标准 MIDI 文件（SMF）二进制解析 |
| `jsonschema` | `4.26.0` | runtime | MIT | 纯 Python 跨平台 | `InstrumentProfile` 与 `performance.json` Draft 2020-12 校验 |
| `fastapi` | `0.165.0` | runtime | MIT | 纯 Python 跨平台 | 本地 `127.0.0.1` HTTP API 服务 |
| `uvicorn` | `0.54.0` | runtime | BSD-3-Clause | 跨平台 | 本地 ASGI 服务器 |
| `python-multipart` | `0.0.34` | runtime | Apache-2.0 | 纯 Python 跨平台 | FastAPI 文件上传表单解析 |
| `pywebview` | `6.2.1` | optional (`desktop`) | BSD-3-Clause | 条件绑定：macOS (`pyobjc` Cocoa/WKWebView) / Windows (`pythonnet` WebView2) | 双平台桌面应用容器 |
| `pytest` | `9.2.0` | dev | MIT | 跨平台 | 单元测试与集成测试框架 |
| `pytest-cov` | `7.1.0` | dev | MIT | 跨平台 | 分支与语句覆盖率统计（目标 ≥80%） |
| `ruff` | `0.17.6` | dev | MIT | macOS arm64 / Windows x64 原生轮子 | 静态检查与代码格式/导入规范 |
| `httpx` | `0.28.1` | dev | BSD-3-Clause | 纯 Python 跨平台 | FastAPI `TestClient` 集成测试客户端 |
| `hatchling` | `1.33.0` | build-system | MIT | 纯 Python 跨平台 | PEP 517 构建后端 |

*(注：上述依赖自带的传递依赖如 `attrs`、`referencing`、`rpds-py`、`coverage` 等均已在 `uv.lock` 锁定，为常见 MIT/Apache-2.0/BSD 宽松许可。)*

### 1.2 前端 Node 依赖（见 `apps/desktop/web/package.json` & `pnpm-lock.yaml`）

- `vue` (`^3.5.13`)、`@vitejs/plugin-vue` (`^5.2.1`)、`vite` (`^6.0.11`)、`vitest` (`^3.0.4`)、`@vue/test-utils` (`^2.4.6`)、`jsdom` (`^25.0.1`)、`vue-tsc` (`^2.2.0`) — 均为 **MIT**；`typescript` (`^5.7.3`) 为 **Apache-2.0**；`esbuild`（Vite 传递依赖）为 **MIT**。

---

## 2. 上游参考项目核验记录（2026-11-22 实测）

以下信息于 2026-11-22 通过 GitHub REST API 与 `git ls-remote` 实测获取，**M0 阶段未复制任何上游仓库代码**。

| 仓库 | 核验 Commit SHA | 仓库 SPDX 许可 | 状态 | 可借鉴边界与风险结论 |
|---|---|---|---|---|
| [Akinome/genshin-music-studio](https://github.com/Akinome/genshin-music-studio) | `28fd488d77a0945eb5976edef23f7d1ed456550a` | **GPL-3.0** | 活跃（stars: 5） | 架构参考（多阶段 MIDI 流水线与原琴适配思路）；**禁止直接复制源码**，以免触发 GPL-3.0 传染义务。 |
| [Jed556/AutoMidiPlayer](https://github.com/Jed556/AutoMidiPlayer) | `0eadb428b0fe44b8f1820aee51c5be06c273549f` | **GPL-3.0** | 活跃（stars: 71） | 多游戏乐器配置与 UI 交互思路参考；**禁止直接复制源码或品牌素材**。 |
| [sabihoshi/GenshinLyreMidiPlayer](https://github.com/sabihoshi/GenshinLyreMidiPlayer) | `1a400a0a90e4f3eb99b1ee6a1fa81b7320fbc832` | **MIT** | 非归档（pushed 2023-07, stars: 283） | 仅核对事实数据：确认了《原神》风物之诗琴默认 QWERTY 21 键（MIDI 48–83 自然大调音阶，Z–M / A–J / Q–U）映射关系，详见 `Keyboard.cs`；**未复制 C# 代码**。 |
| [LanceLRQ/genshin-music-player](https://github.com/LanceLRQ/genshin-music-player) | `1291c04c89706c595dfd2e0cba306b2f86f2d3c8` | **MIT** | 活跃（stars: 2） | 谱格式与冲突检测思路参考；未复制代码。 |
| [babalae/bettergi-scripts-list](https://github.com/babalae/bettergi-scripts-list) | `685ae8e6d3ef1a800344d5044e045731c9bc3499` | **无仓库级 License (`None`)** | 活跃（stars: 774） | 社区脚本/谱面权利混杂且无统一许可证；**禁止直接打包或镜像其谱面资源**。 |
| [spotify/basic-pitch](https://github.com/spotify/basic-pitch) | `fa5997af0a8210982619003269994a1be25eddf3` | **Apache-2.0** | 活跃（stars: 6108） | 拟作为 M2 基础音频转 MIDI 引擎。PyPI `0.4.0` 依赖分析显示：Windows + Python >=3.11 默认绑定 `tensorflow<2.15.1`，且 macOS Apple Silicon 对 Python/TF/CoreML 版本要求敏感。**结论：M2 通过独立隔离环境/Worker 调用**（详见 [ADR-0001](adr/0001-headless-python-core-and-isolated-transcribers.md)）。 |
| [kobimusic/dettato](https://github.com/kobimusic/dettato) | `9b724251794f2bbd5eaa43e54734e5a251829130` | **Apache-2.0**（代码与权重） | 活跃（stars: 215） | M2 可选多乐器高精度候选。README 注明代码与权重为 Apache-2.0，但部分 grouper/drum 训练数据集带非商用条款；引入前需展示模型卡并按需下载。 |
| [facebookresearch/demucs](https://github.com/facebookresearch/demucs) | `e976d93ecc3865e5757426930257e200846a520a` | **MIT** | **已归档 (`archived: true`, 2024-04)** | 可选按需隔离安装的多轨源分离工具（`lyraforge tools install demucs`），与 PyInstaller 分发包完全分离、不内嵌打包；预训练 `htdemucs` 权重仅在用户触发人声分离流水线时按需下载至用户工具缓存。 |
| `swift-f0` (`0.3.0`) | PyPI release `0.3.0` | **MIT**（代码与内置 0.13 MB `model.onnx` 权重） | **已采用（可选隔离环境）** | 通过 `lyraforge tools install swift-f0` 按需安装到独立虚拟环境（`swift-f0==0.3.0` + `mido`，依赖 `onnxruntime` MIT 与 `numpy` BSD-3-Clause，独立环境实占约 `104.2 MB`），绝不打入 PyInstaller 分发包；与 `GPL-3.0` 完全兼容，仅用于单音人声 F0 提取与 DP 音符切分。 |
| `torchcrepe` / `torchfcpe` / `librosa` (`pyin`) | 调研评测基线 (`0.0.24` / `0.0.4` / `0.11.0`) | **MIT / ISC** | **已评测未接入** | 虽许可兼容，但在相同真声/合成评测集下无内置 DP 音符切分时均产生严重颤音碎片（F1 `0.445–0.500` vs `swift-f0` `0.842`），且依赖额外权重或推理较慢（RTF `0.033–0.386` vs `0.006`）。 |
| `mlx-rmvpe` (`0.1.0`) | 调研评测基线 (`0.1.0`) | 代码 **MIT**；外部 RMVPE 权重 | **已评测拒绝** | 仅支持 macOS Apple Silicon (`mlx`)、不支持 Windows/CUDA/纯 CPU、需加载外部 RMVPE 权重且无原生 DP 切分（实测 F1 `0.425`），不符合双平台与轻量原则。 |
| [muscriptor/muscriptor](https://github.com/muscriptor/muscriptor) | `68456b17da8eea651eee6084c104611089810231` | 代码 **MIT**；权重 **CC BY-NC 4.0** | 活跃（stars: 2002） | README 明确要求登录 HuggingFace 并接受非商用（CC BY-NC 4.0）权重协议；**禁止默认打包进公开发行版**，仅列为研究参考。 |
| [zeikar/pianoize](https://github.com/zeikar/pianoize) | `66b3f6ad540f2fab1c68e54fa831c630f8a2d387` | **MIT** | 活跃（stars: 3） | Agent 编曲验证思路参考；非原琴专用，未复用代码。 |
| [mido/mido](https://github.com/mido/mido) | `d261ee41db32717fb73dfaa14162159fb6529ef5` | **MIT** | 活跃（stars: 1661） | M0 直接使用的 MIDI 文件解析库。 |
| [sgossner/VCSL](https://github.com/sgossner/VCSL) | `c1ea7bcc3c7309650ab0da9d15c9cd1fbc4a4c7e` | **CC0-1.0**（Public Domain） | 活跃（stars: 46） | 从 Steinway Model B 三角钢琴、音乐会竖琴与越式十三弦（Dan Tranh）抽取并降采样裁剪的真实原声试听采样（`src/lyraforge/preview/samples/`），与 `GPL-3.0` 完全兼容；严禁提取游戏本体音频。 |

---

## 3. 自制测试数据集声明

`tests/fixtures/midi/` 下全部 17 个 `.mid` 文件均由本项目自编脚本 `tests/fixtures/midi_builders.py`（通过 `scripts/make_fixtures.py`）生成，内容为人工构造的音阶、三和弦、半音阶、重复音、跨八度、变拍/变速及损坏文件头测试样例，**不含任何第三方商业乐谱、游戏录音或受版权保护的 MIDI**。
