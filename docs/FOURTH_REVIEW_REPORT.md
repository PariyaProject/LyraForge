# LyraForge 第四轮全面审查、质量加固与 Alpha 验收报告

> **基准提交（`origin/main`）**：`9123a950ea362e59e714fb6b4127fe6cb79a2212`（`9123a95`，Run [#45006178921](https://github.com/PariyaProject/LyraForge/actions/runs/45006178921)）  
> **工作分支**：`fix/round4-audit-quality-hardening`  
> **审查日期**：2026-11-22  
> **开源许可**：GNU General Public License v3.0 ([LICENSE](../LICENSE)) —— 终局许可协议，本轮未做变更

---

## 1. 本轮审查范围与核心目标

本轮围绕「从研发样机迈向**可靠可用的 Alpha 产品**」展开独立代码审计与实机/无头环境验证，覆盖七大维度：
1. **音视频提取与转录流水线**：子进程 I/O 死锁风险、格式支持与失败诊断保留；
2. **游戏自动演奏驱动与安全门控**：Win32 `ctypes` 类型定义、`VK_ESCAPE` 物理键检测、暂停/恢复无补发突发、高精度混合时钟、Windows 焦点检查配置联动与桌面端条件判断；
3. **API、Desktop 生命周期与数据完整性**：TOCTOU 重复读入、SQLite 标签模糊越界、`Piano Roll` 邻近同键覆盖冲突、Windows 保留文件名 ZIP 攻击、全库恢复入口与服务停机清理；
4. **AI Agent / MCP Server 协议合规与稳定性**：协议版本协商、并发/取消阻塞、`sqlite3` 跨线程访问异常、`limit`/整数布尔混淆参数边界；
5. **网络隔离与 LLM 边界防护**：外部下载代理变量绕过固定 DNS、`OpenAICompatibleLLMProvider` 响应体体积与非数字字段强韧解析；
6. **Windows EXE 打包可靠性**：PyInstaller 隐藏导入、缺失前端产物静默跳过、`LICENSE` 随包分发、`LyraForge.exe --self-check` 冒烟门禁；
7. **前端交互连续性与 High-DPI 布局质量**：全局持续试听栏、暂停/恢复交互、首页新手引导、库恢复交互及实机 Chrome CDP 多分辨率审计。

---

## 2. 发现与修复的工程缺陷清单（BUG-401 ～ BUG-408）

| 编号 | 严重度 | 模块与文件 | 缺陷根因与实际影响 | 修复方案与回归验证 |
|---|---|---|---|---|
| **BUG-401** | **P0 阻塞** | `src/lyraforge/transcribers/_subprocess.py`<br>`src/lyraforge/media/extract.py` | 转录隔离进程与 `ffmpeg` 提取均在轮询循环内读取 `subprocess.PIPE`，当外部工具连续输出 >64 KB 日志或报错时触发 OS 管道缓冲区写满死锁；同时媒体扩展列表缺少 `.webm`。 | 将子进程 stdout/stderr 改写至任务目录临时文件并读取尾部摘要；加入 `.webm` 到 `SUPPORTED_MEDIA_EXTENSIONS`；`test_subprocess_pipe_flood_no_deadlock_and_webm_supported` 验证 160 KB 输出/错误无死锁且保留尾部 `TAIL_END`。 |
| **BUG-402** | **P0 安全 / 平台缺陷** | `apps/desktop/web/src/views/PlaybackView.vue`<br>`src/lyraforge/playback/windows/win32_types.py`<br>`src/lyraforge/playback/windows/driver.py`<br>`src/lyraforge/playback/{clock,guards,player}.py`<br>`src/lyraforge/api/playback_service.py` | 1. **前端严重 Bug**：`PlaybackView.vue` 将 `platform !== 'windows'` 作为禁用条件，而 Python `sys.platform` 在 Windows 返回 `'win32'`，导致真机 Windows 无法选中使用游戏演奏选项。<br>2. **Win32 与时序缺陷**：`ULONG_PTR`/`SendInput` 缺少严格 `ctypes` 签名；缺乏 `GetAsyncKeyState(VK_ESCAPE)` 物理按键检测；Windows 模式下未强制 `realtime=True`（存在 `VirtualClock` 瞬间连发风险）；缺少不产生恢复连发的 `PauseToken`；纯 `sleep` 时钟在高频音符窗口抖动大。 | 前端改用 `!store.health.value?.windows_playback_available`；补充 `ctypes.c_size_t` 与完整 `SendInput` 签名；实现 `VK_ESCAPE` 急停与线程安全的 `pressed_snapshot()`；`PauseToken` 暂停时立即 `release_all()` 并在恢复时顺延后续事件基准；`MonotonicClock.sleep_us()` 末端 ~1.5 ms 自旋微调；`PlaybackMode.WINDOWS` 强制 `effective_realtime=True`。 |
| **BUG-403** | **P1 可用性 / 生命周期** | `src/lyraforge/api/app.py`<br>`src/lyraforge/api/job_service.py`<br>`src/lyraforge/desktop/launcher.py` | API 缺少 `POST /v1/library/restore`；`/v1/playback/prepare` 未将设置中的 `windows_allowed_titles` 传入守护器；进程退出缺少优雅释放后台转录/演奏任务的 `lifespan` 与 `finally` 清理。 | 新增 `/v1/library/restore`、`/v1/playback/pause`、`/v1/playback/resume`；接入配置 `windows_allowed_titles` 回退；增加 `TranscriptionJobManager.cancel_all()`、FastAPI `lifespan` 与启动器 `finally` 清理。 |
| **BUG-404** | **P1 数据完整 / 跨平台** | `src/lyraforge/library/store.py`<br>`src/lyraforge/library/packaging.py`<br>`src/lyraforge/cli.py` | `import_midi()` 存在双重读取风险；`search_songs(tag=...)` SQL `LIKE` 未转义通配符且发生子串误命中；`save_edited_arrangement()` 在 Piano Roll 相邻音符微调后未去重/钳制 `hold_ms`，易触发 `validate_performance` 拒存；ZIP 解包未阻断 Windows DOS 保留设备名（`CON`/`NUL`/`COM1` 等）。 | `import_midi()` 单次读入计算哈希；`search_songs(tag=...)` 精确匹配标签并转义 `LIKE`；编辑保存执行 `(at_ms, key_id)` 去重与安全持续时间钳制；ZIP 路径校验证拒 Windows 保留名与尾随空格/点；新增 `lyraforge library restore` CLI。 |
| **BUG-405** | **P1 安全 / 强韧性** | `src/lyraforge/sources/{url,online}.py`<br>`src/lyraforge/agent/llm.py` | 尽管实现 DNS 固定与 SSRF 校验，全局 `HTTP_PROXY`/`HTTPS_PROXY` 仍可能劫持 `urllib` 默认 opener；HTTP LLM 解析遇到超长响应体或 `"transpose": "auto"` 等非数字字段易抛出未预期异常。 | 在直连与在线源构建器显式注入 `urllib.request.ProxyHandler({})` 并验证 default vs disabled opener；`OpenAICompatibleLLMProvider` 限制响应上限 1 MB 并安全转换可选参数。 |
| **BUG-406** | **P0/P1 MCP 协议合规** | `src/lyraforge/mcp/{server,tools}.py` | 1. 收到未知 `protocolVersion` 时向下降级而非协商最新受支持版本。<br>2. `serve_streams` 主循环同步阻塞执行 `tools/call`，导致耗时转录任务进行期间无法响应 `notifications/cancelled` 取消通知。<br>3. 若跨线程执行工具而复用主线程 SQLite 连接会引发跨线程报错；参数 `limit` 接受 `bool` (`True`/`False`) 且缺乏统一边界校验。 | 统一协商返回 `"2025-03-26"`；采用有界 `ThreadPoolExecutor(max_workers=4)` + 写锁 + `_thread_store()` 线程局部连接处理请求，主循环持续监听 stdin 取消帧；新增 `_bound_int()` 严格拒绝布尔值与越界值。真实子进程 `stdio` 实测验证。 |
| **BUG-407** | **P0 发布打包** | `packaging/lyraforge.spec`<br>`scripts/build_windows.ps1`<br>`.github/workflows/ci.yml` | 1. 若 `apps/desktop/web/dist/index.html` 不存在，`spec` 仅静默跳过打包空外壳。<br>2. 缺少 `python_multipart`/`uvicorn` 运行时隐式模块与根目录 `LICENSE`、`docs/LICENSE_AUDIT.md`。<br>3. CI 只检查 `.exe` 文件存在但未试运行。 | 强制要求 `dist/index.html` 存在否则构建直接报错；补齐 `hiddenimports` 与许可文件；实现 `lyraforge desktop --self-check`，并在 `build_windows.ps1` 与 CI `package-windows` 作业真实执行 `LyraForge.exe --self-check`。 |
| **BUG-408** | **P1 UI/UX 连续性** | `apps/desktop/web/src/App.vue`<br>`apps/desktop/web/src/styles/global.css`<br>`apps/desktop/web/src/views/{HomeView,LibraryView,StudioView,PlaybackView}.vue` | 试听音频 `<audio>` 仅局限在局部视图，切换页面即中断；首页缺 3 步新手引导；库页面缺全库 ZIP 恢复入口；非滚动锁定的壳层会导致较高视图下底部控制区被挤出首屏。 | 桌面壳层改为 `block-size: 100dvh` 分区独立滚动 + 固定底部全局 `<footer class="studio-transport">`；新增首页 3 步引导、工作室直接试听、曲库 ZIP 恢复、播放暂停/继续控件及 `ToastStack` 避让高度。 |

---

## 3. 代码质量与关键边界现状核对

- **架构隔离验证**：`tests/unit/test_layering.py` 验证 `src/lyraforge/music_core` 零依赖 Windows `ctypes`/UI，保持纯粹跨平台无头计算引擎。
- **三层 AI 与零强制 API Key 架构**：本地默认 `RuleBasedLLMProvider` 完全离线；MCP `stdio` 服务与本地 `RuleBasedLLMProvider` 均无需外部 Key，也绝不读取/借用用户个人 OAuth 凭据；可选 HTTP 模型 Key 仅走 Keychain / Credential Manager / `0o600` 文件 / 环境变量。
- **诚实能力边界**：
  - 内置 `builtin-mono`（纯 Python YIN）在独奏单音旋律下 `F1 = 1.0000`，但在纯和弦伴奏与多乐器复杂混音下受单音算法限制分别录得 `F1 = 0.0000` 和 `F1 = 0.2222`（详情见 [TEST_REPORT.md](TEST_REPORT.md)）。
  - 当前 macOS 开发机未安装 `ffmpeg`、`basic-pitch` 和 `dettato`；相关封装与隔离协议已在模拟/隔离进程测试验证，但外部 ML 模型实音识别精度尚未在本机实测。

---

## 4. Alpha 发布准备度结论（Go / No-Go）

| 发布定位 | 判定 | 依据与前置要求 |
|---|---|---|
| **开源工程源码与 CI 技术预览版（Alpha Tech Preview）** | **GO（建议放行）** | 本地 122 项 Python 测试（86.53% 覆盖率）、前端 Vitest 4 文件 6 测试、`vue-tsc` + Vite 构建、Chrome CDP 14 项实机视觉与交互全流程、`eval_transcribers.py` 端到端闭环，以及双平台 CI（含 `LyraForge.exe --self-check`）全部验证通过。 |
| **公开宣传“开箱即用《原神》实机稳定演奏”（Stable / Game Release）** | **NO-GO（暂缓放行）** | **Windows 10/11 实机《原神》21 键实音校准、全曲节奏延迟实测、切窗/ESC 物理按键全松开验收**以及 **`basic-pitch` / `dettato` / `ffmpeg` 外置环境联调**尚无真机实测记录。必须按 [TEST_REPORT.md](TEST_REPORT.md) §5 清单在 Windows 实体机逐项签收后，方可摘除“Alpha / 未经实机校准（`calibration.status="unverified"`）”警示。 |
