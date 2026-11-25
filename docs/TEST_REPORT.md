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

---

## 16. 播放队列 P3（2026-11-23）

1. **实现**：
   - `api/queue_service.py`：有序队列 + 当前索引，`step(±1)` 环绕；
   - `/v1/playback/queue`（设置/读取）、`/add`、`/clear`、`/step`；`step` 会停止当前播放、重新 `prepare` 目标编曲，再走 `start_pending`（含 `waiting_focus` 与 UIPI 检查）；
   - 桌面：编曲工作室「加入播放队列」、播放页队列列表（当前项高亮）与上一首/下一首/清空按钮；
   - 全局热键 `next` / `previous` 调用同一 `/step` 逻辑。
2. **验证**：
   - `pytest` → **182 passed, 2 warnings in 31.93s**，覆盖率 **83.94%**（新增 `test_queue_api.py`：队列环绕、API 设置/切歌/追加/清空）；
   - `ruff` 通过；前端 `vitest` 6/6；`vue-tsc + vite build` → 169.89 kB JS / 20.52 kB CSS。
3. **未覆盖（如实标注）**：
   - 真实游戏内切歌、热键与管理员权限组合仍待用户实机验证；
   - 队列目前只支持手动加入与顺序/环绕切换，未实现随机播放或按曲库批量生成队列。

---

## 17. UI/UX 布局与版本管理修正（2026-11-23）

1. **修复的问题**：
   - 音频转谱页的「高级（可选）」详情被放在两列网格里，折叠后留下空白占位；现已移到网格外整宽显示；
   - 设置页外部工具卡片中的长版本串/路径会溢出边框；`code`、`pre` 与卡片文本统一 `overflow-wrap: anywhere`，`pre` 允许换行；
   - 左下角「离线可运行 · 零绑架 API Key」口号被移除，改为「版本 + GPL-3.0 · 关于与第三方许可」入口。
2. **播放队列重构**：从播放页内嵌卡片改为全局右侧抽屉（底部传输栏「队列 n」开关），支持编号、当前项高亮、点击选中、上一首/下一首/清空；`PlaybackView` 内的重复卡片已删除。
3. **编曲版本管理**：
   - 版本标题自动生成 `#序号 · 风格 · 移调 · 速度`，并展示可演奏率、音符数与创建时间；
   - 支持在曲库中就地重命名（新增 `POST /v1/arrangements/{id}/label` 与 `store.set_arrangement_label` 复用）；
   - 编曲工作室下拉、全局底栏也统一使用同一描述。
4. **验证**：
   - `pytest` → **182 passed, 2 warnings in 45.86s**，覆盖率 **83.96%**；`ruff` 通过；
   - 前端 `vitest` → 4 文件 / 6 用例全过；`vue-tsc + vite build` → 174.93 kB JS / 22.65 kB CSS。
5. **未覆盖（如实标注）**：
   - 未在真实窗口做人工视觉验收（无浏览器控制）；布局改动仅由组件测试与构建覆盖；
   - 抽屉/弹层的窄屏与高 DPI 表现需实机确认。

---

## 18. dettato GPU 支持与转录超时缩放（2026-11-23）

1. **GPU / NPU**：
   - dettato 适配器新增 `LYRAFORGE_DETTATO_DEVICE=cpu|cuda|mps` 覆盖；未指定时会用隔离解释器探测 `torch.cuda.is_available()` / `torch.backends.mps.is_available()`，自动传 `--device`；
   - 注意：PyPI 安装的 `torch` 默认是 CPU 版，要用 GPU 需在 dettato 环境改装 CUDA 版 wheel（见 [DEVELOPMENT.md](DEVELOPMENT.md) §3.2）；NPU 目前没有通用 `--device` 后端，dettato CLI 只声明 cuda/cpu。
2. **超时**：转录子进程预算按音频时长缩放（dettato 10×实时 + 180s、Basic Pitch 3× + 60s，且不低于 `TranscribeOptions.timeout_s`），修复长曲目固定 300s 超时。
3. **UI 清理**：引擎卡片移除 `ADR-0001` 等开发术语，改为用户可读的能力/运行方式描述。
4. **验证**：
   - `pytest` → **184 passed, 2 warnings in 35.83s**，覆盖率 **83.86%**；`ruff` 通过；
   - 新增测试覆盖设备覆盖优先级、CLI runner 回退 cpu、超时缩放上限；
   - 前端 `vitest` 6/6、`vue-tsc + vite build` 通过（174.93 kB JS / 22.65 kB CSS）。
5. **未覆盖（如实标注）**：
   - 本会话没有 NVIDIA GPU / 游戏环境，未实测 CUDA 推理吞吐；仅验证参数与探测逻辑；
   - NPU 加速未实现。

---

## 19. 媒体格式扩展：.m4s 与常见音视频容器（2026-11-23）

1. **支持列表**：`SUPPORTED_MEDIA_EXTENSIONS` 新增 `.m4s`（DASH/分片 MP4 分段），并扩展 `.aac`/`.wma`/`.aiff`/`.aif`/`.oga`/`.opus`/`.m4b` 与 `.mov`/`.avi`/`.flv`/`.wmv`/`.ts`/`.m2ts`/`.mts`/`.3gp`/`.mpg`/`.mpeg`/`.vob`/`.ogv`；桌面导入选择器同步更新。
2. **解码**：所有非 WAV 格式仍交给本机 FFmpeg（`-i` 解码为单声道 16-bit WAV）；加密/DRM 文件、缺少音轨的文件会得到明确的 `MEDIA_DECODE_FAILED` / `MEDIA_UNSUPPORTED` 错误。
3. **验证**：
   - 参数化测试对 32 个受支持扩展逐一验证会被路由到 FFmpeg 提取路径；
   - `pytest` → **212 passed, 2 warnings in 35.91s**，覆盖率 **83.83%**；`ruff` 通过；
   - 前端 `vue-tsc + vite build` → 175.15 kB JS / 22.65 kB CSS。
4. **未覆盖（如实标注）**：
   - 未用真实 `.m4s`/视频文件逐格式验证解码结果（本机 FFmpeg 版本 9.0.2 可用，但本会话未提供样本）；
   - 加密（DRM）或需要 init segment 拼接的分片不保证可读。

---

## 20. dettato GPU 设置集成（2026-11-23）

1. **实现**：
   - `toolchain/gpu.py`：通过 `nvidia-smi` 检测 GPU/驱动，用隔离解释器探测 `torch.version.cuda` / `torch.cuda.is_available()`；读取/写入工具链清单中的 `dettato_device` 设置；
   - `toolchain/installer.py`：新增 `install_dettato_gpu()`（`uv pip install --index-url https://download.pytorch.org/whl/cu124 --upgrade torch`，安装后验证 CUDA 可用），并接入 `ToolInstallManager`（`dettato-gpu` 任务）；
   - `toolchain/runtime.py`：启动时把持久化的设备偏好注入 `LYRAFORGE_DETTATO_DEVICE`；
   - API：`GET /v1/gpu`、`POST /v1/gpu/device`、`POST /v1/gpu/install`；设置页新增 GPU 卡片（检测结果、设备下拉、一键安装与进度）。
2. **验证**：
   - `pytest` → **217 passed, 2 warnings in 35.41s**，覆盖率 **83.67%**；`ruff` 通过；
   - 新增 `test_gpu_tools.py`：nvidia-smi 解析、torch 探测、设备持久化/环境注入、GPU API；
   - 前端 `vitest` 6/6；`vue-tsc + vite build` → 178.78 kB JS / 22.65 kB CSS。
3. **未覆盖（如实标注）**：
   - 本会话没有 NVIDIA GPU，未实际执行 2.5 GB CUDA PyTorch 安装，也未测量推理吞吐；
   - NPU 仍不支持（dettato CLI 仅声明 cuda/cpu 后端）。

---

## 21. GPU 安装“成功但仍是 CPU”修复（2026-11-23）

1. **现象**：设置页检测到 RTX 2070 SUPER / 驱动 617.42，PyTorch 为 `2.15.0+cpu`；点安装后 90% 处报 `[SOURCE_UNAVAILABLE] CUDA 版 PyTorch 已安装，但 torch.cuda.is_available() 仍为 False`。
2. **根因**：PyPI 的 CPU wheel 版本高于当前 CUDA 索引里可用的最新版（`2.15.0+cpu` vs `2.14.1+cu130`）。`uv pip install --upgrade torch` 判定“已是最新”，实际没有替换，探测仍为 CPU。
3. **修复**：默认索引改为 `cu130`，安装命令改为 `uv pip install --index-url <cuXXX> --reinstall-package torch torch`；这会只重装 torch 并允许降级（dettato 仅要求 `torch>=2.2`）。索引仍可由 `LYRAFORGE_PYTORCH_CUDA_INDEX` 覆盖；失败提示建议换 cu128/cu126/cu124。
4. **真机验证**：
   - 安装 `torch-2.14.1+cu130`（下载 1.9 GiB，Prepared 40.22s）；
   - `torch.__version__ = 2.14.1+cu130`、`torch.version.cuda = 13.0`、`torch.cuda.is_available() = True`、`torch.cuda.get_device_name(0) = NVIDIA GeForce RTX 2070 SUPER`；
   - `pytest` → **218 passed, 2 warnings in 35.79s**，覆盖率 **83.83%**。
5. **未覆盖（如实标注）**：
   - 未跑完整 dettato 转录 benchmark（只验证 CUDA 可用与设备名）；
   - NPU 仍不支持。

---

## 22. 转谱上下文与“切歌后一直不完成”（2026-11-23）

1. **现象**：提交 dettato CUDA 转谱后切到另一首歌播放，转谱页的歌曲选择跟着变，任务看起来一直不完成。
2. **根因**：
   - 转谱页的曲目选择直接绑定了全局 `selectedSongId`，播放/曲库切歌会同时改变它；
   - 任务完成回调刷新的是“当前选中歌曲”，不是任务自己的 `song_id`，所以结果看起来挂到了错误的歌上；
   - dettato GPU 本身较慢：15 秒片段首次运行（含加载模型）耗时 **69 秒**，3–4 分钟歌曲可能需要数分钟到十几分钟；后端进度只有 30%（子进程运行中）没有细粒度更新，容易误判为卡死。
3. **修复**：
   - 新增独立的转谱目标 `transcribeSongId` / `transcribeSources` / `transcribeTranscriptions`，播放切歌不再影响；
   - `handleStartTranscribe` 使用转谱目标；完成/取消/失败后按 `job.song_id` 刷新，不再刷新当前播放歌曲；
   - 任务面板显示任务曲目名、阶段（排队/提取音频/识别中/完成）、已运行秒数，并提示切歌不会中断；
   - 轮询从 150ms 放宽到 400ms，减少无意义请求。
4. **验证**：
   - `pytest` → **218 passed, 2 warnings in 35.03s**，覆盖率 **83.82%**；
   - 前端 `vitest` 6/6；`vue-tsc + vite build` → 180.26 kB JS / 22.65 kB CSS。
5. **未覆盖（如实标注）**：
   - 未用完整 3:45 歌曲跑完 GPU 转谱计时（只跑了 15 秒片段）；
   - 任务进度仍只有粗粒度阶段，暂无按音频比例的 ETA。

---

## 23. Round 21 产品级 UI/UX 全面重设计与跨分辨率验收（2026-11-24）

1. **设计系统与约束落地**：
   - 新增 [DESIGN.md](../DESIGN.md)（Studio Obsidian + Warm Amber Safelight，OKLCH 令牌层级、4px 间距阶梯、三字重 `400/500/600`、平直细线分割容器规范与 Windows 10/11 WebView2 / DPI / IME 安全基线），并在 [AGENTS.md](../AGENTS.md) § 2 固化前端 UI 维护门禁。
   - 重构 6 个核心工作区（`HomeView`、`LibraryView`、`TranscribeView`、`StudioView`、`PlaybackView`、`SettingsView`）与全局覆盖层（`App.vue` 左侧导航与底部固定试听传输栏、`QueueDrawer`、`AboutDialog` 原生 `<dialog>`、`ToastStack`、`PianoRollEditor`、`LyreKeyboard`）。
   - 新增 `apps/desktop/web/src/__tests__/StudioOverlays.spec.ts`（4 项 overlay / dialog / store 预览播放头同步单测）。
2. **Hallmark 设计审计（`sloplint` 前后对比）**：
   - 基线（`before`）：`59 FAIL, 45 REFLEX, 17 WARN`。
   - 终版重设计（`sloplint --kept`）：**`0 FAIL, 0 REFLEX, 13 WARN`**（`EXIT=0`，`links 1/1`、`fields 19/19`、`handlers 93/94` 且仅 1 项音符点击与拖拽统一处理器已登记）。
3. **实时 FastAPI + Chrome 跨分辨率、High-DPI 与全流程 E2E 实测**：
   - 覆盖 `1440×900`（6 视图 + 队列抽屉 + 关于弹窗）、`1280×720`（首页 / 编曲工作室 / 演奏控制台）、`1366×768`（本地曲库）、`1920×1080`（编曲工作室）与 `1440×900@2x` 共 **14 次视口采样**：全部 `horizontalOverflowPx == 0`、`hasFooterTransport == true`、`consoleErrors == []`、`pageErrors == []`。
   - 编曲工作室首屏焦点提升：`1440×900` 下 Piano Roll 从改版前的 `top = 593`（`mainScrollH = 1577 > 802`）提升至 `top = 133`（`mainScrollH = 804 == mainClientH`，占视口 `51.20%`）；`1920×1080` 下占视口 `63.49%`（`1408×935`）。
   - **10 / 10 项端到端真实交互全过**（本地 MIDI 导入、曲库搜索+打开+版本重命名、内置单音音频转谱完整生命周期、编曲预设+A/B 对比、Piano Roll 拖拽/微调/右键菜单、撤销/重做、跨视图离线试听 Blob 连续播放、Piano Roll 保存新版本、设置保存+4 端 MCP 切换、DryRun 两段确认+暂停/继续/急停）。
4. **本地全量验证（最终编辑后重新执行 `make check`）**：
   - `uv run ruff check .` → `All checks passed!`
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **218 passed, 2 warnings in 43.67s**，总覆盖率 **84.36%**。
   - `pnpm --dir apps/desktop/web test` → **Test Files 5 passed (5), Tests 10 passed (10)**。
   - `pnpm --dir apps/desktop/web build` → `dist/index.html 1.07 kB`、`CSS 50.91 kB`、`JS 204.36 kB`（`926ms`）。
   - `make smoke` & `desktop --self-check` → 退出码 `0`（DryRun 48 动作，`keys_still_pressed = []`）。
5. **环境边界（如实标注）**：
   - 上述跨分辨率与 E2E 验证运行于 macOS Headless Google Chrome + 真实本地 FastAPI 服务（`DryRun` 模拟模式）；Windows 10/11 PyWebView2 真实窗口渲染与 125%/150% DPI、以及《原神》真机 21 键校准与 `SendInput` 演奏仍未在 Windows 实体游戏机完成实测。
   - 外置工具（`ffmpeg` / `basic-pitch` / `dettato`）当前测试机未安装，转谱 E2E 验证基于内置 `builtin-mono` (YIN) 完成。

---

## 24. Round 22 极简应用图标与 Windows + macOS 双平台打包（2026-11-24）

1. **图标资产与校验**：
   - 由 SVG 矢量母版（`packaging/icons/lyraforge.svg`、`lyraforge-win.svg`、`docs/assets/lyraforge-icon.svg`）经 `scripts/generate_icons.py` 生成：
     - `packaging/icons/lyraforge.png`（`512×512` RGBA，15,460 B）；
     - `packaging/icons/lyraforge.ico`（7 层 PNG-in-ICO：`16, 24, 32, 48, 64, 128, 256` RGBA，18,172 B）；
     - `packaging/icons/lyraforge.icns`（Apple IconImage `icns`，经 `iconutil -c iconset` 逆向解包验证含完整 10 个标准+Retina 槽位，147,073 B）。
2. **macOS Apple Silicon 原生打包实测**：
   - 执行 `bash scripts/build_macos.sh`：Vue 3 前端构建 + PyInstaller `BUNDLE` 生成 `dist/LyraForge.app`（`Contents/Resources/lyraforge.icns` + `CFBundleIconFile` 正确嵌入）；
   - 执行 `dist/LyraForge.app/Contents/MacOS/LyraForge --self-check --check-gui`：退出码 `0`，输出 `gui_host: {"available": true, "backend": "cocoa", "backend_ok": true, "version": "6.2.1"}`；
   - 执行 `scripts/release_helper.py package --platform macos --arch macos-arm64` 生成 `17,845,938` bytes 压缩包，`unzip -q` 解压后确认 `.app` 内部符号链接完整（如 `Contents/Resources/AppKit -> ../Frameworks/AppKit`），且解压出的可执行文件二次 `--self-check --check-gui` 返回 `ok: true`。
3. **本地全量门禁（最终编辑后实测）**：
   - `uv run ruff check .` 通过；`uv run pytest` **222 passed, 2 warnings**（含 macOS `cocoa` 门禁、图标头部检验、`.app` ZIP 符号链接/防逃逸与双平台合流发布用例），总覆盖率 **84.12%**；`vitest` **5/5 文件 10/10 通过**；`vue-tsc + vite build` 通过；`make smoke` 退出码 `0`。
4. **跨平台运行时边界（如实标注）**：
   - Windows `.exe` 图标资源与 WinForms `Form.Icon` 注入逻辑将随本轮 GitHub Actions `windows-latest` CI 构建验证打包，真实 Windows 11 资源管理器与任务栏视觉渲染待实体 Windows 机器打开 `.exe` 后直观确认。

---

## 25. Round 23 统一选曲与分曲目多任务转谱状态（2026-11-24）

1. **修复范围与核心改动**：
   - `apps/desktop/web/src/composables/useLyraStore.ts` + `src/api.ts`：
     - 消除 `selectedSongId` 与 `transcribeSongId` 双套选曲状态分叉，并增加单调序号并发竞态保护与队列切歌反同步（`selectArrangement` 同步所属歌曲）；
     - 新增 `allSongs` 维护未筛选全量曲目表，曲库搜索/标签筛选时不影响全局切换；
     - 用多任务列表 `transcriptionJobs` + `GET /v1/jobs` 初始化恢复替代单一全局 `activeJob`，`ensureJobPolling` 并发轮询多个活动任务并在后台完成时通过提示与快捷入口通知，不劫持当前选中曲目。
   - `apps/desktop/web/src/App.vue` + `styles/global.css` + `views/TranscribeView.vue` + `views/StudioView.vue`：
     - 顶部上下文栏新增全视图一致的曲目选择器（`#topbar-song-select`）与后台转谱任务跳转胶囊；
     - `TranscribeView` 流程步骤条与状态区严格绑定当前选中曲目，并增加「其他曲目的转谱任务」区块（支持 `去编曲` 直达、`切换查看` 与按任务 `job.id` 取消）；
     - `StudioView` 空状态区分未选曲 / 未完成转谱（直接跳转「前往音频转谱」）/ 已转谱待编排。
2. **本地全量验证（`make check`）**：
   - `uv run ruff check .` → `All checks passed!`
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **222 passed, 2 warnings in 43.58s**，总覆盖率 **84.09%**。
   - `pnpm --dir apps/desktop/web test` → **Test Files 5 passed (5), Tests 11 passed (11)**（含新增 `App.spec.ts` 多曲目并发转谱切换、未转谱进工作室引导、后台完成不劫持当前曲目及「去编曲」跳转、曲库筛选下顶部切歌全链路回归用例）。
   - `pnpm --dir apps/desktop/web build`（`vue-tsc --noEmit && vite build`） → `dist/index.html 1.34 kB`、`CSS 51.62 kB`、`JS 211.49 kB`（`896ms`）。
   - `make smoke` → 退出码 `0`（DryRun 48 动作，`keys_still_pressed = []`）。
3. **GitHub PR 与合并后 CI**：
   - [PR #24](https://github.com/PariyaProject/LyraForge/pull/24)（`8f6619b`）→ PR CI [Run #45313980464](https://github.com/PariyaProject/LyraForge/actions/runs/45313980464) 全绿；
   - Squash 合入 `main`（`f671c8c`）→ 合并后 CI [Run #45314387622](https://github.com/PariyaProject/LyraForge/actions/runs/45314387622) 全部 5 作业 `success`。
4. **环境边界（如实标注）**：
   - 本机 `PATH` 未安装 `sloplint` CLI，前端按 [DESIGN.md](../DESIGN.md) token、无嵌套卡片与无冲突 CTA 规则人工核对通过；真实桌面交互视觉未在本轮额外做无头 Chrome 截屏或 Windows GUI 实机点击复核，已由 `vitest` jsdom 全流程单测与双端 PyInstaller `--self-check --check-gui` 门禁验证。

## 26. Round 24：Windows 默认管理员提权与隐藏子进程 CMD 窗口验证记录

1. **核心改动核查**：
   - 默认管理员提权：
     - 打包二进制：[packaging/lyraforge.spec](../packaging/lyraforge.spec) 为 `EXE(...)` 启用 `uac_admin=IS_WINDOWS` 并保持 `console=False`；
     - 源码启动：[src/lyraforge/elevation.py](../src/lyraforge/elevation.py) 新增 `NO_ELEVATE_ENV = "LYRAFORGE_NO_ELEVATE"`、`is_current_process_elevated()`、`_source_gui_python()`（优先使用 `pythonw.exe`）、`maybe_elevate_for_desktop()`，[src/lyraforge/cli.py](../src/lyraforge/cli.py) 为 `desktop` 子命令新增 `--no-elevate` 开关，并在常规 GUI 启动时默认申请管理员提权，若用户在源码模式下取消 UAC 则回退至非提权 GUI，同时保持 `--self-check`、`--check-gui` 与 `mcp` 非提权不阻塞。
   - 隐藏子进程 CMD 窗口：
     - [src/lyraforge/media/subprocess_utils.py](../src/lyraforge/media/subprocess_utils.py) 新增纯标准库 `hidden_subprocess_kwargs()`（在 `sys.platform == "win32"` 下注入 `CREATE_NO_WINDOW`、`STARTUPINFO(STARTF_USESHOWWINDOW, SW_HIDE)`），并将其接入 `_popen_isolation_kwargs()`、`_kill_windows_descendants()`（`powershell`）与 `_terminate_process_tree()`（`taskkill`）；
     - [src/lyraforge/toolchain/gpu.py](../src/lyraforge/toolchain/gpu.py)（`detect_nvidia()`、`probe_dettato_torch()`）、[src/lyraforge/toolchain/installer.py](../src/lyraforge/toolchain/installer.py)（`_run()`）与 [src/lyraforge/transcribers/dettato.py](../src/lyraforge/transcribers/dettato.py)（`resolve_device()`）统一补充 `stdin=subprocess.DEVNULL` 与 `**hidden_subprocess_kwargs()`。
2. **本地自动化校验（`aa3516d`）**：
   - `make check` 全项通过：
     - `uv run ruff check .`：`All checks passed!`
     - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80`：`229 passed, 2 warnings`（Total coverage `84.59%`，含新增 `tests/unit/test_windows_console_hiding.py` 与更新后的 `test_elevation.py`、`test_desktop_startup.py`、`test_layering.py`）
     - `pnpm --dir apps/desktop/web test`：`Test Files 5 passed (5), Tests 11 passed (11)`
     - `pnpm --dir apps/desktop/web build`：`built in 944ms`
     - `make smoke`：退出码 `0`（`actions_sent: 48`、`keys_still_pressed: []`、`state: "completed"`）
3. **GitHub PR 与合并后 CI**：
   - [PR #25](https://github.com/PariyaProject/LyraForge/pull/25)（`aa3516d`）→ PR CI [Run #45319544386](https://github.com/PariyaProject/LyraForge/actions/runs/45319544386) 4 项活动作业全部 `success`（`Publish Desktop Releases` 按 PR 条件跳过）；
   - Squash 合入 `main`（`ed0dd13f`）→ 合并后 CI [Run #45320114882](https://github.com/PariyaProject/LyraForge/actions/runs/45320114882) 初次运行在 `Test (windows-latest, Python 3.11)` 上触发 `test_subprocess_derived_process_tree_timeout_cancel_orphan_pipes_and_stress` 计时上限波动（`10.281s < 10.0s`），重跑失败作业后全部 5 作业（含 `Build Windows/macOS Bundle (PyInstaller)` 与 `Publish Desktop Releases`）均为 `success`，已更新 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 产物。
4. **环境边界（如实标注）**：
   - 本机为 macOS，GitHub `windows-latest` Runner 处于非交互 `runneradmin` 会话，且仅以 `--self-check --check-gui` 验证打包启动门禁；真实 Windows 10/11 桌面双击 `LyraForge.exe` 触发 UAC 提示以及在 `ffmpeg` / `basic-pitch` / `dettato` / `uv` / `nvidia-smi` 执行期间全程无 CMD 黑框闪现，仍待用户在物理 Windows 设备上下载 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 实测确认。

## 27. Round 25：可扩展多流水线转谱与人声主旋律编曲增强验证记录

1. **架构与核心改动**：
   - **纯无头音乐核心（`src/lyraforge/music_core/`）**：
     - `cleanup.py`：为 `CleanupOptions` 新增 `merge_vibrato_gap_ms` 与 `min_velocity`（默认调参行为与统计键完全向后兼容），实现 `_merge_vocal_vibrato()` 与多轨合并函数 `merge_stem_scores()`（保留多音轨元信息并分配独立非打击乐通道）；
     - `arranger.py`：引入 `ArrangerStrategyInfo` 与 `classic` / `vocal_lead` 策略注册表；保留 `classic` 路径完全一致，新增 `vocal_lead` 策略：`_search_transpose_vocal_lead()`（多轨密度归一化约 75% 主旋律权重寻优 + 非对称乐器音域折返计分）、`_map_notes_vocal_lead()`（主旋律天花板压低 + 半音冲突避免与越顶强制折让）与 `_select_vocal_lead_clusters()`（按 `Style.MELODY`/`BALANCED`/`RICH` 差异化人声避让、大于 600ms/300ms 间奏自动放行伴奏、半音冲突单独记为 `DropReason.SEMITONE_DROPPED`，以及单轨轮廓连续性主旋律追踪）；增强人声轨名识别权重（`0.45`）；
     - `performance.py` & `__init__.py`：`transform_json()` 对 `classic` 默认参数保持原 JSON 指纹（UUIDv5 `arrangement_id` 向后一致），对 `vocal_lead` 或手动 `melody_track` 显式附加区分字段。
   - **按需隔离源分离与可扩展流水线（`separators/`、`pipelines/`、`toolchain/`）**：
     - `toolchain/{specs,runtime,gpu,installer}.py`：新增 `demucs` (`4.0.1` + `soundfile`, MIT) 隔离工具定义、NVIDIA CUDA PyTorch 共享安装逻辑与 `LYRAFORGE_DEMUCS_DEVICE` 设备管理；不进入 PyInstaller 打包 ZIP；
     - `separators/{base,demucs,registry}.py`：`DemucsSeparator` 使用隐藏窗口子进程策略调用隔离 `demucs` 拆出 `vocals` / `drums` / `bass` / `other`，自动剔除 `drums` 并合流 `bass+other` 为去鼓伴奏 `no_drums.wav`；
     - `transcribers/{base,basic_pitch}.py` + `pipelines/{base,builtin,registry}.py`：扩展 Basic Pitch 可选人声频带/阈值参数，注册 `direct`、`vocal_split_full`（`Vocal Lead` + `Accompaniment` 双角色多轨 MIDI）、`vocal_split_lead` 与 `vocal_split_accomp` 四条独立可切换流水线。
   - **存储 Schema v4、API、CLI 与桌面对比界面**：
     - `library/schema.py` & `store.py`：Schema v4 幂等迁移增加 `transcriptions.{pipeline_id, tracks_json}` 与 `arrangements.{transcription_id, arranger_strategy}`；`transcribe_song` 按最终序列化 MIDI 同步分轨索引（SMF Type 1 中曲目轨从 `1` 起算），支持 `get_song_tracks()` 与按 `transcription_id` 指定编曲/编辑传承；
     - `api/{app,job_service,tool_service}.py` & `cli.py`：新增 `GET /v1/pipelines`、`/v1/separators`、`/v1/arrangers`、`GET /v1/library/songs/{song_id}/tracks` 与 `POST /v1/gpu/install/demucs`，扩展 CLI `--pipeline` / `--vocal-engine` / `--accomp-engine` / `--arranger-strategy` / `--melody-track` / `--transcription-id`；
     - `apps/desktop/web/src/{api.ts,composables/useLyraStore.ts,views/{Transcribe,Studio,Settings}View.vue}`：遵循 `DESIGN.md` 增加转谱流水线与分声部引擎选择器、同曲多转录结果「以此编曲」跳转、编曲工作室转录版本选择器/编曲策略切换/MIDI 分轨复选框与手动「设为主旋律」覆盖，以及设置页 Demucs CUDA 安装开关。
2. **本地全量验证（合并前提交 `04260c1`）**：
   - `pnpm --dir apps/desktop/web install --frozen-lockfile && make check`：
     - `uv run ruff check .` → `All checks passed!`
     - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **241 passed, 2 warnings in 44.51s**，总覆盖率 **84.11%**（覆盖新增 `tests/unit/test_vocal_arranger.py` 6 例、`tests/unit/test_pipelines_and_separators.py` 4 例、分层纯净门禁 `tests/unit/test_layering.py` 10 例、GPU/工具链 `tests/unit/test_gpu_tools.py` 8 例与集成 `tests/integration/test_api.py`）。
     - `pnpm --dir apps/desktop/web test` → **Test Files 5 passed (5), Tests 12 passed (12)**（含新增 `App.spec.ts` `vocal_split_full` 提交、状态轮询、「以此编曲」跳转、工作室版本与 `vocal_lead` 联动、分轨复选框与主旋律覆盖端到端 mock 用例）。
     - `pnpm --dir apps/desktop/web build`（`vue-tsc --noEmit && vite build`） → `47 modules transformed`，`built in 917ms`。
     - `make smoke` → 退出码 `0`（`OK: 24 events, profile genshin.windsong_lyre.v1 (hash verified)`, `actions_sent: 48`, `state: "completed"`）。
   - `uv run python scripts/eval_transcribers.py`：`builtin-mono` 与 `pipeline_roundtrip`（`ok: true`, `transcribed_notes: 8`, `arranged_events: 8`）通过（本机 macOS 沙盒未预装 `basic-pitch`/`dettato`）。
3. **GitHub PR 与合并后 CI**：
   - [PR #26](https://github.com/PariyaProject/LyraForge/pull/26)（`04260c154b1a7f09b40fd4335210a04cfc2eb325`）→ PR CI [Run #45340849334](https://github.com/PariyaProject/LyraForge/actions/runs/45340849334) 全部 4 项活动作业 `success`（`Publish Desktop Releases` 按 PR 条件跳过）；
   - Squash 合入 `main`（`17f95f49a579a2e43cde77fbd00ffa6171bb71a9`）→ 合并后 CI [Run #45341468839](https://github.com/PariyaProject/LyraForge/actions/runs/45341468839) 全部 5 作业（`Test (macos-latest)`、`Test (windows-latest)`、`Build Windows Bundle`、`Build macOS Bundle`、`Publish Desktop Releases`）均为 `success`，已更新双平台 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 构建。
4. **环境边界（如实标注）**：
   - `DemucsSeparator`、`VocalSplitPipeline` 与前端对比流程均在隔离 mock / 合成测试夹具上完成回归验证；由于 CI 与本机 macOS 沙盒未联网安装 `demucs`/`basic-pitch`/`dettato` 及 NVIDIA GPU 驱动，实际在物理 Windows 10/11 环境下首次安装 `demucs` + 下载 `htdemucs` 权重、CUDA GPU 推理速度与多首真实带人声流行歌在游戏琴键上的主观听感对比，仍待用户在新版 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 上实测对比确认。
   - 本机 `PATH` 未安装 Hallmark `sloplint` CLI，前端按 `DESIGN.md` token（无字面量色值、无嵌套卡片）通过 grep 与人工检查确认。

---

## 28. Round 26：人声转谱质量、可选 SwiftF0 引擎与音乐编曲专项优化验证记录

1. **核心改动核查**：
   - **禁止伴奏静默降级与全链路溯源**：[src/lyraforge/pipelines/builtin.py](../src/lyraforge/pipelines/builtin.py) 将 `_pick_accomp_engine()` 从静默回退 `builtin-mono` 改为无多音引擎时返回 `None`，`PipelineInfo.available` 真实反映缺失引擎并在任务前暴露推荐引擎与降级/含鼓 warnings；修复 `VocalSplitPipeline.run()` `engine_id` 优先级导致忽略自动选择 `swift-f0` 的真实缺陷；保留用户主动选配低资源 `builtin-mono` 能力（标记 `degraded_mode: true`），完整记录实际引擎、`engine_version`（子进程版本探测缓存）、参数与警告至 SQLite `options_json` 及 API/CLI/MCP/桌面端；
   - **人声音符清理顺序与预设**：[src/lyraforge/music_core/cleanup.py](../src/lyraforge/music_core/cleanup.py) 新增 `VOCAL_CLEANUP_PRESETS`（`off` / `light` / `standard` / `strong`），重排 `_clean_vocal_score()` 先做谐波幽灵剔除（`+12/+19/+24`）、孤立八度错误修复、重叠/序列颤音合并、单调/低响度滑音吸收与微断音粘连（保护零间隙清晰连续同音重击及快速装饰音/半音经过音不被误并），再做 `min_note_ms` 过滤；
   - **宽人声音域、真实参数透传与跨设备修复**：新增 `VOCAL_RANGE_PRESETS`（`auto 73–1760 Hz` / `male 65–700 Hz` / `female 155–1760 Hz`），向 `BasicPitchSubprocessTranscriber` 真实转发 `--minimum-note-length`（实测验证 `basic_pitch.predict` 单位为毫秒）；`DemucsSeparator`（[src/lyraforge/separators/demucs.py](../src/lyraforge/separators/demucs.py)）改为原始 float32 `bass+other` 相加后统一 `0.98` 峰值限幅、记录 `drums_removed: bool` 诚实标签与 MPS→CPU 自动回退；`DettatoSubprocessTranscriber` 与 `toolchain/runtime.py` 自动避开 MPS float64 崩溃（macOS `dettato` 自动走 `cpu`，`demucs` 走 `mps`）；`format_log_tail()` 保留 `stdout` 尾行防错误信息被吞；
   - **可选 `swift-f0` 轻量人声引擎与 `vocal_lead` 编曲打磨**：经实机多模型评测后引入 MIT 许可 `swift-f0==0.3.0`（[src/lyraforge/transcribers/swift_f0.py](../src/lyraforge/transcribers/swift_f0.py)，`model.onnx` `0.13 MB`，仅限单音人声）；`vocal_lead`（[src/lyraforge/music_core/arranger.py](../src/lyraforge/music_core/arranger.py)）增强主旋律标签防抢夺、轮廓陡跳/低音舒适惩罚、低八度支撑、原生 `sus2` 保留 vs 小二度冲突屏蔽与人声尾音间奏交接；同步补齐 [src/lyraforge/mcp/tools.py](../src/lyraforge/mcp/tools.py) 参数与 [apps/desktop/web/src/](../apps/desktop/web/src/) 预检/预设展示。
2. **真音乐质量评测摘要**（完整四层对照数据与候选 F0 对照见 [MUSIC_QUALITY_EVAL.md](MUSIC_QUALITY_EVAL.md)）：
   - Vocal F0 选型对比（8 类干声与 Demucs 分离真声）：`swift-f0 0.3.0` 录得最高均值 `F1 = 0.8416`、`0.0000` 八度误差、平均 `RTF = 0.0063`，在真实 VocalSet (`CC-BY-4.0`) + 乐队混音中将 `vocal_split_lead` 人声 F1 从 `0.061`/`0.703` 提升至 `0.476`/`0.941`，端到端 `vocal_split_full` 编曲主旋律精确召回在 `cat9`/`cat10`/`cat7` 分别达 `0.5714`、`0.9412`、`1.0000`（`Cliffs = 0`）；
   - `cat8_vocal_artifacts` 修复清理执行顺序与 touching 同音保护后，4 次同音重击从错并至 `1` 次恢复为 `4/4` 完整保留（`basic-pitch` 清理 F1 `0.6207 → 0.7879`，`swift-f0 + light` `0.8571`）；
   - 纯真值 MIDI 编曲矩阵中 `cat4_jpop_anime` (`vocal_lead`) 移调优化为 `-7`、主旋律精确召回 `0.8824 → 0.9412`、八度断崖 `1 → 0`，`classic` 保持 100% 字节向后兼容。
3. **本地全量验证结果（最终提交前全套门禁，`43ee8a3`）**：
   - `uv run ruff check .` → `All checks passed!`
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **248 passed, 2 warnings in 47.13s**，总覆盖率 **83.81%**（覆盖新增 `test_transcribers.py`、`test_pipelines_and_separators.py`、`test_vocal_arranger.py`、`test_gpu_tools.py`、`test_toolchain.py`、`test_mcp_server.py` 与 `tests/integration/test_api.py`）。
   - `pnpm --dir apps/desktop/web test` → **Test Files 5 passed (5), Tests 13 passed (13)**；`pnpm --dir apps/desktop/web build` → `47 modules transformed`（`vue-tsc --noEmit && vite build` `1.07s`）。
   - `make smoke` → 退出码 `0`（DryRun `actions_sent = 48`、`keys_still_pressed = []`）。
   - `uv run python scripts/eval_transcribers.py` → 退出码 `0`（`pipeline_roundtrip.ok = true`、`preview_wav_bytes = 155276`，全部 4 引擎真实 `supported_options` 与 `polyphonic` 报告正确）。
4. **GitHub PR 与合并后 CI**：
   - [PR #27](https://github.com/PariyaProject/LyraForge/pull/27)（`43ee8a3`）→ PR CI [Run #45370192084](https://github.com/PariyaProject/LyraForge/actions/runs/45370192084) 全部 4 项活动作业 `success`（`Test (windows-latest)`、`Test (macos-latest)`、`Build Windows Bundle (PyInstaller)`、`Build macOS Bundle (PyInstaller)`）；
   - Squash 合入 `main`（`89857c6`）→ 合并后 CI [Run #45370816844](https://github.com/PariyaProject/LyraForge/actions/runs/45370816844) 全部 5 作业（含 `Publish Desktop Releases (Windows & macOS)`）均为 `success`，已更新双平台 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 产物（`LyraForge-dev-20261124-89857c6-windows-x64.zip`、`LyraForge-dev-20261124-89857c6-macos-arm64.zip`）。
5. **环境边界（如实标注）**：
   - macOS Apple Silicon 上真实端到端运行并对比 `ffmpeg 9.0`、`demucs 4.0.1`、`basic-pitch 0.4.0`、`dettato 2.0.0`、`swift-f0 0.3.0` 与 `builtin-mono`；物理 Windows 10/11 NVIDIA CUDA 上实测多轨分离/转录速度与真机《原神》游戏内实际敲键演奏未在本会话物理机复测，待用户在 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 上实机验证。

---

## 29. Round 27：Piano Roll 60s 截断与交互升级、分轨配色与保留、版本删除及 Demucs GPU 缓存修复

针对真实使用中的 6 项核心痛点（60s 后网格线消失、编曲后右侧音轨勾选重置与音符数差值不透明、无版本删除能力、Piano Roll 交互自由度不足、分轨音符视觉混淆、`dettato`/`Demucs` 独立虚拟环境与 GPU 缓存未失效）完成端到端修复与验证：

1. **后端与工具链修复**：
   - [src/lyraforge/library/store.py](../src/lyraforge/library/store.py)、[src/lyraforge/api/queue_service.py](../src/lyraforge/api/queue_service.py)、[src/lyraforge/api/app.py](../src/lyraforge/api/app.py)：新增 `DELETE /v1/arrangements/{arrangement_id}`（`LibraryStore.delete_arrangement()` 条带锁事务删除数据库记录与产物并清理 `parent_id`，`PlaybackQueueManager.remove_arrangement()` 同步裁剪播放队列）。
   - [src/lyraforge/separators/demucs.py](../src/lyraforge/separators/demucs.py)、[src/lyraforge/transcribers/dettato.py](../src/lyraforge/transcribers/dettato.py)、[src/lyraforge/toolchain/gpu.py](../src/lyraforge/toolchain/gpu.py)、[src/lyraforge/toolchain/installer.py](../src/lyraforge/toolchain/installer.py)：新增 `clear_device_cache()` 并在 `set_device()` / `install_dettato_gpu()` / `install_demucs_gpu()` / `install()` 后自动清空进程内 `_DEVICE_CACHE`，安装 CUDA 版 PyTorch 后无需重启即可立即生效。
2. **前端 Studio / Piano Roll / 曲库 / 设置修复**：
   - [apps/desktop/web/src/components/PianoRollEditor.vue](../apps/desktop/web/src/components/PianoRollEditor.vue)：移除 `Math.min(4800, ...)` 硬编码截断；实现 6 槽位 OKLCH 分轨配色（[tokens.css](../apps/desktop/web/src/styles/tokens.css)、[trackColors.ts](../apps/desktop/web/src/utils/trackColors.ts)）与可点击音轨聚焦图例；新增 Shift/Ctrl 多选、空白处框选（Marquee）、批量平移/移高/复制（`Ctrl+D`）/全选（`Ctrl+A`）/删除、Web Audio 琴键/音符试听及 `Space` 未保存草稿播放（[webAudioPreview.ts](../apps/desktop/web/src/utils/webAudioPreview.ts)）、`25%–250%` 缩放与「适应全曲」、`Ctrl+滚轮`/`Shift+滚轮`、随播跟踪、内联毫秒输入与「放弃修改」。
   - [apps/desktop/web/src/composables/useLyraStore.ts](../apps/desktop/web/src/composables/useLyraStore.ts)、[StudioView.vue](../apps/desktop/web/src/views/StudioView.vue)、[LibraryView.vue](../apps/desktop/web/src/views/LibraryView.vue)、[SettingsView.vue](../apps/desktop/web/src/views/SettingsView.vue)：修复 `handleArrange`/`handleArrangeAB`/`handleSaveEdited` 重置音轨与主旋律勾选的问题；展示每轨 `原始 → 编曲` 音符数量差值与淘汰原因明细；支持 Studio 与曲库二次确认删除编曲版本；Preset 一键切换自动重新编曲；设置页并排显示 `dettato` 与 `Demucs` 独立环境状态标签。
3. **本地全量验证（代码与测试定稿后）**：
   - `pnpm --dir apps/desktop/web install --frozen-lockfile && make check` 全部通过（覆盖提交分支前最终校验）；
   - `uv run ruff check .` → `All checks passed!`；
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **249 passed, 2 warnings in 46.46s**，总覆盖率 **83.76%**；
   - `pnpm --dir apps/desktop/web test` → **Test Files 5 passed (5), Tests 16 passed (16)**；
   - `pnpm --dir apps/desktop/web build` → `49 modules transformed`（`vue-tsc --noEmit && vite build` `982ms`）；
   - `make smoke` → 退出码 `0`（DryRun `actions_sent = 48`、`keys_still_pressed = []`）；
   - CSS 规范扫描：确认 `apps/desktop/web/src` 除 `tokens.css` 外零硬编码色彩字面量（`NO_LITERAL_COLORS`）。
4. **GitHub PR 与合并后 CI**：
   - [PR #28](https://github.com/PariyaProject/LyraForge/pull/28)（`71b3aba`）→ PR CI [Run #45383657674](https://github.com/PariyaProject/LyraForge/actions/runs/45383657674) 全部 4 项活动作业 `success`（`Test (windows-latest)`、`Test (macos-latest)`、`Build macOS Bundle (PyInstaller)`、`Build Windows Bundle (PyInstaller)`）；
   - Squash 合入 `main`（`be4f0da`）→ 合并后 CI [Run #45385270232](https://github.com/PariyaProject/LyraForge/actions/runs/45385270232) 全部 5 作业（含 `Publish Desktop Releases (Windows & macOS)`）均为 `success`，已发布双平台 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 产物（`LyraForge-dev-20261124-be4f0da-windows-x64.zip`、`LyraForge-dev-20261124-be4f0da-macos-arm64.zip`、`SHA256SUMS.txt`）。

---

## 30. Round 28：演奏时间轴精度、快速琶音/同键重触发修复、高精度调度与三层乐器校准基准

1. **核心修复与架构范围**：
   - **乐理/编曲时间轴与同键重触发**：[src/lyraforge/music_core/profile.py](../src/lyraforge/music_core/profile.py) 与 Schema 扩展可选 `timing` 字段（`min_key_release_gap_ms=20` 暂定默认值、`min_inter_key_interval_ms=0`、`trigger_mode="one_shot"`、`sustain_decay_ms=None`，保持内置 3 份乐器档案 JSON 原字节与规范 SHA-256 哈希不变）；[src/lyraforge/music_core/arranger.py](../src/lyraforge/music_core/arranger.py) 新增 `TimingMode`（`adapted` / `strict_fidelity`），将 `_cluster_end()` 改为仅对单轨 `<= 4 ms` 真同步音符建簇（保护 `>= 5 ms` 快速上下行琶音不被并入和弦反转），并在 Step 7/8 实现同键紧凑冲突的主旋律优先让位与释放间隙保持时间截断。
   - **高精度调度与 Win32 热路径**：[src/lyraforge/playback/player.py](../src/lyraforge/playback/player.py) 新增 `LateEventPolicy`（`shift_clock` / `drop_late` / `catch_up`）、确定性同键防重叠修复 `expand_events_with_stats()`、和弦同组批量下发、`active_seq_by_key` 防旧事件误杀、实时 `last_up_at` 间隙守护及 `P50/P95/P99/Max/late_events/retrigger_conflicts` 遥测；[src/lyraforge/playback/clock.py](../src/lyraforge/playback/clock.py) 分离粗眠与亚毫秒两级等待；[src/lyraforge/playback/windows/timer.py](../src/lyraforge/playback/windows/timer.py)、[win32_types.py](../src/lyraforge/playback/windows/win32_types.py)、[driver.py](../src/lyraforge/playback/windows/driver.py)、[game_window.py](../src/lyraforge/playback/windows/game_window.py) 实现 `winmm.timeBeginPeriod(1)`、Win32 结构体与 `user32` `@cache`、原子批量 `SendInput` 及其失败回滚保护、焦点轮询 `include_elevation=False` 与有界 PID 缓存。
   - **三层校准引擎、CLI、MCP 与精简 UI**：[src/lyraforge/playback/calibration.py](../src/lyraforge/playback/calibration.py) 实现 7 组测试序列（A–G）、3 级校准（`dry_run_virtual` / `realtime_scheduler` / 沿用两步确认的 `in_game_prepare` + WAV 起音与余音衰减分析），同步接入 [api/app.py](../src/lyraforge/api/app.py)、[api/playback_service.py](../src/lyraforge/api/playback_service.py)、[cli.py](../src/lyraforge/cli.py)（`lyraforge calibrate`）、[mcp/tools.py](../src/lyraforge/mcp/tools.py) 与桌面端 `StudioView.vue` / `PlaybackView.vue`。
2. **`scripts/eval_playback.py` 专项实测基准（macOS 本地运行）**：
   - **5–100 ms 下行琶音矩阵**：`1x` 倍速下 `BALANCED (arpeggiate_ms=12)` 与 `MELODY` 在 **9/9** 间隔（`5, 10, 15, 20, 30, 40, 50, 75, 100 ms`）均完整保留 6/6 音且音序与时刻精确一致；`2x` 倍速在 `10–100 ms` 全部精确保序（`5 ms @ 2x` 压缩为 `2.5 ms` 进入 `<= 4 ms` 同步和弦窗）。
   - **同键连击与跨轨让位**：连奏重复实测最小释放间隙 `20 ms`（原为 `0 ms`）；`Accomp @ 0 ms` 与 `Vocal @ 15 ms` 同键冲突中，主旋律轨 `track 0` 胜出（`melody_retrigger_replacements = 1`）。
   - **100 ms 系统卡顿恢复策略对照**：`catch_up` 在卡顿后将 4 音压缩至 `120 ms` 并发和弦；`shift_clock` 输出 `[0, 120, 150, 180, 210]`（`clock_shifts_count = 1`，保留 `30 ms` 相对琶音节奏）；`drop_late` 丢弃 3 个滞后音符避免爆发错音。
   - **Tier 2 实时 `MonotonicClock`（macOS Apple Silicon, `DryRunDriver`）**：
     - `distinct_key_rapid`（36 音）：`drift = 0.031 ms`，`CPU = 2.02%`，`P50 = 0.023 ms`，`P95 = 0.086 ms`，`Max = 2.394 ms`，`overlapping_key_downs = 0`；
     - `same_key_retrigger`（32 音）：`drift = 0.131 ms`，`CPU = 1.39%`，`P50 = 0.030 ms`，`P95 = 1.025 ms`，`Max = 2.432 ms`，`min_observed_release_gap = 20.002 ms`；
     - `chord_simultaneous`（20 音）：`drift = 0.306 ms`，`CPU = 0.88%`，`P50 = 0.031 ms`，`P95 = 0.246 ms`；
     - `rapid_arpeggio`（60 音）：`drift = 0.116 ms`，`CPU = 1.95%`，`P50 = 0.029 ms`，`P95 = 0.201 ms`；
     - `hold_release_sweep`（21 音）：`drift = 0.165 ms`，`CPU = 1.83%`，`P50 = 0.015 ms`，`P95 = 0.052 ms`，`min_observed_release_gap = 10.019 ms`；
     - `long_stability`（3.0s / 33 音）：`drift = 0.096 ms`，`CPU = 1.95%`，`P50 = 0.027 ms`，`P95 = 0.305 ms`，`Max = 1.292 ms`。
   - **合成 PCM WAV 校准解析往返**：Pattern B（`+60 ms` 偏移、屏蔽 `<60 ms` 连击）测得 `offset = 58.0 ms`、`detection_rate = 0.8125`、推荐 `min_same_key_interval_ms = 60`；Pattern G 准确区分 `one_shot`（短按衰减 `115.0 ms` vs 长按 `118.3 ms`）与 `sustained`（`91.7 ms` vs `365.0 ms`）。
3. **本地全量验证（代码定稿与合入前最终校验）**：
   - `uv run ruff check .` → `All checks passed!`；
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **283 passed, 2 warnings in 54.99s**，总覆盖率 **83.89%**（含 `test_playback_precision.py` 29 例与 `test_calibration.py` 5 例）；
   - `pnpm --dir apps/desktop/web test` → **Test Files 5 passed (5), Tests 17 passed (17)**；
   - `pnpm --dir apps/desktop/web build`（`vue-tsc --noEmit && vite build`） → `49 modules transformed`，`built in 1.12s`；
   - `make smoke` → 退出码 `0`（`OK: 24 events, profile genshin.windsong_lyre.v1 (hash verified)`，`actions_sent: 48`，`state: "completed"`）；
   - `uv run python scripts/eval_transcribers.py` → `pipeline_roundtrip` 通过（`transcribed_notes: 8`, `arranged_events: 8`）；
   - CSS 规范扫描：除 `tokens.css` 外无字面量色值。
4. **GitHub PR 与合并后 CI**：
   - [PR #29](https://github.com/PariyaProject/LyraForge/pull/29)（`1e70a98`）→ PR CI [Run #45397777519](https://github.com/PariyaProject/LyraForge/actions/runs/45397777519) 全部 4 项活动作业 `success`（`Test (windows-latest)`、`Test (macos-latest)`、`Build macOS Bundle (PyInstaller)`、`Build Windows Bundle (PyInstaller)`）；
   - Squash 合入 `main`（`afe8591`）→ 合并后 CI [Run #45398458703](https://github.com/PariyaProject/LyraForge/actions/runs/45398458703) 全部 5 作业（含 `Publish Desktop Releases (Windows & macOS)`）均为 `success`，已更新双平台 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 产物（`LyraForge-dev-20261124-afe8591-windows-x64.zip`、`LyraForge-dev-20261124-afe8591-macos-arm64.zip`、`SHA256SUMS.txt`）。
5. **验证边界与实机待确认项**：
   - 上述测试在 macOS `DryRunDriver`、虚拟时间膨胀/暂停时钟、Win32 API/winmm Mock 及合成 WAV 夹具上完成；`min_same_key_interval_ms=50`、`min_key_hold_ms=20`、`min_key_release_gap_ms=20`、`trigger_mode="one_shot"` 均明确标注 `provisional: true`。在物理 Windows 10/11 运行《原神》游戏客户端时不同琴种的真实最小发声保持时间、同键连击帧上限与多键同步上限，仍待维护者使用本轮 `lyraforge calibrate prepare` / 桌面校准面板实机录制 WAV 完成实测校准。


## 31. Round 29：人声伴奏动态层次编曲（Plan A）与工作室交互控制（Plan B）

1. **核心功能与架构范围**：
   - **Plan A（无头动态编曲与分句八度平滑引擎）**：新建纯标准库模块 [src/lyraforge/music_core/dynamics.py](../src/lyraforge/music_core/dynamics.py)（`AccompDensity`、`PhraseOctaveMode`、`StemDynamics`、`segment_melody_phrases`、`optimize_phrase_octaves`、`align_accompaniment_onsets`、`VocalSectionProfile`）；在 [arranger.py](../src/lyraforge/music_core/arranger.py) 注册 `vocal_dynamic` 策略，实现分句级 Viterbi DP（低音换气句智能抬升 `+12`、抵抗句内突跳）、跨轨微起音对齐（保护 `5–45 ms` 伴奏琶音不被压平）及高潮伴奏按拍门控稀疏化（`DropReason.ACCOMP_THINNED`，间奏自动放开）；`classic` 与 `vocal_lead` 在未传入覆写参数时保持 100% 原行为不变。[pipelines/builtin.py](../src/lyraforge/pipelines/builtin.py) 在分轨转录阶段按 `500 ms` 窗提取 `vocal_db` / `accomp_db` 写入转录 `metadata["stem_dynamics"]`，由 [library/store.py](../src/lyraforge/library/store.py) 透传至 `arrange()`。
   - **Plan B（游戏固定力度试听与工作室手工控制）**：[preview/synth.py](../src/lyraforge/preview/synth.py) 与 [api/app.py](../src/lyraforge/api/app.py)、[cli.py](../src/lyraforge/cli.py)、[mcp/tools.py](../src/lyraforge/mcp/tools.py) 新增 `fixed_velocity` 开关（缓存 `.fixed.wav` 并在 `DELETE` 时清理）；前端新增全局底栏 `#transport-fixed-vel-toggle`（联动 WAV 与 Piano Roll Web Audio 草稿试听）、`PianoRollEditor.vue` 选区 `+1八度` / `-1八度`（含 `Shift+↑/↓` 与右键菜单）、`伴奏瘦身`（每 `380 ms` 保留一个骨架锚点）与 `清伴奏`（全可撤销/重做），以及 `StudioView.vue` 动态密度/分句八度/微对齐选择器与 `伴奏节奏让路` / `低音句抬升八度` / `跨轨微对齐` 报告徽章。
2. **`scripts/eval_dynamics.py` 三场景对比实测结果（`genshin.windsong_lyre.v1`）**：
   | 场景 | 策略 | 主旋律 | 伴奏总数 | 高潮伴奏 | 间奏伴奏 | 主歌中位音高 | 伴奏让路 | 微对齐 | 抬升句数 | 总评分 |
   |---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
   | `1_climax_plus_offset` | `classic` / `vocal_lead` | 12 | 33 | 17 | 0 | 80.0 | 0 | 0 | 0 | 96.7 |
   | `1_climax_plus_offset` | `vocal_dynamic` | 12 | 13 | 8 | 0 | 80.0 | 20 | 8 | 0 | 69.2 |
   | `2_muddy_verse_high_chorus` | `classic` | 16 | 16 | 6 | 4 | 52.0 (E3) | 0 | 0 | 0 | 99.2 |
   | `2_muddy_verse_high_chorus` | `vocal_lead` | 16 | 12 | 4 | 4 | 52.0 (E3) | 0 | 0 | 0 | 89.4 |
   | `2_muddy_verse_high_chorus` | `vocal_dynamic` | 16 | 16 | 6 | 4 | **64.0 (E4)** | 0 | 0 | **1** | **99.1** |
   | `3_verse_climax_interlude` | `classic` / `vocal_lead` | 10 | 26 | 10 | 8 | 74.0 | 0 | 0 | 0 | 100.0 |
   | `3_verse_climax_interlude` | `vocal_dynamic` | 10 | 17 | **5** | **8** | 74.0 | 9 | 0 | 0 | 84.7 |
3. **本地全量验证与 CSS 规范检查**：
   - `uv run ruff check .` → `All checks passed!`；
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **290 passed, 2 warnings in 54.56s**，总覆盖率 **84.05%**（含 `test_dynamic_arranger.py` 7 例完整覆盖动态包络提取、Viterbi 分句八度平滑、跨轨微对齐与琶音保护、高潮让路/间奏放开、`fixed_velocity` WAV 合成与缓存清理、CLI/API/MCP 链路）；
   - `pnpm --dir apps/desktop/web test` → **Test Files 5 passed (5), Tests 19 passed (19)**（含 `PianoRollInteractions.spec.ts` `±1八度`/`伴奏瘦身`/`清伴奏` 与 `App.spec.ts` `vocal_dynamic`/固定力度开关回归）；
   - `pnpm --dir apps/desktop/web build` → `49 modules transformed`，`built in 1.10s`；
   - `make smoke` → 退出码 `0`（`OK: 24 events, profile genshin.windsong_lyre.v1 (hash verified)`）；
   - `uv run python scripts/eval_transcribers.py` → `pipeline_roundtrip` 通过（`transcribed_notes: 8`, `arranged_events: 8`）；
   - CSS 规范扫描（除 `tokens.css` 外）：无任何字面量色值。
4. **GitHub PR、合并后 CI 与验证边界**：
   - [PR #30](https://github.com/PariyaProject/LyraForge/pull/30)（`35d8e46`）→ PR CI [Run #45525242428](https://github.com/PariyaProject/LyraForge/actions/runs/45525242428) 全部 4 项活动作业 `success`；
   - Squash 合入 `main`（`6b2abaf`）→ 合并后 CI [Run #45525789807](https://github.com/PariyaProject/LyraForge/actions/runs/45525789807) 全部 5 作业（含 `Publish Desktop Releases (Windows & macOS)`）均为 `success`，已更新双平台 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 产物：`LyraForge-dev-20261125-6b2abaf-windows-x64.zip`、`LyraForge-dev-20261125-6b2abaf-macos-arm64.zip`、`SHA256SUMS.txt`；
   - **验证边界**：真实人声流行歌在物理 Windows 安装 Demucs + 真实《原神》游戏客户端下的长曲动态对比听感，仍待维护者在新版 `dev-latest` 客户端中导入真实歌曲试听与实机演奏确认。

## 32. Round 30：谐律键琴默认乐器、多音色试听与草稿播放体验全面升级

1. **核心功能与修复**：
   - **默认乐器切换为「谐律键琴」与多音色试听合成**：新增 [genshin.harmonic_keys.v1.json](../src/lyraforge/instruments/data/genshin.harmonic_keys.v1.json)（原神 4.6 谐律键琴 21 键 `C3–B5` `Z-M`/`A-J`/`Q-U`）并更新 `DEFAULT_PROFILE_ID`、预设 `presets.py`、自然语言识别 `agent/llm.py` 及前端默认选项（完整保留原有 3 份乐器档案 JSON 与校验哈希）；离线试听 [preview/synth.py](../src/lyraforge/preview/synth.py) 与浏览器端 [webAudioPreview.ts](../apps/desktop/web/src/utils/webAudioPreview.ts) 同步支持 `piano` / `lyre` / `zither` / `vintage` 四套独立泛音与衰减包络（谐律键琴自动对应带槌击瞬态与高/低音区差异衰减的 `piano` 音色），透传 `LibraryStore` 缓存、`POST/GET /v1/preview`、CLI `--timbre`、MCP `preview` 与 Piano Roll `#pr-timbre-select`。
   - **草稿播放控制与版本重置修复**：修复 [PianoRollEditor.vue](../apps/desktop/web/src/components/PianoRollEditor.vue) 切换或新生成编曲版本后未清零 `draftPlayheadMs` 导致从旧版本时间点续播的问题；暂停时保留可见播放头与 `mm:ss / mm:ss` 时间读数；区分 `试听草稿 / 继续草稿` 与显式 `从头播`；点击时间尺可在暂停或播放中直接定位跳转。
   - **工作室全局快捷键与歌词式智能跟随 + 实时编辑**：在工作区级挂载 `Space`（播放/暂停）、`Shift+Space`（从头重播）、`Home`（归零）与 `F`（一键回正恢复跟随），焦点离开画布同样生效（输入框/弹窗内自动让位）；播放器按滑窗实时读取当前编辑谱面与音轨聚焦状态，实现边播边切独奏/边改谱即时生效；播放中手动横向滚动自动解除强制拉回并在角落显示带方向指示的 `#pr-return-playhead-btn`（`← 回到播放头` / `回到播放头 →`），拖回当前播放区停留 400 ms 自动重新吸附跟随。
2. **验证记录**：
   - `uv run ruff check .` → `All checks passed!`；
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **293 passed, 2 warnings in 71.58s**，总覆盖率 **84.11%**（含 `test_harmonic_keys_and_timbres.py` 3 例与既有 3 份乐器档案 SHA-256 哈希零改动回归）；
   - `pnpm --dir apps/desktop/web test` → **Test Files 5 passed (5), Tests 21 passed (21)**（含版本切换归零、全局 `Space`/`Shift+Space`/`Home`/`F`、边播边改独奏、`400 ms` 歌词式自动重吸附、方向回归按钮与谐律键琴默认选择回归）；
   - `pnpm --dir apps/desktop/web build` → `49 modules transformed`，`built in 1.05s`；
   - `make smoke` → 默认档案 `genshin.harmonic_keys.v1` 校验通过（`OK: 24 events, profile genshin.harmonic_keys.v1 (hash verified)`）；
   - CSS 规范扫描（除 `tokens.css` 外）：无任何字面量色值；
   - [PR #31](https://github.com/PariyaProject/LyraForge/pull/31)（`4ff0089`）→ PR CI [Run #45536932945](https://github.com/PariyaProject/LyraForge/actions/runs/45536932945) 4 项活动作业全部 `success`；
   - Squash 合入 `main`（`7c1d78e`）→ 合并后 `main` CI [Run #45537569869](https://github.com/PariyaProject/LyraForge/actions/runs/45537569869) 全部 5 作业 `success`，已更新双平台 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 产物：`LyraForge-dev-20261125-7c1d78e-windows-x64.zip`、`LyraForge-dev-20261125-7c1d78e-macos-arm64.zip`、`SHA256SUMS.txt`；
   - **验证边界**：浏览器 Web Audio / 离线合成的钢琴与风物之诗琴音色均为纯跨平台数学泛音合成（无游戏提取音频样本），与《原神》游戏客户端真实音色听感对比、以及 Windows 物理机长曲工作流体验待用户在 `dev-latest` 上确认。


## 33. Round 31：CC0 真实原声钢琴/竖琴采样音源、多轨同步试听、实时参数预览差分与工作室 UX 整合

1. **核心功能与架构升级**：
   - **合规 CC0-1.0 真实采样音库与丰满和弦混音（严禁提取游戏本体音频）**：新建 [scripts/build_cc0_samples.py](../scripts/build_cc0_samples.py)，从锁定提交的开源 `sgossner/VCSL`（`c1ea7bcc3c7309650ab0da9d15c9cd1fbc4a4c7e`，`CC0-1.0` Public Domain）拉取 Steinway Model B 三角钢琴（9 锚点）、音乐会竖琴（6 锚点）与十三弦古筝（5 锚点），经 `afconvert`/Python 降采样与首尾无Click裁剪封装为 `22,050 Hz` 单声道 16-bit WAV（总计 `1.4 MB`，附带 SHA-256 `manifest.json`）并纳入 [packaging/lyraforge.spec](../packaging/lyraforge.spec) 打包校验；升级 [synth.py](../src/lyraforge/preview/synth.py)（真采样线性重采样 + 同音高前音轻阻尼防梳状滤波 + Soft-Knee 和弦压限）、[app.py](../src/lyraforge/api/app.py)（`/v1/preview/samples/manifest` 与路径白名单校验 `/v1/preview/samples/{pack}/{filename}`）及浏览器 [webAudioPreview.ts](../apps/desktop/web/src/utils/webAudioPreview.ts)（样本预加载解码 + `DynamicsCompressorNode` + 微量厅堂混响母线、移除粗糙锯齿音兜底）。
   - **Piano Roll 多轨同步复选试听与全时长不早退**：将 `focusedTrackIndex` 升级为 `audibleTracks: Set<number> | null` 复选框 + 独立 `独奏` 按钮（可同时勾听任意音轨组合）；`startDraftSequencer()` 新增 `getTotalDurationMs` 回调，切换/独奏短音轨或静音轨时继续推进至全曲结束，不再中途突停归零；重构 `onTimelineScroll()` / `lastProgrammaticScrollLeft` / `onScrollPointerDown()` 与纯手动 `回到播放点` 按钮，彻底取消 400 ms 自动强拉机制。
   - **中文音轨映射、实时参数谱面差分预览与工作室单流化收口**：新增 [trackNames.ts](../apps/desktop/web/src/utils/trackNames.ts) 将常见英文分轨名及 GM 乐器名译为直观中文（如 `Vocal Lead` → `人声主旋律`、`Accompaniment` → `伴奏`）并标注音域（`C4–E5`）及提示原始轨名与调整详情；新增无落盘 `POST /v1/studio/preview-arrange`（配合 [store.py](../src/lyraforge/library/store.py) 有界 `_load_midi_cached` 解析缓存），调整工作室参数时在 Piano Roll 上叠加「删减（红虚线）/ 新增（绿虚线）」幽灵预览与 `仅看改后谱面` / `应用并生成版本` / `还原当前参数`；整合顶栏与右侧检查器为「一键预设 + 核心编曲设置（含编曲风格微型示意图）+ 折叠专业微调 + 折叠可选 A/B 对比」，并在 `POST /v1/jobs/arrange` 透传 `created` 字段以明确提示「已新建版本」或「匹配已有同参数版本（未重复新建）」。
2. **本地全量验证与性能实测（最终代码定稿后实测）**：
   - `pnpm --dir apps/desktop/web install --frozen-lockfile` → 通过（`39ms`）；
   - `pnpm --dir apps/desktop/web exec vue-tsc --noEmit` → 退出码 `0`；
   - `uv run ruff check .` → `All checks passed!`；
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **296 passed, 2 warnings in 67.37s**，总覆盖率 **83.92%**（含 `test_preview.py` CC0 清单 SHA-256 校验 / 路径穿越拦截 / 四音色无削波回归，以及 `test_api.py` `/v1/preview/samples/*` 鉴权、`/v1/studio/preview-arrange` 零落盘与 `/v1/jobs/arrange` `created` 去重状态验证）；
   - `pnpm --dir apps/desktop/web test` → **Test Files 6 passed (6), Tests 25 passed (25)**（含 `trackNames.spec.ts`、`PianoRollInteractions.spec.ts` 多轨复选试听 / 短轨续播不早退 / 手动拖放不自动回正 / 幽灵预览差分、`App.spec.ts` 实时参数预览与新建/去重提示回归）；
   - `pnpm --dir apps/desktop/web build` → `50 modules transformed`，`built in 1.18s`（CSS `60.59 kB` / JS `290.87 kB`）；
   - `make smoke` → 退出码 `0`（`OK: 24 events, profile genshin.harmonic_keys.v1 (hash verified)`）；
   - **纯 Python 合成基准（`genshin.harmonic_keys.v1`, 150 音富和弦谱）**：`0.829s` 生成 `459,566` 字节 WAV；采样包总占用 `1.4 MB`；
   - **CSS 设计规范扫描**：`apps/desktop/web/src/` 下除 `tokens.css` 外零字面量色值。
   - **GitHub PR、双平台 CI 与 `dev-latest` 发布验证**：
     - [PR #32](https://github.com/PariyaProject/LyraForge/pull/32)（`43b748d`）→ PR CI [Run #45553263693](https://github.com/PariyaProject/LyraForge/actions/runs/45553263693) 全部 4 项活动作业（`Test (windows-latest, Python 3.11)`、`Test (macos-latest, Python 3.11)`、`Build Windows Bundle (PyInstaller)` 含 `lyraforge/preview/samples/` payload 检查、`Build macOS Bundle (PyInstaller)`）均为 `success`；
     - Squash 合入 `main`（`451a1d6`）→ 合并后 `main` CI [Run #45553803862](https://github.com/PariyaProject/LyraForge/actions/runs/45553803862) 全部 5 项作业（含 `Publish Desktop Releases (Windows & macOS)`）均为 `success`，已更新双平台 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 产物（`2026-11-25T05:32:57Z`）：`LyraForge-dev-20261125-451a1d6-windows-x64.zip`、`LyraForge-dev-20261125-451a1d6-macos-arm64.zip`、`SHA256SUMS.txt`。
3. **验证边界说明**：
   - 物理 Windows 10/11 客户端下 CC0 原声采样音色的实际桌面听感、PyInstaller 窗口启动体验，以及《原神》实机谐律键琴演奏表现，仍待用户在下载最新 `dev-latest` 构建后现场确认（自动化端到端浏览器采样路径已在 `FakeAudioCtx` 与本地 FastAPI/Pytest 环境下验证通过）。


## 34. Round 32：纯净美化合成音色、纯横向防误锁平滑滚动与统一不自动生成表单

1. **声学诊断与音色彻底清理优化**：
   - 对原 VCSL 实录包执行全量基频/包络扫描并发现显著客观缺陷：`zither` 实录高出整整一个八度（`H2 >> H1`）且存在 `-50..+46` 音分走音，`lyre` 全键偏低约 `-12` 音分且相邻键均方根音量差达 `11.6 dB`，`piano` 中高音 `72_C5.wav` 呈断奏快速衰减且 `G#3/E4/G#4` 存在近 `40 ms` 起音前空隙；同时 [webAudioPreview.ts](../apps/desktop/web/src/utils/webAudioPreview.ts) 的 `createRoomImpulse()` 向每颗音符叠加未经滤波的白噪声卷积混响导致背景沙哑刺耳。
   - **修复方案**：彻底删除 `src/lyraforge/preview/samples/`（20 条 WAV + 清单）、`scripts/build_cc0_samples.py`、`/v1/preview/samples/*` 路由及白噪混响器；重做 [preview/synth.py](../src/lyraforge/preview/synth.py)（相位锁定三角递推泛音 + `piano` 最长歌唱余韵 > `lyre` > `zither` > `vintage` + 全 21 键音量平衡 + `same_pitch_caps` 同音防叠加 + Soft-Knee 限幅）与 [webAudioPreview.ts](../apps/desktop/web/src/utils/webAudioPreview.ts)（同音 `18 ms` 干净收尾 + 纯正泛音低通顺滑过滤），彻底消除沙哑噪声与走音。
2. **Piano Roll 纯横向防误锁与连续平滑跟随**：
   - 修复 [PianoRollEditor.vue](../apps/desktop/web/src/components/PianoRollEditor.vue) 垂直滚轮 / 拖拽右侧竖向滚动条触发 `onTimelineScroll()` / `onScrollPointerDown()` 而意外定格播放跟随的问题（仅当横向 `scrollLeft` 真实变化、拖按底部横向滚动条或横向滚轮 / `Shift+滚轮` 时才脱离）；将原先「撞击右边缘后瞬间大幅跳屏」的切换式跟随替换为围绕视口 30% 锚点连续推进与三次缓动动画（`animateScrollLeftTo`）。
3. **编曲工作室表单统一、模板不自动生成与历史版本设置完整展示**：
   - `applyPreset()` 与 `applyRecommendedVocalSetup()` 不再触发 `handleArrange()`，改为直接填入表单参数并立即调用 `requestLiveArrangePreview(true, { force: true })` 在谱面预览变化，由底部统一确认按钮 `#studio-apply-arrange-btn`（或顶栏 `生成改编版本`）提交生成；明确将「声部厚度（`主旋律 ≤2 键` / `均衡 ≤3 键` / `丰满 ≤6 键`）」与上方快捷参数模板区隔。
   - 切换 `#studio-arr-select` 时依据 `report.transform` / `performance.transform`（[api.ts](../apps/desktop/web/src/api.ts)）完整同步所有参数控件及分轨配置，并在检查器顶部 `#studio-version-settings` 展示当前版本全部已保存设置标签。
4. **本地全量验证与声学回归结果（最终代码定稿后实测）**：
   - `pnpm --dir apps/desktop/web install --frozen-lockfile` → 通过（`10ms`）；
   - `pnpm --dir apps/desktop/web exec vue-tsc --noEmit` → 退出码 `0`；
   - `uv run ruff check .` → `All checks passed!`；
   - `uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **296 passed, 2 warnings in 96.46s**，总覆盖率 **84.17%**（含 `test_studio_timbres_pure_tuned_and_balanced_across_register` 验证四音色 `C3..B5` 全键音准显著高于高八度与 `±3%` 偏音、跨音区 RMS 比 `< 2.2x`、`test_preview.py` 稠密和弦零削波与 `test_api.py` `transform` 字段透传校验）；
   - `pnpm --dir apps/desktop/web test` → **Test Files 6 passed (6), Tests 26 passed (26)**（新增覆盖纯竖向滚动/滚轮/右滚动条不脱离跟随、连续平滑滚动、点击模板不触发 `arrangeSong` 仅实时预览、以及切版本同步控件与展示 `#studio-version-settings`）；
   - `pnpm --dir apps/desktop/web build` → `50 modules transformed`，`built in 1.06s`（CSS `61.43 kB` / JS `295.26 kB`）；
   - `make smoke` → 退出码 `0`（`OK: 24 events, profile genshin.harmonic_keys.v1 (hash verified)`）；
   - **纯 Python 音色实测**：150 音富和弦钢琴合成 `1.762s`（`941,580` 字节）；`dense_chords` 四音色峰值均锁定 `0.920` 零削波、RMS `0.153–0.155`；CSS 字面量色值扫描 0 违规。
   - **GitHub PR、双平台 CI 与 `dev-latest` 发布验证**：
     - [PR #33](https://github.com/PariyaProject/LyraForge/pull/33)（`b325a3d`）→ PR CI [Run #45590387558](https://github.com/PariyaProject/LyraForge/actions/runs/45590387558) 全部 4 项活动作业（`Test (windows-latest, Python 3.11)`、`Test (macos-latest, Python 3.11)`、`Build Windows Bundle (PyInstaller)`、`Build macOS Bundle (PyInstaller)`）均为 `success`；
     - Squash 合入 `main`（`9811baa`）→ 合并后 `main` CI [Run #45591168649](https://github.com/PariyaProject/LyraForge/actions/runs/45591168649) 全部 5 项作业（含 `Publish Desktop Releases (Windows & macOS)`）均为 `success`，已更新双平台 [`dev-latest`](https://github.com/PariyaProject/LyraForge/releases/tag/dev-latest) 产物（`2026-11-25T10:08:06Z`）：`LyraForge-dev-20261125-9811baa-windows-x64.zip`、`LyraForge-dev-20261125-9811baa-macos-arm64.zip`、`SHA256SUMS.txt`。
5. **验证边界说明**：
   - 物理 Windows 10/11 桌面窗下浏览器真机音色听感、垂直/水平滚轮及滚动条平滑跟随手感，以及《原神》实机演奏表现，仍待维护者下载并试听新发布的 `dev-latest` 双平台包最终确认。
