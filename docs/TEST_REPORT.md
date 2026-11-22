# LyraForge 第四轮全量测试与验收基准报告

> **记录原则**：本报告仅记录在最终提交代码后**实际执行并直接观察到输出**的命令、结果、耗时与未验证环境边界，绝不外推未运行的 Windows 真机或外置 ML 工具状态。

---

## 1. 本地质量门禁总览（macOS Apple Silicon）

**执行环境**：`darwin` (macOS), Python `3.11.13`, `uv`, Node.js, `pnpm 12.6.0`, Headless Google Chrome（外部工具 `ffmpeg` / `basic-pitch` / `dettato` / `codex`：**未安装**；本机含 `/opt/homebrew/bin/claude` `2.1.267`，未污染全局配置）。

| 检查项 | 执行命令 | 实测结果 |
|---|---|---|
| **前端锁文件一致性** | `pnpm --dir apps/desktop/web install --frozen-lockfile` | 通过（`39ms`, `pnpm v12.6.0`, zero lockfile drift） |
| **Python 静态检查** | `uv run ruff check .` | 通过（`All checks passed!`） |
| **Python 单元 + 集成测试** | `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` | **122 passed**, 2 deprecation warnings (`26.65s`)；总语句+分支覆盖率 **86.53%**（5558 stmts, 586 miss, 1404 branches, 258 part，超过 80% 门禁） |
| **前端类型检查 + 构建** | `pnpm --dir apps/desktop/web build` (`vue-tsc --noEmit && vite build`) | 通过（`833ms`；`dist/index.html` `0.85 kB`, CSS `20.52 kB`, JS `158.80 kB`） |
| **前端组件与交互单测** | `pnpm --dir apps/desktop/web test` (`vitest run`) | **Test Files 4 passed (4), Tests 6 passed (6)**（`1.70s`） |
| **CLI Dry-Run 冒烟** | `make smoke` | 退出码 `0`：`actions_sent=48`, `keys_still_pressed=[]`, `max_lateness_ms=0.0`, `mode="virtual"`, `sent_os_input=false`, `state="completed"` |
| **桌面可执行自检** | `uv run lyraforge desktop --self-check` | 退出码 `0`：`{"ok": true, "platform": "darwin", "profiles": ["genshin.windsong_lyre.v1", "genshin.floral_zither.v1"], "version": "0.1.0.dev0", "windows_modules_loaded": false}` |

---

## 2. 第四轮专项加固回归验证（`tests/unit/test_round4_hardening.py`）

本次新增 5 个端到端安全/稳定性/协议专项用例并纳入 `make check` 全量集（均已实跑通过）：

1. `test_subprocess_pipe_flood_no_deadlock_and_webm_supported`：模拟子进程持续写入 >160 KB `stdout` 与 >160 KB `stderr` 验证无管道死锁、报错保留尾部摘要 `TAIL_END`，并确认 `.webm` 允许导入提取。
2. `test_player_pause_resume_escape_stop_and_multi_song_sequence`：使用 `PauseToken` 与物理按键回调在音符执行中暂停（确认所有按键立刻释放 `pressed == []`）、等待后恢复无连发跳变、触发 ESC 中断并支持连续曲目切换，随后执行 500 音符长谱压力调度验证 `keys_still_pressed == []`。
3. `test_library_tag_exactness_single_read_pianoroll_clamp_and_zip_reserved`：验证单次哈希导入 MIDI、标签精确筛选不被 `c` 子串误命中 `classical`、Piano Roll 同键重叠事件去重与时长安全钳制，以及恶意 ZIP 内 `CON.txt` 等 Windows DOS 保留文件名拦截。
4. `test_api_restore_pause_resume_allowed_titles_cli_ssrf_and_llm_guards`：FastAPI `TestClient` 与 `lyraforge library restore` 实测全库 ZIP 恢复、`/v1/playback/pause` + `resume` + `stop`、系统 `HTTP_PROXY` 被 `ProxyHandler({})` 绕过保护，以及 `OpenAICompatibleLLMProvider` 对 1 MB 响应截断和 `"transpose": "auto"` 安全兜底。
5. `test_mcp_negotiation_validation_midflight_cancel_and_desktop_self_check`：启动真实 `python -m lyraforge.cli mcp` 子进程执行 `initialize` 未知协议版本协商（返回 `"2025-03-26"`）、参数越界/布尔混淆校验、8 秒音频耗时转录过程中通过 `stdio` 发送 `notifications/cancelled` 并发取消（`thread_local` 连接隔离无崩溃），以及 `desktop --self-check` 返回码 0。

---

## 3. 五类音频转谱与端到端编曲分离式基准（`scripts/eval_transcribers.py`）

> **严格指标隔离说明**：下表将「**音频转录还原度**（对比参考 MIDI 真值）」与「**相对已转录 MIDI 的编曲适配分**」及「**端到端相对原始参考音符的真实召回**」明确分开，禁止用编曲适配分掩盖多声部转录损失。  
> **当前主机可用引擎**：`builtin-mono (available=true)`；`ffmpeg_available=false`、`basic-pitch.available=false`、`dettato.available=false`。

| 评测类别 | 用例 ID | 转谱 P / R / F1 | 主旋律 R / F1 | 起音误差 (ms) | 漏检 / 误报 | 编曲适配分 (相对转录 MIDI) | 端到端参考召回 (总 / 主旋律) | 耗时 (ms) |
|---|---|---|---|---|---|---|---|---|
| **单音旋律** | `solo_melody` | `1.00 / 1.00 / 1.0000` | `1.00 / 1.0000` | `0.0` | `0 / 0` | `100.0` | `1.0000 / 1.0000` | `169.88` |
| **钢琴独奏（主旋律+琶音）** | `solo_piano_arpeggio` | `0.70 / 0.6364 / 0.6667` | `1.00 / 0.5714` | `28.0` | `4 / 3` | `92.36` | `0.5455 / 1.0000` | `137.61` |
| **和弦及多声部** | `polyphonic_piano_chords` | `0.00 / 0.00 / 0.0000` | `0.00 / 0.0000` | `0.0` | `12 / 4` | `100.0` | `0.0000 / 0.0000` | `134.39` |
| **人声与伴奏混合** | `vocal_with_accompaniment` | `0.20 / 0.20 / 0.2000` | `0.00 / 0.0000` | `42.5` | `8 / 8` | `90.91` | `0.1000 / 0.0000` | `192.38` |
| **多乐器复杂编曲** | `multi_instrument_complex` | `0.33 / 0.1667 / 0.2222` | `0.00 / 0.0000` | `12.0` | `10 / 4` | `96.65` | `0.1667 / 0.0000` | `161.66` |
| **MIDI夹具渲染WAV（单音）** | `fixture_c_major_scale_wav` | `1.00 / 1.00 / 1.0000` | `1.00 / 1.0000` | `0.0` | `0 / 0` | `100.0` | `1.0000 / 1.0000` | `208.60` |
| **MIDI夹具渲染WAV（多声部）** | `fixture_chords_type1_wav` | `0.25 / 0.1429 / 0.1818` | `0.1429 / 0.1818` | `18.0` | `24 / 12` | `91.98` | `0.1429 / 0.1429` | `677.75` |

- **完整业务闭环 `pipeline_roundtrip`（导入音频 → 转录 → 编曲 → 渲染试听 WAV → 编辑 → 保存新版 → 再试听）**：
  - `ok: true`, `transcribed_notes: 8`, `arranged_events: 8`, `preview_wav_bytes: 155276`, `edited_preview_wav_bytes: 155276`。

---

## 4. 实时 Chrome CDP 交互式与跨分辨率前端实测摘要

通过真实 FastAPI 后端 (`127.0.0.1`) + 无头 Chrome DevTools Protocol 驱动真实点击与多分辨率/High-DPI 渲染，共检查 14 次视口采样与 4 项端到端前端交互（详细图文见 [UI_REVIEW.md](UI_REVIEW.md)）：

- **视口零溢出**：`1440×900@1x`（6 视图）、`1440×900@2x`（High-DPI）、`1024×720@1x`、`1920×1080@1x` 共 **14 次截屏**全部满足 `docScrollW <= winInnerW`、`mainScrollW == mainClientW`、`hasFooterTransport == true` 且 `console_errors == []`。
- **端到端交互实测（4 / 4 通过）**：
  - Studio 点击 `生成 A/B 对比版本` 并渲染对比卡片：`passed`
  - Piano Roll 点击选中音符 → `+50ms` → `保存为新版本`（版本下拉从 2 增至 3）：`passed`
  - Studio 点击 `试听当前版本` → 底部 `<footer class="studio-transport"> audio[src^="blob:"]` 加载成功，切页至 `本地曲库` 后音频对象依然持续存在：`passed`
  - Playback 视图完整执行 `1. 准备演奏` → `2. 确认授权开始` → 出现暂停状态 → 点击 `暂停演奏` → 进入 `paused` → 点击 `继续演奏` → 点击 `紧急停止`：`passed`

---

## 5. 待完成的 Windows 10/11《原神》真机验收清单（Executable Checklist）

由于 GitHub Actions `windows-latest` Runner 不安装《原神》客户端且缺乏物理桌面游戏前台交互，以下操作需由项目所有者在 Windows 10/11 实体机上执行并回填结论：

```powershell
# 1. 解压 GitHub Actions 产物 LyraForge-windows-x64 并验证便携运行自检
.\LyraForge.exe --self-check
# 期望输出：exit code 0 且 JSON 包含 "ok": true, "windows_modules_loaded": true

# 2. 启动桌面工作台，验证无控制台弹窗报错且首页能正常导入 tests\fixtures\midi\c_major_scale.mid
.\LyraForge.exe

# 3. 凭据隔离检验：在“设置 -> 高级可选 HTTP 模型”填入临时占位 Key 并保存，重启后检查 Windows 凭据管理器存在条目，再清除
# 4. 切窗 & ESC 真机安全门控检验（先不打开或打开《原神》大世界自由演奏界面 —— 严禁在音游模式测试）：
#    a) 在“试听与演奏”选择“Windows 原神窗口 SendInput”，设置合适窗口白名单；
#    b) 切出游戏窗口至记事本，点击确认开始 -> 必须立即被 WindowGuard 拦截（零按键发出）；
#    c) 前台切回《原神》风物之诗琴自由演奏界面 -> 启动演奏 -> 核对实际按键声调（Z~M / A~J / Q~U 三行 21 键映射准确无误）；
#    d) 演奏中途测试“暂停/恢复”是否平稳顺延而非连发补键，按下实体键盘 Esc 或 Alt+Tab 切出游戏是否 1 帧级立即停键且零粘滞卡键。
# 5. （可选）配置独立环境中安装 ffmpeg 与 basic-pitch，使用真实人声/钢琴歌曲实测转谱与手动修音完整体验。
```

---

## 6. 第五轮 Code Review 加固专项复核与回归结果（基于 `051a222b`）

针对第五轮独立 Review 指出的 6 类工程隐患已完成代码修改与针对性回归（[tests/unit/test_round5_review_fixes.py](tests/unit/test_round5_review_fixes.py)，新增 **6 组端到端专项测试全部通过**；全库回归共 **128 passed**, 覆盖率 **87.75%**, 前端 Vitest **4 文件 / 6 用例全过**，无新增第三方依赖）：

1. **MCP 协议统一校验、并发有界线程池与竞态安全（`mcp/server.py`, `mcp/tools.py`）**：
   - 将消息解析、初始化检查（未初始化调用 `tools/call` 或 `tools/list` 统一返回 `-32002`）、`arguments` 对象类型严格校验（拒收字符串/数组/`null` 返回 `-32602`，绝不静默转 `{}`）及错误 JSON-RPC 处理收敛至单一 `_parse_and_route()`，`handle_message()` 与 `serve_streams()` 彻底消除分叉绕过。
   - 新增 `max_pending`（默认 16）排队上限超载拦截（`-32001`）、`_on_done` Future 与请求令牌释放回调、`notifications/cancelled` 在任务注册前（`_pre_cancelled`）、执行中（包含 `requestId=0`）与完成后（不回滚 `completed`）全相位处理、工作线程未捕获异常 `-32603` 兜底上报及断连取消清理；压力测试中同时暴露并顺带修复 `LibraryStore.arrange_song()` 与 `_import_validated_source()` 多线程并发同内容哈希写入 `UNIQUE constraint failed` 竞态。
2. **曲库恢复独占维护门控与 SQLite WAL 兼容（`errors.py`, `api/{app,job_service,playback_service}.py`, `library/{schema,store,packaging}.py`）**：
   - 新增 `ErrorCode.LIBRARY_BUSY` (`409`) 与 `_LibraryAccessGate`：恢复前阻塞新入读/写/转录/编曲/播放启动请求并排空在途请求，暂停新异步任务提交并向活动后台转录及播放线程发停机信号且严格核验线程确实退出；若有停滞线程未退出或外部连接正持有 SQLite 事务/WAL（`BEGIN EXCLUSIVE` + `PRAGMA journal_mode=DELETE` 检测），拒绝恢复并返回 `409 LIBRARY_BUSY`，保持原库完好且可继续正常使用。同时适配 Windows 文件句柄释放重试验退与生命周期关停排序。
3. **子进程日志有界内存/磁盘（`media/subprocess_utils.py`, `media/extract.py`, `transcribers/_subprocess.py`）**：
   - 使用双段轮转日志（`_BoundedRotatingLog`，默认单流上限 256 KB）与后台定量（4 KB）流式抽取替代无界写入及 `read_bytes()`；改由 `os.SEEK_END` / `seek()` 精确读尾，兼容现有零参单测桩，并确保正常/失败/取消/超时下清理 `.log`/`.log.1` 且不破坏模型输出 `.mid`/`.wav`。
4. **SQLite JSON1 标签精确检索（`library/schema.py`, `library/store.py`）**：
   - 注册 `py_lower()` 并采用 `json_valid(tags_json)` + `json_each()` 在 SQL 层精确匹配标签，配合 `LIMIT/OFFSET`、Unicode（`Café`/`原神`）、LIKE 特殊字符（`%`/`_`/`\`）与 600+ 曲目分页压测均一次精确命中且 0 截断。
5. **LLM 非有限浮点数安全解析（`agent/llm.py`）**：
   - 使用 `math.isfinite()` 强化 `_coerce_float`、`_coerce_int` 与 `_coerce_opt_int`，全面拦截 `"nan"`、`"inf"`、`"-inf"`、`1e308`、`"1e309"`、布尔与越界字符串并安全回退默认值。
