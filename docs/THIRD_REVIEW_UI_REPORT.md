# LyraForge 第三轮独立复核与前端 UI/UX Studio 重设计报告

> **复核基线 `main` 提交**：`a872f664c5e9dd0b05976bcccc1e9260803c0ba2`  
> **工作分支**：`feat/ui-ux-studio-redesign`  
> **开源许可证**：GNU General Public License v3.0（[LICENSE](../LICENSE) · [docs/LICENSE_AUDIT.md](LICENSE_AUDIT.md)），严格保持不变。  
> **声明边界**：本报告仅记录当前 macOS Apple Silicon 开发机可实测项目，**不包含 Windows 10/11《原神》实机切窗/21 键校准**，亦未在本机安装 `ffmpeg`、`basic-pitch` 或 `dettato`。

---

## 一、阶段一：远端状态与核心安全回归复核

1. **GitHub Actions CI 基线验证（Run [#45003219667](https://github.com/PariyaProject/LyraForge/actions/runs/45003219667)）**
   - 对应提交：`a872f664c5e9dd0b05976bcccc1e9260803c0ba2`（`origin/main`）。
   - 三项作业全部真实通过（`success`）：
     - `Test (windows-latest, Python 3.11)`
     - `Test (macos-latest, Python 3.11)`
     - `Build Windows Bundle (PyInstaller)`
2. **关键安全与核心能力独立回归（`uv run pytest`）**
   - `tests/unit/test_secrets_and_security.py`、`tests/unit/test_lyrapack_and_m5.py`、`tests/unit/test_windows_playback.py`、`tests/unit/test_license_and_quality.py`、`tests/unit/test_mcp_server.py`：**19 passed, 1 warning in 1.97s**。
   - 实测核验内容包括：API Key 凭据隔离与备份/`.lyrapack`/日志脱敏、SQLite 故障自动回滚、DNS 固定防 SSRF 下载、`classify_license_url()` 版权许可校验、Windows `SendInput` 驱动松键重试逻辑、`play_in_game` 在 MCP 侧保持门禁。

---

## 二、阶段二：旧版前端真机启动与缺陷清单

启动真实 `lyraforge serve` + 静态构建产物后，使用无头 Google Chrome 在 `1024×720`（紧凑）、`1440×900`（标准）与 `1920×1080`（宽屏）三个窗口尺寸截取并审查页面，整理如下缺陷：

| 类别 | 实测现象与代码定位 | 改进方案 |
|---|---|---|
| **视觉与布局问题** | 单页全功能堆叠，`1920×1080` 下试听、导出、`.lyrapack` 分享包与游戏演奏控制台仍折叠在首屏外 | 拆分为左侧导轨 + 顶部上下文栏的 6 大专属工作视图（首页 / 本地曲库 / AI 转谱 / 编曲工作室 / 试听与演奏 / 设置与模型） |
| **视觉与布局问题** | 左侧边栏 `<input type="file">`（「导入分享包」）在三套窗口下均超出卡片右边界约 12px | 为输入控件增加 `.file-picker-wrap` 单层容器、`max-inline-size: 100%` 及全链路 `min-inline-size: 0` |
| **视觉与布局问题** | `1024×720` 紧凑视口下，已保存版本下拉框与 Agent 指令输入框缺少 `min-inline-size: 0` 发生裁切；边框对比偏弱 | 引入 `@layer base, tokens, layout, components, utilities` + Studio Dark 语义 Token（`--border-control: #5a6a8a`）与 `@media (forced-colors: active)` 回退 |
| **交互问题** | 曲库检索、Agent 提示词等回车行为缺少中文/日文输入法组字保护，WebKit 下易在选词按 Enter 时误提交 | 新增 `isImeEnter(event)` 统一拦截 `event.isComposing \|\| event.keyCode === 229` |
| **交互问题** | Piano Roll 缺乏时间轴缩放、吸附网格精度、时间标尺、指针直接拖拽调音及键盘快捷键 | 重构为支持 `50%–250%` 缩放、`0/25/50/100/250 ms` 吸附、粘性标尺、指针拖拽音高/时值、点击加音与 `Arrow` / `Delete` / `Ctrl+Z` 的 DAW 编辑器，并补充 ToastStack 即时反馈 |
| **功能与信息架构** | 缺少以“快速搜索 + 拖拽导入 + 最近曲目”为核心的工作台首页；音频转谱缺阶段步骤指示；客户端缺乏桌面内一键 `lyraforge mcp` 配置面板 | 新增 `HomeView` 拖拽导入区与最近工程网格、`TranscribeView` 四步流水线与 `<progress>` 进度条、`SettingsView` 免 API Key 的 MCP/Skill 标签页复制面板 |

---

## 三、阶段三：Studio Dark 设计系统与可访问性落地

- **设计 Token 与层级化样式**：新建 [tokens.css](../apps/desktop/web/src/styles/tokens.css) 与 [global.css](../apps/desktop/web/src/styles/global.css)，使用 CSS Cascade Layers (`@layer`)、`min-inline-size: 0`、`scrollbar-gutter: stable` 以及受特性查询保护的细滚动条样式。
- **语义地标与无障碍**：全页保持 `<aside>` + `<nav aria-label="主工作区导航">` + `<header class="studio-topbar">` + `<main id="main-content">` 结构，每视图仅使用单一 `<h1>` 与显式 `for`/`id` 标签；音频转谱进度采用原生 `<progress>`，避免在高频过渡态使用吵闹的 `aria-live`。
- **响应式栅格**：`>1120px` 展示 `224px` 完整侧栏；`<=1120px`（含 `1024×720` 窗口）自动收起文字为 `76px` 图标导航栏；`<=680px` 折返为顶部横向导航条。

---

## 四、阶段四：改版后真实渲染审查与缺陷闭环

搭建临时隔离子库环境，先导入内置 MIDI 夹具、合成 `melody_sample.wav` 并通过 `/v1/jobs/transcribe` 真机调用 `builtin-mono` 完成转录，再导入多和弦曲目，在 `dist/` 构建产物上通过 Chrome DevTools Protocol（CDP）采集 **6 视图 × 3 视口共 12 张实拍截图**。

1. **首轮视觉复查发现并修复的 3 项细节**：
   - 修复 `.file-picker-wrap` 内 `input[type="file"]` 命中全局输入框样式导致的“双重边框”视觉瑕疵。
   - 在 `index.html` 中嵌入轻量内联 SVG 图标，消除浏览器默认请求 `/favicon.ico` 触发的 404 控制台报错。
   - 在 `useLyraStore.ts` 中增加 `?song=<id>` URL 初始化选中支持，使转谱页截图真实锁定含音频来源并可点击启动转谱的曲目。
2. **修复后 12 次实拍度量结果（全绿：0 溢出 · 0 控制台报错）**：

| 截图 / 视口 | H1 标题核验 | `docScrollW <= winInnerW` | `mainScrollW == mainClientW` | 控制台 Error | 真实渲染截图 |
|---|---|---|---|---|---|
| 首页 (`1440×900`) | LyraForge 编曲与演奏工作台 | `1440 <= 1440` | `1216 == 1216` | `0` | [home.png](assets/ui/home.png) |
| 本地曲库 (`1440×900`) | 本地曲库与工程归档 | `1425 <= 1440` | `1201 == 1201` | `0` | [library.png](assets/ui/library.png) |
| AI 转谱 (`1440×900`) | AI 音乐转谱与智能编曲 Agent | `1440 <= 1440` | `1216 == 1216` | `0` | [transcribe.png](assets/ui/transcribe.png) |
| 编曲工作室 (`1440×900`) | 编曲工作室 & Piano Roll | `1425 <= 1440` | `1201 == 1201` | `0` | [studio.png](assets/ui/studio.png) |
| 试听与演奏 (`1440×900`) | 试听、导出与游戏演奏控制台 | `1440 <= 1440` | `1216 == 1216` | `0` | [playback.png](assets/ui/playback.png) |
| 设置与模型 (`1440×900`) | 设置、MCP 接入与转谱引擎诊断 | `1425 <= 1440` | `1201 == 1201` | `0` | [settings.png](assets/ui/settings.png) |
| 紧凑 (`1024×720`) 4 视图 | home / library / studio / playback | `1009 <= 1024`（全部） | `933 == 933`（全部） | `0` | 已逐张视觉检查 |
| 宽屏 (`1920×1080`) 2 视图 | home / studio | `1920<=1920` · `1905<=1920` | `1696==1696` · `1681==1681` | `0` | 已逐张视觉检查 |

---

## 五、阶段五：最终全量门禁与能力边界说明

在最后一次代码与资源编辑后执行全量检验：
- **依赖锁校验**：`pnpm --dir apps/desktop/web install --frozen-lockfile` → `pnpm v12.6.0` 通过（`42ms`）。
- **代码静态规范**：`uv run ruff check .` → `All checks passed!`。
- **后端全量测试与覆盖率**：`uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **117 passed, 1 warning in 24.63s**，总覆盖率 **87.13%**。
- **前端单元测试与构建**：
  - `vitest run` → **Test Files 4 passed (4), Tests 6 passed (6)**（含 `App.spec.ts` 6 视图导航与 IME 拦截测试、新增 `PianoRollInteractions.spec.ts` 缩放/吸附/快捷键/拖拽测试、`PianoRollEditor.spec.ts` 与 `LyreKeyboard.spec.ts`）。
  - `vue-tsc --noEmit && vite build` → `0.85 kB` HTML / `19.86 kB` CSS / `152.57 kB` JS（`787ms`）。
- **端到端 DryRun 冒烟（`make smoke`）**：退出码 `0`（48 动作，0 残留按键）。
- **音频转谱基线（`uv run python scripts/eval_transcribers.py`）**：
  - `builtin-mono`：`solo_melody` `F1 = 1.0`（`166.86 ms`），`fixture_c_major_scale_wav` `F1 = 1.0`（`205.06 ms`），`dense_multi_register` `F1 = 0.3333`（`148.4 ms`），`fixture_chords_type1_wav` `F1 = 0.1818` / 适配分 `91.98`（`677.71 ms`），`polyphonic_piano_chords` `F1 = 0.0`（`139.19 ms`）。
  - 外部引擎：`ffmpeg`、`basic-pitch`、`dettato` 在当前 macOS 环境中均未安装（`available = false`），界面在转录选择器与设置诊断卡如实标示不可用原因。

### 待跨平台真机验证清单
- Windows 10/11 实体机运行 PyInstaller 产出的 `LyraForge.exe`、完成《原神》21 键实音校准与前景焦点切换测试。
- 配置隔离 `basic-pitch` / `dettato` 与 `ffmpeg` 环境后的桌面端多声部音频全链路实测。
