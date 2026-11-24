# LyraForge 开发者文档（Development Guide）

> 本文档整理面向贡献者与高级用户的本地运行命令、代码结构、质量门禁与 Windows / macOS 构建方式。公开产品介绍请见 [README.md](../README.md)，实时模块成熟度见 [PROGRESS.md](PROGRESS.md)，AI/MCP 集成请见 [AI_INTEGRATION.md](AI_INTEGRATION.md)。

---

## 1. 环境准备与本地校验门禁

前置要求：Python `3.11`（或 `3.12`）、[`uv`](https://docs.astral.sh/uv/)，以及前端测试/打包所需的 Node.js + `pnpm`（[package.json](../apps/desktop/web/package.json) 已固定 `"packageManager": "pnpm@12.6.0"`）。

```bash
# 安装/同步前后端锁定依赖
uv sync
pnpm --dir apps/desktop/web install --frozen-lockfile

# 一键运行全量质检（ruff + pytest 覆盖率>=80% + vitest + vite build + CLI smoke）
make check

# 或分项运行：
uv run ruff check .
uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80
uv run python scripts/eval_transcribers.py
pnpm --dir apps/desktop/web test
pnpm --dir apps/desktop/web build
make smoke
```

检查 GitHub Actions 远程 CI（需本机 `gh auth login` 已认证）：

```bash
uv run python scripts/check_ci.py --sha HEAD --watch
```

---

## 2. 完整 CLI 工具链（离线 & 本地库）

```bash
# 查看内置乐器配置与校准状态
uv run lyraforge profiles list
uv run lyraforge profiles show genshin.windsong_lyre.v1

# 检查 MIDI（支持 Type 0/1、多轨、Tempo 变化与损坏诊断）
uv run lyraforge inspect tests/fixtures/midi/chords_type1.mid

# 适配为游戏演奏事件 JSON（输出质量报告）
uv run lyraforge arrange tests/fixtures/midi/chords_type1.mid \
  -o /tmp/chords_perf.json \
  --report /tmp/chords_report.json \
  --style balanced

# Schema 与语义校验
uv run lyraforge validate /tmp/chords_perf.json

# DryRun 模拟演奏（零系统按键，支持提前停止校验松键）
uv run lyraforge playback dry-run /tmp/chords_perf.json --log /tmp/dryrun.jsonl
uv run lyraforge playback dry-run /tmp/chords_perf.json --stop-after-ms 1500

# 本地 SQLite 曲库、改编、试听 WAV 与导出
uv run lyraforge import tests/fixtures/midi/chords_type1.mid --title "Chords Demo" --tags demo,lyre
uv run lyraforge library list
uv run lyraforge library search "Chords"
uv run lyraforge library arrange <song_id> --style balanced
uv run lyraforge preview <arrangement_id> -o /tmp/preview.wav
uv run lyraforge export <arrangement_id> --format midi -o /tmp/arrangement.mid

# 本地桌面服务端与 PyWebView 桌面壳
uv run lyraforge serve --host 127.0.0.1 --port 8765 --token dev-token
make web-setup && make desktop

# 音频转谱与引擎探测
uv run lyraforge engines list
uv run lyraforge transcribe /path/to/solo.wav --engine builtin-mono -o /tmp/raw.mid --cleaned-out /tmp/cleaned.mid --arrange-out /tmp/perf.json

# 离线规则 Agent 与授权开放曲库检索
uv run lyraforge agent "搜索《Chords Demo》转成镜花之琴主旋律并优化"
uv run lyraforge agent "搜索开放曲库 Clair de Lune 转成风物之诗琴曲谱" --allow-network

# 以 stdio MCP Server 启动（供 Claude Code / Codex / Antigravity 调用）
uv run lyraforge mcp

# 分享包导出/导入（默认剔除原始音频与凭据）与全库安全备份
uv run lyraforge pack export <arrangement_id> -o /tmp/demo.lyrapack --confirm-rights
uv run lyraforge pack import /tmp/demo.lyrapack
uv run lyraforge library backup -o /tmp/lyraforge-backup.zip
```

---

## 3. 可选外部多媒体与转录引擎配置

内置 `builtin-mono` 使用纯 Python 离线 YIN 算法（适合独奏单声线；在多声部和弦上受限，见 `scripts/eval_transcribers.py` 实测）。如需非 WAV 媒体（MP3/MP4/MKV）或更高准确度多音转录：

### 3.1 推荐：应用内一键安装（无需命令行、不改系统环境）

桌面版 **设置 →「转谱引擎与 GPU」→「外部工具与转谱引擎」** 中，每个工具都有「安装」按钮；也可用 CLI：

```bash
uv run lyraforge tools status          # 查看 ffmpeg / basic-pitch / dettato 是否就绪
uv run lyraforge tools install         # 安装全部（首次约 1.2 GB 下载）
uv run lyraforge tools install ffmpeg  # 只装 FFmpeg（约 40 MB）
```

安装位置为 `%LOCALAPPDATA%\LyraForge\tools`（macOS：`~/Library/Application Support/LyraForge/tools`）：
- 从 PyPI 下载 `uv` wheel（SHA-256 校验后解压），由它管理独立 CPython 与各引擎虚拟环境；
- FFmpeg 从 `imageio-ffmpeg` wheel 中提取并做可执行性校验；
- 不写注册表、不修改用户环境变量；应用启动时由 `lyraforge.toolchain.runtime` 自动把路径注入子进程，显式设置的同名环境变量优先。

### 3.2 高级：手动安装（自定义版本或无法联网时）

1. 安装系统 `ffmpeg` 并确保 `ffmpeg`/`ffprobe` 在 `PATH` 中（Windows 可直接 `winget install --id Gyan.FFmpeg`）。
2. 按 [ADR-0001](adr/0001-headless-python-core-and-isolated-transcribers.md) 在**独立**虚拟环境中安装对应引擎（不要装进主环境），再通过环境变量接入：

   **Basic Pitch（Apache-2.0）**

   ```bash
   uv venv ~/.lyraforge-tools/basic-pitch --python 3.11
   uv pip install --python ~/.lyraforge-tools/basic-pitch/bin/python \
     basic-pitch==0.4.0 "numpy<2" "setuptools<81"
   export LYRAFORGE_BASIC_PITCH_PYTHON=~/.lyraforge-tools/basic-pitch/bin/python
   # Windows：...\basic-pitch\Scripts\python.exe
   ```

   - basic-pitch 0.4.x 的模块入口是 `basic_pitch.predict`（旧版本为 `basic_pitch.inference`，LyraForge 已按 0.4.x 适配）；
   - `numpy<2` 是 TensorFlow 2.14 的硬性要求（否则 `pywrap_ml_dtypes` 导入崩溃）；`setuptools<81` 仍提供 `resampy` 需要的 `pkg_resources`；
   - `basic-pitch` 会向 stdout 打印 emoji 进度，LyraForge 已为子进程强制 `PYTHONUTF8=1`，避免中文 Windows 的 `cp936` 编码崩溃。

   **dettato（Apache-2.0，权重首次运行自动从 Hugging Face 下载）**

   ```bash
   uv venv ~/.lyraforge-tools/dettato --python 3.11
   uv pip install --python ~/.lyraforge-tools/dettato/bin/python dettato==2.0.0
   export LYRAFORGE_DETTATO_PYTHON=~/.lyraforge-tools/dettato/bin/python
   # Windows：...\dettato\Scripts\python.exe
   ```

   - dettato 的 `-o` 是输出**目录**，它会在其中写入 `<曲名>.mid`；CPU 推理约 4 秒音频 / 20 秒耗时。
   - **GPU 加速**：桌面 **设置 →「转谱引擎与 GPU」→ dettato GPU 加速** 会自动检测 NVIDIA GPU 与隔离环境里的 PyTorch/CUDA；可在下拉框选 `auto / cpu / cuda / mps`（持久化到工具链清单，启动时注入 `LYRAFORGE_DETTATO_DEVICE`）。若只装了 CPU 版 torch，点「安装 CUDA 版 PyTorch」即可由应用调用 `uv pip install --reinstall-package torch torch --index-url https://download.pytorch.org/whl/cu130` 完成（下载约 1.9 GiB）；索引可用 `LYRAFORGE_PYTORCH_CUDA_INDEX` 覆盖，安装后会验证 `torch.cuda.is_available()`。注意 PyPI 的 CPU wheel 可能比 CUDA 索引里的最新版本更新（例如 2.15.0+cpu 对 2.14.1+cu130），所以必须 `--reinstall-package torch` 强制降级替换，普通 `--upgrade` 会“无变更”并继续报 CUDA 不可用。命令行仍可直接设置 `LYRAFORGE_DETTATO_DEVICE=cpu|cuda|mps`。
   - **超时**：转录子进程预算会随音频长度增长（dettato 约 10× 实时 + 180 秒余量，Basic Pitch 约 3× + 60 秒），不再固定 5 分钟。
3. 校验：`uv run lyraforge engines list` 中三个引擎均为 `available: true`，再对一段 WAV/MP3 执行一次 `lyraforge transcribe`。

> Windows 如需让桌面应用长期看到上述变量，可用
> `[Environment]::SetEnvironmentVariable('LYRAFORGE_BASIC_PITCH_PYTHON', '<path>', 'User')` 写入用户环境变量后重新登录。
> 使用 §3.1 的应用内安装时无需这一步。

### 3.3 内置乐器与一键编曲预设

- 乐器 Profile 位于 `src/lyraforge/instruments/data/*.json`，当前内置：风物之诗琴（C 大调，MIDI 48–83）、镜花之琴（C 大调，48–83）、老旧的诗琴（低/中行 C Dorian、高行 C Phrygian，48–82）。
- 预设位于 `src/lyraforge/presets.py`：每件乐器 5 套（主旋律优先 / 均衡 / 丰满 / 慢速练习 / 轻快），对应 `style`、移调、琶音与速度。命令行查看：`uv run lyraforge presets list --profile genshin.windsong_lyre.v1`；桌面端在编曲工作室顶部直接点选应用。
- 新增 21 键乐器：复制现有 JSON，修改 `id`、`display_name`、`keys[].pitch`，在 `calibration` 中写明资料来源并保持 `status: "unverified"`；在 `presets.py` 的 `_PROFILE_IDS` 登记；运行 `uv run pytest tests/unit/test_presets.py`。
- 校准边界：Windows 10/11《原神》自由演奏实机流程与默认键位表现已由维护者实机验证通过；三件内置乐器 JSON 的 `calibration.status` 元数据字段目前仍保持 `"unverified"`（待后续单独元数据更新）；更换键位属于数据修改，不需要改编曲算法。


---

## 4. 安全与凭据架构要点

- **API Key 安全存储**：支持 `LYRAFORGE_LLM_API_KEY` 环境变量及系统凭据库（macOS Keychain `security -i`、Windows Credential Manager [secrets_win32.py](../src/lyraforge/secrets_win32.py)、或 `0o600` 文件 `.lyraforge.secrets.json`）。[store.py](../src/lyraforge/library/store.py) 启动时自动迁移并删除历史 SQLite 明文键；[packaging.py](../src/lyraforge/library/packaging.py) 导出全库备份与 `.lyrapack` 均排除凭据。
- **网络 SSRF 防护**：[url.py](../src/lyraforge/sources/url.py) 使用 DNS 解析固定（`_PinnedHTTPConnection` / `_PinnedHTTPSConnection`）、封堵私网/回环/CGNAT/内嵌账号 URL，限制重定向（≤5）和超时。
- **开放曲库许可解析**：[online.py](../src/lyraforge/sources/online.py) 通过严格规范化的 Creative Commons / Public Domain URL 白名单判定（禁止 `NoDerivatives` 与弱子串匹配）。

---

## 5. 双平台便携打包（Windows + macOS）与 GitHub Releases 自动发布

```powershell
# 在 Windows 10/11（无需管理员权限）生成便携目录 dist/LyraForge/LyraForge.exe
./scripts/build_windows.ps1
```

```bash
# 在 macOS Apple Silicon 生成独立应用包 dist/LyraForge.app 并验证 Cocoa GUI 宿主
bash ./scripts/build_macos.sh

# 如需修改矢量母版（packaging/icons/lyraforge*.svg）后重新生成 .ico / .icns / .png
uv run python scripts/generate_icons.py
```

CI 复用 [.github/workflows/ci.yml](../.github/workflows/ci.yml) 中的 `package-windows` 与 `package-macos` 作业：在双平台测试及原生 `--self-check --check-gui` 全数通过后，由 [scripts/release_helper.py](../scripts/release_helper.py) 将完整 Windows 便携目录与 macOS `.app` 包分别打包为包含架构/构建版本、完整运行时依赖、前端 `dist/` 与 `LICENSE` 的 ZIP，生成统一的 `SHA256SUMS.txt` 并对两端**解压后的可执行文件 `--self-check --check-gui`** 进行二次验证：

- **开发预发行渠道（Pre-release）**：`main` 分支每次受信任的 `push` 或手动 `workflow_dispatch` 会发布不可变快照 `dev-<YYYYMMDD>-<sha7>`（保留最近 10 个快照），并同步更新固定最新入口 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest)（同时包含 `windows-x64` 与 `macos-arm64` 构建）；所有开发版均以 Pre-release 渠道发布，并附带校验哈希与当前版本说明。
- **独立 SemVer 正式发行渠道**：仅当推送独立 `vX.Y.Z`（或 `vX.Y.Z-alpha.N`）Tag 时发布对应版本，绝不会被普通 `main` 推送覆盖或移动 Tag，且所有 Pull Request 均禁止执行发布作业（顶层默认 `contents: read`，仅发布作业授予 `contents: write`）。
- 相关构建与发布辅助：[lyraforge.spec](../packaging/lyraforge.spec)、[release_helper.py](../scripts/release_helper.py)、[generate_icons.py](../scripts/generate_icons.py)。

---

## 6. 仓库目录结构

```text
lyraforge_starter/
├─ AGENTS.md                  # 持久化自主维护规则与安全约束
├─ pyproject.toml / uv.lock   # 跨平台锁定依赖 (GPL-3.0)
├─ .github/workflows/ci.yml   # GitHub Actions: macOS/Windows 测试与双平台 PyInstaller 打包发布
├─ packaging/
│  ├─ lyraforge.spec          # PyInstaller Windows (.exe) & macOS (.app) 统一打包配置
│  └─ icons/                  # SVG 矢量母版及生成的多分辨率 .ico / .icns / .png 图标
├─ integrations/              # Claude Code / Codex / Antigravity MCP 配置与 Skill 模板
├─ docs/                      # 需求规格、架构、开发者/维护手册、CI 与 Review 报告
├─ src/lyraforge/
│  ├─ errors.py / fs.py       # 统一错误码与原子路径安全写
│  ├─ secrets.py / secrets_win32.py  # 跨平台凭据管理与日志脱敏
│  ├─ music_core/             # 无头纯 Python 音乐核心（MIDI/Tempo/编曲/分离式质量评价）
│  ├─ instruments/            # 乐器预设（风物之诗琴/镜花之琴/老旧的诗琴）
│  ├─ media/ / transcribers/  # WAV 提取、YIN 转录与隔离进程外部 ML 适配器
│  ├─ sources/                # 本地库/目录 + 规范化许可判定开放曲库 + DNS 固定直链获取
│  ├─ agent/                  # 离线规则指令解析与可选 OpenAI-compatible HTTP 提供器
│  ├─ mcp/                    # 零依赖 stdio JSON-RPC MCP Server 与任务取消注册表
│  ├─ library/                # SQLite (WAL v3) 曲库、.lyrapack 与原子回滚备份恢复
│  ├─ preview/                # 纯 Python 拨弦 WAV 试听合成器
│  ├─ api/ / desktop/         # 127.0.0.1 FastAPI 服务 + PyWebView 桌面壳
│  └─ playback/               # 跨平台调度器、DryRun 与隔离 Windows SendInput 驱动
├─ apps/desktop/              # PyWebView 入口与 Vue 3 + TypeScript + Vite 工作台
├─ scripts/                   # check_ci.py、eval_transcribers.py、generate_icons.py、build_windows.ps1、build_macos.sh
└─ tests/                     # 自制版权安全 MIDI 样例、单元测试、分层门禁与集成测试
```
