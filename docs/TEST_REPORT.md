# LyraForge 测试报告与验收基准（Test Report）

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

针对第五轮独立 Review 指出的 6 类工程隐患已完成代码修改与针对性回归（[tests/unit/test_round5_review_fixes.py](../tests/unit/test_round5_review_fixes.py)，新增 **6 组端到端专项测试全部通过**；全库回归共 **128 passed**, 覆盖率 **87.64%**, 前端 Vitest **4 文件 / 6 用例全过**，无新增第三方依赖）：

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

---

## 7. 第六轮稳定性收敛专项复核与回归结果（基于 `34f08ce`）

针对第六轮 Code Review 剩余边界问题已完成最小化高可靠改造与全量回归验证（[tests/unit/test_round6_review_fixes.py](../tests/unit/test_round6_review_fixes.py)，新增 **4 组专项回归全通**；全库回归共 **132 passed**, 覆盖率 **86.49%**, 前端 Vitest **4 文件 / 6 用例全过**, Vite 构建 **757ms**, 无新增第三方依赖）：

1. **事务型曲库目录切换恢复与断点自动回滚（`library/packaging.py`, `library/store.py`, `library/__init__.py`）**：
   - 在触碰目标库前执行 `_check_target_files_unlocked()` 与 `_verify_and_quiesce_existing_db()`，先于目录外部准备并校验证明完整的 `prepared_dir` 与 `rollback_dir`，再通过 `.restore-txn.json` + 目录原子重命名（`_rename_dir_with_retry()`）实施无就地删档切换。
   - 捕获 `BaseException`（含 `KeyboardInterrupt`）执行原子回退；若双重故障（回滚期同样遇锁）发生，设置 `keep_snapshots = True` 完整保留快照并携带 `manual_recovery_steps` 抛出 `LIBRARY_BUSY`，同时 `LibraryStore.__init__` / `recover_interrupted_restore()` 可在重启后自动自愈未完成恢复事务。
2. **MCP `MCPTaskRegistry` 活动任务零驱逐保护（`mcp/tools.py`）**：
   - 引入 `MCPTaskRecord.finished`（取消中至多等待工线程 `finish()` 才标完成）、`active_count()` 与 `_reclaim_finished_locked()`，严禁驱逐未完成活动任务；满载时返回可恢复错误 `ErrorCode.LIMIT_EXCEEDED` 并保持已有活动任务的进度查询与取消关联完整，淘汰已完结记录时同步清理过期 `_request_to_task` 映射。
3. **非转录 MCP 工具与底层业务协作式取消（`mcp/tools.py`, `music_core/arranger.py`, `preview/synth.py`, `sources/{local,url,online}.py`, `library/store.py`）**：
   - 移除 `lambda ...: _st` 忽略路径，将 `search_music`/`import_media`/`transcribe`/`arrange`/`evaluate`/`preview`/`save_to_library`/`export_score` 纳入统一 `_run_tracked()` 追踪与 `StopToken`/`is_cancelled` 检查，确保执行前、流式下载/移调搜索/波形合成中途以及写数据库提交前取消均可清理新建孤儿产物并返回 `PLAYBACK_ABORTED`，且已提交事务或原子写入后的迟到取消绝不错误标记为失败。
4. **外部子进程及其派生进程树生命周期（`media/subprocess_utils.py`, `media/{extract.py}`, `transcribers/_subprocess.py`）**：
   - 隔离会话/进程组启动（`start_new_session=True` / `CREATE_NEW_PROCESS_GROUP`、`stdin=DEVNULL`、`close_fds=True`），终止时使用 POSIX `os.killpg` 与 Windows `taskkill /F /T` + `Win32_Process` 后代递归清扫；即使父进程已退出而孙进程仍继承持有 `stdout`/`stderr` 管道亦能识别并安全回收，并在所有排空线程完全结束及管道关闭后再执行轮转日志清理，避免 Windows 句柄竞争与跨线程并发关闭隐患。

---

## 8. 第七轮收尾回归、源码核验与质量验收结果（基于 `e9570fa`）

针对第七轮 Code Review 收尾检查（[tests/unit/test_round7_review_fixes.py](../tests/unit/test_round7_review_fixes.py)，新增 **2 组专项回归测试全过**；全库回归共 **134 passed, 2 warnings in 42.42s**，语句+分支总覆盖率 **86.52%**（6615 stmts, 1830 branches），前端 Vitest **4 文件 / 6 用例全过（1.46s）**，Vite 构建 **714ms**，无新增第三方依赖）：

1. **并发试听取消防文件误删回归（`src/lyraforge/fs.py`, `src/lyraforge/library/paths.py`, `src/lyraforge/library/store.py`）**：
   - **修复前复现**：请求 B 完成 `render_preview()` 写入 `wav_path` 并更新 `arrangements.preview_path` 后，原本先于 B 启动的请求 A 因旧逻辑依赖 `existed_before = False`，在合成结束后遭遇 `StopToken` 取消并直接 `unlink(wav_path)`，导致共享 WAV 丢失而 `preview_path` 仍指向不存在的路径。
   - **最小修复与验证**：新增 `atomic_replace_file()`（按目标路径条带加锁 + Windows `PermissionError` 重试）；`render_preview()` 先写入单次调用专属同目录临时 WAV，在锁下再次核验 `StopToken` 后执行 `os.replace` 原子发布并立即更新 SQLite，`finally:` 仅清理当前请求自身临时文件。覆盖并发竞争、全新曲目取消、合成异常保留历史版本、连续多采样率重生成、发布后迟到取消等场景全部通过，零 `.tmp*` 残留。
2. **子进程终态排空与日志清理并发收尾（`src/lyraforge/media/subprocess_utils.py`）**：
   - **修复前复现**：模拟 `_terminate_process_tree()` 在超时/取消分支抛异常时，`reap_attempted = True` 被过早赋值导致 `finally:` 跳过回退清理、子进程继续存活且遗漏 `.log` 文件；POSIX 下独立会话（`start_new_session=True`）孙进程持管道退出后，原 `BufferedReader.read(4096)` 与先 `join` 后 `stop_drain.set()` 的时序亦会丢弃 `PARENT_DONE` 并遗留活跃 `-drain` daemon 线程。
   - **最小修复与验证**：POSIX FIFO 管道改用 `selectors.DefaultSelector()` + `os.read()` 可中断非阻塞轮询（Windows/测试桩保留兼容 `.read()` 回退）；`_BoundedRotatingLog.read_tail()` 持锁原子关闭并快照状态；新增 `_safe_terminate_process_tree()`（失败时回退 `killpg`/`proc.kill()`/`wait()`）；延后 `reap_attempted = True` 至真实返回之后；`finally:` 先 `stop_drain.set()` 再 `join`，并先 `out_log.close()`/`err_log.close()` 后清理磁盘日志。实测全部回归（含脱管孙进程、阻塞 Mock 管道延迟释放、Reap 失败与超限轮转日志）均零泄漏且零进程残余。同时顺带修复 GitHub macOS CI 暴露的 [src/lyraforge/api/app.py](../src/lyraforge/api/app.py) `_LibraryAccessGate.exclusive()` 退出时因 `_shutting_down=True` 未清除 `_maintenance_reason` 而导致 `begin_shutdown()` 空等超时的竞态缺陷。
3. **重点源码深度核验记录（只读核验通过，未做无意义重构）**：
   - [src/lyraforge/library/packaging.py](../src/lyraforge/library/packaging.py)：核验 `restore_backup_zip()` 与 `recover_interrupted_restore()` 通过 `.restore-txn.json`、`prepared_dir` / `rollback_dir` / `displaced_dir` / `failed_dir` 目录原子切换、`BaseException` 自动回滚以及回滚二次失败时 `keep_snapshots = True` + `manual_recovery_steps` 完整自愈。
   - [src/lyraforge/mcp/tools.py](../src/lyraforge/mcp/tools.py)：核验 `MCPTaskRegistry` 使用 `finished` 与 `_reclaim_finished_locked()` 严禁驱逐活动/取消中任务，满载返回 `LIMIT_EXCEEDED`，全部工具通过 `_run_tracked()` 与 `_pre_cancelled` / `StopToken` 一致跟踪。
   - [tests/unit/test_round6_review_fixes.py](../tests/unit/test_round6_review_fixes.py)：核验 4 组测试真实注入 DB 事务锁、只读文件锁、`PermissionError`、目录换名失败、回滚双重失败、中断重启、`max_tasks=1/3` 与 10 线程压测、`asyncio`/流式取消、孙进程树与孤儿管道等故障场景。
4. **本地全量门禁与文档规范验证**：
   - `pnpm --dir apps/desktop/web install --frozen-lockfile`（`209ms`）、`uv run ruff check .`（`All checks passed!`）、`uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80`（`134 passed`, `86.52%`）、`pnpm --dir apps/desktop/web build`（`714ms`, JS `158.80 kB`, CSS `20.52 kB`）、`pnpm --dir apps/desktop/web test`（`4 files / 6 tests passed`）、`make smoke`（`actions_sent=48`, `keys_still_pressed=[]`）、`uv run lyraforge desktop --self-check`（`ok: true`, `platform: "darwin"`, `windows_modules_loaded: false`）。
   - 验证 [README.md](../README.md) Quick Start 命令行可用（`lyraforge profiles list` 与 `lyraforge import tests/fixtures/midi/chords_type1.mid`），并将 README 规范为面向用户和贡献者的产品主页（长期规则写入 [AGENTS.md](../AGENTS.md)）。

---

## 9. GitHub Releases 自动发布流水线验证（基于 `dda4ef7`）

在保留单一 CI 工作流（[.github/workflows/ci.yml](../.github/workflows/ci.yml)）基础上扩展便携 ZIP 校验、SHA256 校验文件与最小权限 GitHub Releases 发布机制（[scripts/release_helper.py](../scripts/release_helper.py)、[tests/unit/test_release_workflow.py](../tests/unit/test_release_workflow.py)）：

1. **发布专项单元测试（5 组全部通过）**：
   - `test_resolve_release_plan_gating_and_naming`：验证 `pull_request` / 非 `main` 分支 / 畸形 Tag 严禁触发发布；`main` 推送与 `workflow_dispatch` 生成确定性 `dev-<YYYYMMDD>-<sha7>` 快照与固定 `dev-latest` 入口；`vX.Y.Z` / `vX.Y.Z-alpha.1` 生成独立 SemVer 计划。
   - `test_package_validate_and_sha256_checks`：验证 ZIP 根目录布局、`LICENSE`（GPL-3.0）、`_internal/` 依赖、前端 `dist/`、乐器与 Schema JSON、`SHA256SUMS.txt` 校验以及缺失核心资产/泄露凭据的反向拦截。
   - `test_idempotent_publish_rolling_entry_pruning_and_semver_isolation`：Mock `gh` CLI 校验首次双发、同提交手动重跑零重复 Release/附件、跨提交安全移动 `dev-latest` 且清理旧附件、超限历史快照裁剪绝不波及 `dev-latest` 与既定 `v0.1.0` Tag，以及保护机制拒绝强移任何正式 SemVer Tag。
   - `test_ci_workflow_extends_existing_build_with_minimal_permissions_and_gates` 与 `test_cli_package_and_publish_entrypoints`：静态审计 `contents: read` / 隔离 `contents: write` / `Expand-Archive` + `--self-check` 烟测与 `package`/`publish` CLI 入口全通。
2. **本机全量门禁实测结果**：
   - `pnpm --dir apps/desktop/web install --frozen-lockfile`（`57ms`）、`uv run ruff check .`（`All checks passed!`）、`uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80`（**`139 passed, 2 warnings in 41.56s`**，总覆盖率 **`86.52%`**）、`vitest`（`4 files / 6 tests passed`）、`vite build`（`775ms`）、`make smoke` & `lyraforge desktop --self-check`（均退出码 `0`）。

---

## 10. Windows 预发行包「双击无反应」根因定位与修复验证（针对 `a8a42de` 的 `dev-latest`）

1. **现象复现（Windows 10/11 x64）**：
   - 下载 `LyraForge-dev-20261123-a8a42de-windows-x64.zip`（`17,755,710` bytes）解压后双击 `LyraForge/LyraForge.exe` 无任何窗口；在可继承 stderr 的控制台内启动约 `1.0 s` 后退出（exit code `1`），唯一输出为 `error [SOURCE_UNAVAILABLE]: pywebview is not installed; install desktop extra with 'uv sync --extra desktop'`。
   - 同一 EXE 执行 `--self-check` 退出码 `0`（`ok: true`, `windows_modules_loaded: true`），说明旧门禁只校验了 Web 资源与服务端，**未校验 GUI 宿主**。
2. **根因分析**：
   - `src/lyraforge/desktop/launcher.py` 使用 `importlib.import_module("webview")` 动态导入 pywebview，PyInstaller 静态分析无法发现；`packaging/lyraforge.spec` 也未把 `webview` / `clr` / `webview.platforms.edgechromium` 列入 `hiddenimports`，因此 pywebview 与 pythonnet 的 `pyinstaller40` hook 从未加载，`_internal/` 内既无 `webview/lib/Microsoft.Web.WebView2.*.dll`、`WebView2Loader.dll`，也无 `pythonnet/runtime/Python.Runtime.dll`。
   - EXE 以 `console=False` 构建，`cli.main()` 将 `LyraError` 写入 stderr 后 `return 1`；双击场景既无控制台也无错误对话框，因此表现为“完全没有反应”。
3. **修复内容**：
   - spec 固化 GUI 宿主 hidden imports，并在 Windows 构建末尾断言 4 个 GUI payload 文件缺失即抛 `RuntimeError` 中止构建；`--self-check --check-gui` 真实导入 `webview` 与 `webview.platforms.edgechromium`（触发 pythonnet / WebView2 互操作 DLL 加载），冻结包自动要求该检查；新增 `src/lyraforge/startup_report.py` 将致命启动异常（含 traceback 与命令行）写入 `%LOCALAPPDATA%\LyraForge\logs\startup.log` 并弹出原生错误对话框；便携 ZIP 增加 `README.txt`，且 `release_helper.validate_release_zip()` 拒绝缺少 GUI payload 的归档。
4. **修复后实测（本机 Windows x64，源码重建）**：
   - 前端资源沿用发布 ZIP 内已构建的 `apps/desktop/web/dist`（本机未安装 `pnpm`，未重新构建 UI），`uv run --with pyinstaller pyinstaller --noconfirm --clean packaging/lyraforge.spec` 构建成功。
   - `dist/LyraForge/LyraForge.exe --self-check --check-gui` → 退出码 `0`，`gui_host.backend = "edgechromium"`, `gui_host.backend_ok = true`, `gui_host.version = "6.2.1"`。
   - 实际启动 `dist/LyraForge/LyraForge.exe`：`Get-Process` 观察到窗口标题 `LyraForge`，`CloseMainWindow()` 正常关闭且进程退出码 `0`。
   - 真实打包链路：`uv run python scripts/release_helper.py package ...`（`refs/heads/main`）生成 `LyraForge-dev-20261123-a8a42de-windows-x64.zip`（`18,591,276` bytes，`133` 个条目，含 `LyraForge/README.txt`、`webview/lib/Microsoft.Web.WebView2.Core.dll`、`pythonnet/runtime/Python.Runtime.dll`），`validate_release_zip()` 校验通过；解压该 ZIP 后执行 `LyraForge.exe --self-check --check-gui` → 退出码 `0`，再次启动可见窗口标题 `LyraForge` 并正常关闭（退出码 `0`）。
   - 自动化回归：`uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **`150 passed, 2 warnings in 33.30s`**，总覆盖率 **`85.86%`**（含新增 `tests/unit/test_desktop_startup.py` 与 `test_release_workflow.py` 的 GUI payload 反向用例）；`uv run ruff check .` → `All checks passed!`。
5. **仍未覆盖（如实标注）**：
   - 本次会话未安装 `pnpm`，故未重跑前端 `vitest`/`vite build` 与 `make smoke`。
   - `windows-latest` 上的 `--self-check --check-gui` 门禁已在 PR #10 与合并后 main 运行中实测通过。
   - 《原神》Windows 真机 21 键校准与游戏内实机演奏仍未执行（见 §5）。

---

## 11. 外部转录引擎 Windows 实机接通与适配器修复（2026-11-23）

1. **本机工具链安装（Windows x64）**：
   - `ffmpeg` 9.1（`winget install --id Gyan.FFmpeg`，`ffmpeg`/`ffprobe` 已在用户 `PATH`）。
   - `pnpm` 12.21.0（`npm install -g pnpm`）。
   - Basic Pitch 隔离环境：`uv venv …\LyraForge\tools\basic-pitch --python 3.11` + `basic-pitch==0.4.0`（TensorFlow `2.14.0`、`numpy 1.26.4`、`setuptools 80.10.2`）。
   - dettato 隔离环境：`uv venv …\LyraForge\tools\dettato --python 3.11` + `dettato==2.0.0`（`torch 2.15.0+cpu`；权重首次运行从 Hugging Face `kobimusic/dettato*` 下载）。
2. **真实环境暴露并修复的三个适配器缺陷**：
   - `basic-pitch` 0.4.x 的控制台入口是 `basic_pitch.predict`，旧的 `-m basic_pitch.inference` 在 0.4.0 下不会产生任何输出；
   - 中文 Windows 下子进程继承 `cp936`，Basic Pitch 的 emoji 进度打印触发 `UnicodeEncodeError` 直接中断转录；现统一向子进程注入 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`；
   - `dettato -o` 语义是输出**目录**（写出 `<stem>.mid`），旧实现传入 `…/dettato.mid` 文件路径导致找不到产物。
3. **端到端复验（`lyraforge` CLI，真实模型）**：
   - `uv run lyraforge engines list` → 三个引擎均 `available: true`，`runner` 分别为 `…\basic-pitch\Scripts\python.exe -m basic_pitch.predict` 与 `…\dettato\Scripts\python.exe -m dettato`。
   - 4 秒测试音频（`c_major_scale` 编曲后离线合成 WAV）：
     - `--engine basic-pitch` → 退出码 0，`raw_note_count = 8`，`duration_ms = 3986`；
     - `--engine dettato` → 退出码 0，`raw_note_count = 7`，`duration_ms = 3943`。
   - 用 `ffmpeg` 将 WAV 转 MP3 后 `--engine builtin-mono` → 退出码 0，`raw_note_count = 8`（验证非 WAV 提取链路）。
   - 回归：`uv run pytest --cov=lyraforge --cov-fail-under=80` → **`152 passed, 2 warnings in 34.63s`**，总覆盖率 **`85.86%`**；`uv run ruff check .` → `All checks passed!`。
4. **AI / MCP 接入实测**：
   - `claude mcp add -s user lyraforge -- D:\Code\LyraForge\.venv\Scripts\lyraforge.exe mcp` → `claude mcp list` 显示 `lyraforge … ✓ Connected`；Skill 已安装到 `~\.claude\skills\lyraforge-music-workbench\SKILL.md`。
   - Antigravity：`~\.gemini\config\mcp_config.json` 与 `~\.gemini\antigravity-ide\mcp_config.json` 写入同一 `mcpServers.lyraforge` 配置并通过 JSON 校验。
5. **仍未覆盖（如实标注）**：
   - 尚未用真实流行歌曲（人声+伴奏、多乐器混音）评估新引擎的实际转谱质量；本次仅验证链路可用与音符数。
   - 工具链目前仍需手工安装与环境变量配置；应用内一键安装属于下一阶段工作（见 [ROADMAP.md](ROADMAP.md) 优先级 C）。

---

## 12. 应用内一键安装外部工具链（2026-11-23）

1. **实现范围**：
   - CLI：`lyraforge tools status [--json]`、`lyraforge tools install [ffmpeg|basic-pitch|dettato|全部]`；
   - API：`GET /v1/tools`（状态 + 安装进度）、`POST /v1/tools/{id}/install`（后台线程安装，UI 轮询进度）；
   - 桌面设置页「外部工具与转谱引擎」卡片：显示已装/系统/未装、版本、许可、下载体积，一键安装并显示进度与错误；
   - 运行时代理：启动时把 `%LOCALAPPDATA%\LyraForge\tools` 下的 FFmpeg 与隔离解释器注入子进程环境，**不修改系统环境变量**，用户显式设置的同名变量优先。
2. **安装链路（真实执行，Windows x64，`LYRAFORGE_TOOLS_DIR=D:\...\tools-managed`）**：
   - `ffmpeg`：PyPI `imageio-ffmpeg` wheel（SHA-256 校验）→ 解压 `ffmpeg 9.0.2` → `-version` 校验通过；
   - `uv 0.13.9`：PyPI wheel 校验解压 → 由它安装托管 CPython 3.11；
   - `basic-pitch 0.4.0`（TF 2.14.0 / numpy 1.26.4 / setuptools 80.10.2）与 `dettato 2.0.0`（torch 2.15.0+cpu）安装到各自虚拟环境，`import` 探测通过。
3. **端到端复验（仅设置 `LYRAFORGE_TOOLS_DIR`，未设置任何 `LYRAFORGE_*_PYTHON`）**：
   - `lyraforge tools status` → 三个工具均 `已安装`、`source=managed`；
   - `--engine basic-pitch` → `raw_note_count = 8`，`duration_ms = 3986`；
   - `--engine dettato` → `raw_note_count = 7`，`duration_ms = 3943`；
   - WAV→MP3 后 `--engine builtin-mono` → `raw_note_count = 8`（使用托管 FFmpeg 解码）。
4. **自动化门禁**：
   - `uv run pytest --cov=lyraforge --cov-fail-under=80` → **163 passed, 2 warnings in 35.55s**，总覆盖率 **85.07%**（新增 `test_toolchain.py` 10 例与 API 后台安装用例）；
   - `uv run ruff check .` → `All checks passed!`；
   - 前端 `vitest run` → **4 文件 / 6 用例全过**；`vue-tsc --noEmit && vite build` → 成功（`161.06 kB` JS / `20.52 kB` CSS）。
5. **安全与供应链边界**：只允许 `pypi.org` / `files.pythonhosted.org` 的 HTTPS 下载；使用 PyPI 元数据中的 SHA-256 校验；下载体积上限（uv 80 MB、FFmpeg 120 MB、其他 200 MB）；`shell=False` 固定 argv；失败即删除临时文件；不写注册表、不写用户环境变量。
6. **未覆盖（如实标注）**：
   - 桌面 UI 的按钮点击流程仅由组件测试与构建覆盖，未做人工可视化点击验收；
   - macOS/Linux 的托管安装路径未在对应实机执行（当前仅 Windows 实测）；
   - 断网/代理失败的用户提示仅由单元测试覆盖，未做真实网络故障演练。
7. **合入记录**：[PR #12](https://github.com/PariyaProject/LyraForge/pull/12) → `7d6fc48`；合并后 main CI [Run #45144673073](https://github.com/PariyaProject/LyraForge/actions/runs/45144673073) 全绿（含 `windows-latest` 打包与 `--self-check --check-gui` 门禁）。

---

## 13. 产品定位收敛、21 键预设与老旧的诗琴（2026-11-23）

1. **AI / Agent 降级为可选项**：
   - README 删除「三层 AI / MCP 集成」主推段落，改为一条「可选的高级集成（默认不需要）」；截图标题「AI 转谱」改为「音频转谱」。
   - 侧边栏：`AI 转谱` → `音频转谱`，`设置与模型` → `设置`，品牌副标题改为 `MIDI / 音频 → 游戏乐器曲谱`。
   - 音频转谱页的 Agent 卡片、设置页的 MCP 卡片均移入 `高级（可选）` 的折叠区，默认流程为转谱 → 预设 → 编曲 → 试听 → 导出。
2. **一键编曲预设**：
   - `src/lyraforge/presets.py` 定义 3 件乐器 × 5 套预设（主旋律优先 / 均衡 / 丰满 / 慢速练习 / 轻快），每套都经过 `ArrangeOptions.validate()`；
   - 新 API `GET /v1/presets`（可选 `profile_id` 过滤）与 CLI `lyraforge presets list --profile`；
   - 编曲工作室顶部新增预设按钮，点击后写入 style / 移调 / 琶音 / 速度，再点「生成编曲」。
3. **老旧的诗琴 Profile**：
   - 新增 `src/lyraforge/instruments/data/genshin.vintage_lyre.v1.json`，21 键：低/中行 C Dorian（48,50,51,53,55,57,58 / 60,62,63,65,67,69,70），高行 C Phrygian（72,73,75,77,79,80,82）；
   - 数据来源：Genshin Impact Wiki（Fandom）Vintage Lyre 条目；`calibration.status` 保持 `unverified`，需真机逐键核对后才能升级。
4. **自动化验证**：
   - `uv run pytest --cov=lyraforge --cov-fail-under=80` → **169 passed, 2 warnings in 34.88s**，总覆盖率 **85.11%**（新增 `test_presets.py`：预设数量/唯一性/参数校验、Vintage Lyre 音高映射与编曲、`/v1/presets` API）；
   - `uv run ruff check .` → `All checks passed!`；
   - 前端 `vitest run` → **4 文件 / 6 用例全过**；`vue-tsc --noEmit && vite build` → 成功（`162.36 kB` JS / `20.52 kB` CSS）。
5. **未覆盖（如实标注）**：
   - 风物之诗琴、镜花之琴、老旧的诗琴的键位与绝对八度命名仍未在游戏内逐键校准（全部 `unverified`）；
   - 鼓（Festive Drum / Djem Djem Drum）、尤克里里、夜风号角、Leaping Spirit Piano、Harmonic Keys 等**不同输入模型**的乐器未纳入；其中鼓/尤克里里需要新的和弦/节奏映射引擎。
6. **合入记录**：[PR #13](https://github.com/PariyaProject/LyraForge/pull/13) → dc22b0；合并后 main CI [Run #45154608748](https://github.com/PariyaProject/LyraForge/actions/runs/45154608748) 全绿。

---

## 14. Windows 真机演奏 P1：焦点交接、进程识别与提权（2026-11-23）

1. **根因**：旧流程在用户点击「确认授权开始」的瞬间启动播放线程，`Player` 在发送每个按键前检查前台窗口；此时前台是 LyraForge 自己，因此必然 `focus_lost`。且检测仅匹配窗口标题，国服/全屏/本地化标题易误判。
2. **实现**：
   - `playback/windows/game_window.py`：公开 Win32 API 读取前台窗口的 PID、进程名、标题与 TokenElevation，不读游戏内存、不装钩子；
   - `ForegroundWindowGuard` 优先匹配进程名 `GenshinImpact.exe` / `YuanShen.exe`，标题仅作回退；
   - `PlaybackManager.start()` 增加 `wait_for_focus_s`（默认 10s）：先进入 `waiting_focus`，检测到游戏前台后再发送按键；超时返回 `focus_timeout` 并附带当前前台进程/标题；
   - UIPI 检测：目标高权限而本进程低权限时进入 `permission_required`，`POST /v1/app/relaunch-elevated` 触发 UAC 重启（`ShellExecuteW("runas")`）；
   - 前端展示等待焦点/权限错误状态与「以管理员身份重启」按钮。
3. **自动化验证**：
   - `uv run pytest --cov=lyraforge --cov-fail-under=80` → **177 passed, 2 warnings in 33.62s**，总覆盖率 **84.40%**（新增 `test_game_window.py`、`test_elevation.py`）；
   - `uv run ruff check .` → `All checks passed!`；
   - 前端 `vitest run` → **4 文件 / 6 用例全过**；`vue-tsc --noEmit && vite build` → 成功（`164.30 kB` JS / `20.52 kB` CSS）。
4. **未覆盖（如实标注）**：
   - 本会话无《原神》游戏环境，**未进行真实游戏内演奏验证**；管理员/非管理员、国服/国际服、独占全屏/无边框需用户在实机确认；
   - 全局热键（P2）与播放队列/上一首/下一首（P3）尚未实现。

---

## 15. Windows 全局热键 P2（2026-11-23）

1. **实现**：
   - `src/lyraforge/hotkeys.py`：文本热键解析（至少一个修饰键，支持 F1–F24 / A–Z / 0–9 / 方向键等）、`RegisterHotKey` 消息循环线程、逐动作冲突提示；默认不绑定；
   - `GET/POST /v1/hotkeys` 与设置页录入/保存；保存到 `windows_hotkeys` 设置并在应用启动时重新注册；
   - 热键动作：开始（启动已准备的编排）、暂停、继续、停止；开始沿用 `waiting_focus` 与权限检查；
   - 新增 `windows_allowed_processes` 设置项（默认 `GenshinImpact.exe, YuanShen.exe`），与标题白名单共同决定目标窗口。
2. **验证**：
   - `pytest` → **180 passed, 2 warnings in 35.04s**，覆盖率 **83.82%**；`ruff` 通过；
   - 前端 `vitest` → 6/6；`vue-tsc + vite build` → 167.30 kB JS / 20.52 kB CSS。
3. **未覆盖（如实标注）**：
   - 本会话无法在真实游戏中验证 `RegisterHotKey` 是否被独占全屏或反作弊拦截；需要用户实机确认；
   - 上一首/下一首仍待 P3 播放队列实现。




