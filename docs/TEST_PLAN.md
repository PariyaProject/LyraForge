# LyraForge 测试计划（Test Plan）

> **更新日期**：2026-11-22  
> **覆盖范围**：M0 自动化验收 + 跨平台 CI 矩阵（macOS / Windows） + M1 Windows 真机《原神》人工验收规程

---

## 1. 测试环境矩阵

| 环境 | 执行内容 | 自动/人工 | 说明 |
|---|---|---|---|
| **macOS Apple Silicon（Mac mini M4 本地）** | `ruff check`、`pytest`（unit + integration + layering）、CLI 端到端、`DryRunDriver` 模拟演奏 | 全自动 | 主开发机；不接触真实游戏，无 Windows 依赖 |
| **GitHub Actions `macos-latest`** | `uv sync --frozen`、lint、pytest（覆盖率 ≥80%）、fixture 一致性校验、CLI DryRun 冒烟 | 全自动 CI | 每次 push / PR 触发 |
| **GitHub Actions `windows-latest`** | 同上全套测试 +（M1 起）PyWebView/PyInstaller Windows 构建与冒烟检查 | 全自动 CI | 验证 Windows 路径、编码（UTF-8）、依赖与打包 |
| **Windows 10/11 真机 + 《原神》PC 版** | 21 键实音校准、`WindowsKeyboardDriver` 焦点切换急停、ESC 紧急停止、非管理员运行 | **单独人工验收** | 无法在 macOS 或无游戏 headless CI 中伪造，须由真机实测并记录 |

---

## 2. M0 自动化测试套件

### 2.1 单元测试（`tests/unit/`）
1. `test_tempo.py`：`TempoMap` 的 `Fraction` 精确累加、多段变速（120→60→180 BPM）、同 tick 多事件取最后值、缺省 120 BPM、非法参数校验、`to_json()`。
2. `test_midi_import.py`：SMF Type 0/1、非 Track 0 `set_tempo` 全局应用与告警、`time_signature`、同音高重叠 FIFO 配对、`note_on(vel=0)` 作 note-off、孤立 `note_off` 与未闭合音符告警、空 MIDI、全部 5 个损坏/不支持样例（`MEDIA_DECODE_FAILED` / `MEDIA_UNSUPPORTED`）、文件缺失（`SOURCE_UNAVAILABLE`）、`ImportLimits` 大小/音符数/时长超限（`LIMIT_EXCEEDED`）。
3. `test_profile.py`：内置 `genshin.windsong_lyre.v1`（21 键、MIDI 48–83 自然大调音阶、唯一键位与音高、`unverified` 校准状态、确定性哈希）、文件加载、`key_count` 不符/重复字段/时序矛盾/`supports_sustain=True` 等 Schema 与语义拒绝。
4. `test_arranger.py`：同输入同配置输出确定性、C 大调零移调、D 大调自动 -2 半音移调、半音阶 `nearest` 替换与 `drop` 策略、超音域整八度折叠、密集连击限制（`repeat_too_fast`）、和弦上限（`melody`/`balanced`/`rich` 与同毫秒同键去重）、GM 打击乐剔除与显式保留、轨道白名单、变速与三连音精确时刻、倍速缩放（0.5x/2.0x）、空谱 `NO_PLAYABLE_NOTES` 与参数校验 `INVALID_ARGUMENT`。
5. `test_performance.py`：全部有效 fixture 生成的 `performance.json` 通过 JSON Schema Draft 2020-12 与语义验证；拒绝乱序 `at_ms`、同键持键时间重叠、未知 `key_id`、`mapped_pitch` 不一致、`duration_ms` 不足、`instrument_profile_hash` 不匹配。
6. `test_player.py`：`VirtualClock` 零漂移时序、同毫秒 `UP` 先于 `DOWN`、`StopToken` 停止后立即 `release_all`、`FocusGuard` 返回 False 时状态为 `FOCUS_LOST` 且释放全部按键、驱动抛异常（`ERROR`）与 `KeyboardInterrupt` 路径全释放按键、`release_all()` 异常时降级逐键 `key_up()`、`MonotonicClock` 短时实时测试（`@pytest.mark.realtime`）。
7. `test_layering.py`：AST 静态导入门禁，确保 `music_core`、`instruments`、跨平台 `playback` 及 `pyproject.toml` 核心依赖不包含任何 GUI、Win32/ctypes、网络、subprocess 或 Windows 专属依赖。

### 2.2 集成与 Fixture 测试（`tests/integration/`）
- 验证 `tests/fixtures/midi/` 下全部 17 个文件与 `midi_builders.FIXTURES` 生成字节逐一匹配（确保无未声明二进制文件）。
- 端到端调用 `lyraforge.cli.main`：`profiles list`、`profiles show`、`inspect`、`arrange`（含 `--report` 与字节级确定性校验）、`validate`、`playback dry-run`（含 `--log` 与 `--stop-after-ms`）、`import` / `library` / `preview`、`engines list` / `transcribe` 及异常退出码验证。
- 本地 FastAPI 服务 `TestClient`（鉴权、导入 MIDI/音频、异步转录与取消、编曲、WAV 试听、MIDI/JSON 导出、设置持久化、两步授权播放与静态资源引导）与 Vue 3 Vitest 测试。
- M2 新增单元测试：`test_cleanup_and_export.py`、`test_media.py`（WAV 原生提取与 FFmpeg 子进程 Mock）、`test_transcribers.py`（端到端 WAV→MIDI F1 ≥ 0.75 回归 + 3 类音频流水线 + Basic Pitch / dettato 隔离适配器 Mock）及 SQLite v1→v2 迁移测试。

---

## 3. 自制 MIDI 回归数据集清单

| 文件名 | 测试目标 |
|---|---|
| `c_major_scale.mid` | 标准 C4–C5 音阶，应 0 移调、0 改音直接命中 |
| `d_major_scale.mid` | D 大调音阶，应自动移调 `-2` 半音至全自然大调可弹 |
| `chords_type1.mid` | SMF Type 1 多轨（Conductor + 旋律 + 三和弦伴奏），验证时间同步与音色分轨 |
| `chromatic.mid` | C4–C5 13 个半音，验证 `nearest` 替换与 `drop` 丢弃策略 |
| `wide_range.mid` | 极低/极高音域（MIDI 21–108），验证整八度折叠 |
| `repeated_notes.mid` | 25ms 极快连击 vs 62.5ms 正常连击，验证 `min_same_key_interval_ms` 过滤 |
| `tempo_changes.mid` | 120 → 60 → 180 BPM 多段变速，验证精确微秒/毫秒换算 |
| `triplets.mid` | 三连音（160 ticks/音），验证非整数拍时间戳舍入 |
| `dense_chords.mid` | 6 音大和弦 + 跨轨重复键 + 人性化微偏移簇，验证和弦窗与复音裁剪 |
| `percussion.mid` | GM 通道 9 打击乐混合旋律，验证默认过滤与统计 |
| `empty.mid` | 0 音符 MIDI，验证安全报错 `NO_PLAYABLE_NOTES` |
| `overlap_edge.mid` | 同音高重叠（FIFO）、`vel=0` note-off、孤立 note-off、未闭合音符兜底 |
| `broken/not_midi.mid` 等 5 个 | 非 MIDI 头、截断文件、损坏 MTrk 长度、SMF Type 2、SMPTE 分辨率 |

---

## 4. Windows 真机《原神》单独人工验收清单（M1+ 执行，M0 不触碰游戏）

在 M1 完成 `lyraforge.playback.windows` 并由 GitHub Actions 生成 Windows 产物后，必须在 Windows 10/11 PC 上单独完成以下验证并回填记录：

- [ ] **非管理员运行**：以普通 Windows 用户权限启动 LyraForge，无需关闭 Windows Defender 或修改 UAC。
- [ ] **21 键实音校准**：在《原神》大世界打开风物之诗琴界面，逐一触发 Z–M / A–J / Q–U 21 键，核对音高与屏幕按键位置一致，随后更新 Profile 为 `verified`。
- [ ] **单音 15 秒连贯性**：播放单音旋律，人工听感无粘键、漏键或明显漂移。
- [ ] **和弦与快速重复**：播放 `chords_type1` 与 `repeated_notes`，确认游戏内和弦能同时发声且无卡键。
- [ ] **焦点离开立即中止**：播放过程中 Alt+Tab 切至记事本/桌面，`ForegroundWindowGuard` 立即触发中止并在 50ms 内释放全部按键。
- [ ] **ESC / 紧急停止**：按下紧急停止热键，确认立即终止且无遗留按下状态，再次启动仍可正常演奏。
- [ ] **不同帧率/负载观测**：记录实测帧率下 `max_lateness_ms` 与实际听感偏差。
