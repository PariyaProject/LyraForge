# LyraForge Code Review 问题修复与工程质量验收报告（FIX-001 ~ FIX-009）

> **仓库地址**：`https://github.com/PariyaProject/LyraForge`  
> **修复基准提交（HEAD）**：`a682716414d04af79fab16b5cbd2006792d6afd1`（`feat: initial LyraForge M0-M5 release (GPL-3.0)`）  
> **开源许可声明**：继续严格保留 **GNU General Public License v3.0 (GPL-3.0)**（[LICENSE](file:///Users/wuzhao/Program/Github/lyraforge_starter/LICENSE)、[pyproject.toml](file:///Users/wuzhao/Program/Github/lyraforge_starter/pyproject.toml)、[package.json](file:///Users/wuzhao/Program/Github/lyraforge_starter/apps/desktop/web/package.json)、[LICENSE_AUDIT.md](file:///Users/wuzhao/Program/Github/lyraforge_starter/docs/LICENSE_AUDIT.md) 均完整保留，无未授权更改）  
> **验证环境**：`macOS Darwin (Apple Silicon)`，`Python 3.11.13`，`uv`，`pnpm 12.6.0`（待在 Windows 10/11 真机与 GitHub Actions 推送后完成目标平台验收）

---

## 一、修复总览与五态成熟度汇总

| 编号 | 问题域 | 优先级 | 涉及主要文件 | 成熟度状态 | 验证结论摘要 |
|---|---|---|---|---|---|
| **FIX-001** | GitHub Actions CI `pnpm` 缺失与 Windows EXE 产物校验 | P0 | [.github/workflows/ci.yml](file:///Users/wuzhao/Program/Github/lyraforge_starter/.github/workflows/ci.yml), [package.json](file:///Users/wuzhao/Program/Github/lyraforge_starter/apps/desktop/web/package.json), [pnpm-lock.yaml](file:///Users/wuzhao/Program/Github/lyraforge_starter/apps/desktop/web/pnpm-lock.yaml) | **已实现但未完成真实环境验收** | 本地 `pnpm --dir apps/desktop/web install --frozen-lockfile`、`vitest`、`vite build` 与 `pytest` 全部通过；远端 GitHub Actions 待推送至 `origin/main` 后复跑确认 |
| **FIX-002** | API Key 系统凭据存储、日志脱敏、旧明文迁移与备份/分享包清洗 | P0 | [secrets.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/secrets.py), [secrets_win32.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/secrets_win32.py), [store.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/library/store.py), [packaging.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/library/packaging.py), [llm.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/agent/llm.py), [orchestrator.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/agent/orchestrator.py), [App.vue](file:///Users/wuzhao/Program/Github/lyraforge_starter/apps/desktop/web/src/App.vue) | **已实现且已测试**（Windows CredMan 为 **已实现但未完成真实环境验收**） | macOS Keychain (`security -i` stdin `-X <hex>`)、`0o600` 回落文件、环境变量 `LYRAFORGE_LLM_API_KEY`、旧明文自动迁移清除、备份与 `.lyrapack` 剥离及异常脱敏均通过实测；`secrets_win32.py` (`advapi32.dll`) 已隔离待 Windows 真机测 |
| **FIX-003** | Windows `key_up` / `release_all` 状态一致性与重试恢复 | P1 | [driver.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/playback/windows/driver.py), [win32_types.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/playback/windows/win32_types.py), [test_windows_playback.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/tests/unit/test_windows_playback.py) | **已实现但未完成真实环境验收** | 已修正原测试掩盖的 `key_up()` 提前 `discard()` 缺陷；确认仅在 `_send_release_with_retry()` 成功后清除 `self.pressed`，且失败键保留状态供后续 `release_all()` 重试；真机《原神》校准与松键待 Windows 测试 |
| **FIX-004** | 全库备份恢复分阶段暂存、SQLite 完整性校验与故障自动回滚 | P1 | [packaging.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/library/packaging.py), [test_lyrapack_and_m5.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/tests/unit/test_lyrapack_and_m5.py) | **已实现且已测试** | 恢复不再先删除现有曲库；在临时暂存目录校验 Manifest 与 `PRAGMA integrity_check`、完成 WAL checkpoint 后生成 `.rollback-*` 快照并换入，任意 `Exception`/`OSError` 自动完整回滚原库 |
| **FIX-005** | 外网下载 DNS 解析固定（防 DNS Rebinding TOCTOU）、重定向与超时限制 | P1 | [url.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/sources/url.py), [test_secrets_and_security.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/tests/unit/test_secrets_and_security.py) | **已实现且已测试** | 新增 `_PinnedHTTPConnection`/`_PinnedHTTPSConnection` 保持校验阶段 IP 与真实 TCP 连接一致且保留 HTTP `Host` 与 TLS SNI；封堵 IPv4-mapped IPv6/6to4/CGNAT/内嵌账号 URL，限制重定向 `<=5` 跳、总耗时 `<=30s`、中断无残留文件 |
| **FIX-006** | 合法开放曲库在线检索（Internet Archive CC/PD）与候选排序 / 音频回退转谱 | P2 | [online.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/sources/online.py), [__init__.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/sources/__init__.py), [orchestrator.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/agent/orchestrator.py), [App.vue](file:///Users/wuzhao/Program/Github/lyraforge_starter/apps/desktop/web/src/App.vue), [test_agent_and_sources.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/tests/unit/test_agent_and_sources.py) | **部分实现** | 实现 `rank_candidates`（本地 > MIDI > 音频 > 开放许可/相关性）与 `OpenMusicCatalogSourceAdapter`（复用 DNS 固定 HTTPS 连接与 `allow_network` 二次确认门禁，优先下载 MIDI，缺失时回退自动转谱 WAV）；通过本地路由 Mock 完整验证，未接入商业版权平台且公网实时连通待运行期验证 |
| **FIX-007** | 转录引擎可用性探测与多场景合成音频真实基准评测 | P2 | [eval_transcribers.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/scripts/eval_transcribers.py) | **部分实现 / 因外部环境阻塞** | 内置 `builtin-mono` 在多谐波合成单音旋律达 `F1=1.0000`，而在 `polyphonic_piano_chords` (`F1=0.0`) 与 `dense_multi_register` (`F1=0.3333`) 如实暴露单音 YIN 算法边界；`ffmpeg`/`basic-pitch`/`dettato` 因当前环境未安装而阻塞 |
| **FIX-008** | 清理 `AGENTS.md` 过期“仅限 M0”工作区指令 | 文档/工程规范 | [AGENTS.md](file:///Users/wuzhao/Program/Github/lyraforge_starter/AGENTS.md) | **已实现且已测试** | 移除过时的 `M0 only` 与“UI 尚在规划”描述，明确 GPL-3.0 保留规则、M0–M5 现状、凭据安全边界与 `make check` 门禁 |
| **FIX-009** | `docs/PROGRESS.md`、`README.md` 与能力边界文档诚实对齐 | 文档/工程规范 | [PROGRESS.md](file:///Users/wuzhao/Program/Github/lyraforge_starter/docs/PROGRESS.md), [README.md](file:///Users/wuzhao/Program/Github/lyraforge_starter/README.md), [REVIEW_FIX_REPORT.md](file:///Users/wuzhao/Program/Github/lyraforge_starter/docs/REVIEW_FIX_REPORT.md) | **已实现且已测试** | 全面引入五态成熟度标注，诚实区分 macOS 已测、Windows 待真机验收及外部工具缺失项 |

---

## 二、逐项问题排查与修复详情

### FIX-001：GitHub Actions CI 失败（P0）

- **问题复核**：通过 `gh run list --repo PariyaProject/LyraForge` 查询基准提交 `a682716414d04af79fab16b5cbd2006792d6afd1` 的远端 CI 记录（Run ID `44977619933`），确认双平台流水线在 `pnpm/action-setup@v4` 步骤失败，报错：`Error: No pnpm version is specified.`；同时 `package-windows` 步骤仅执行 bare `Test-Path dist/LyraForge/LyraForge.exe`，PowerShell 仅打印 `False` 而不以非零状态失败。
- **修复内容**：
  1. 在 [apps/desktop/web/package.json](file:///Users/wuzhao/Program/Github/lyraforge_starter/apps/desktop/web/package.json) 声明 `"packageManager": "pnpm@12.6.0"`。
  2. 执行 `pnpm --dir apps/desktop/web install` 同步更新 [pnpm-lock.yaml](file:///Users/wuzhao/Program/Github/lyraforge_starter/apps/desktop/web/pnpm-lock.yaml) 中的 `packageManagerDependencies` 段，并通过 `pnpm --dir apps/desktop/web install --frozen-lockfile` 验证严格锁文件一致性。
  3. 在 [.github/workflows/ci.yml](file:///Users/wuzhao/Program/Github/lyraforge_starter/.github/workflows/ci.yml) 的 `test` 与 `package-windows` 作业中添加 `with: package_json_file: apps/desktop/web/package.json`；在 `package-windows` 中将构建产物校验改为 `if (-not (Test-Path -LiteralPath "dist/LyraForge/LyraForge.exe")) { Write-Error ...; exit 1 }`。
- **远端验证说明**：当前工作区所有改动保留在本地待审阅、**尚未推送至 `origin/main`**，因此 GitHub Actions 远端全绿结果将在推送后触发验证。

### FIX-002：AI API Key 存储、日志脱敏与备份/分享包隔离（P0）

- **安全隐患复核**：原实现允许将 `llm_api_key` 直接写入 SQLite `settings` 表；完整曲库备份直接拷贝 `library.db`，一旦导出或共享数据库文件即产生明文密钥泄漏风险；异常路径亦直接拼接底层错误字符串。
- **修复内容**：
  1. 新增跨平台凭据模块 [secrets.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/secrets.py) 与隔离的 Windows 后端 [secrets_win32.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/secrets_win32.py)：
     - 支持环境变量最高优先级覆写（`LYRAFORGE_LLM_API_KEY`）。
     - macOS 使用 `/usr/bin/security -i` 通过标准输入传入十六进制编码（`-X <hex>`），避免进程参数列表（`ps`）暴露明文凭据；Windows 使用隔离的 `advapi32.dll` (`CredReadW`/`CredWriteW`/`CredDeleteW`)；无系统密钥环时回落至 `0o600` 权限的 `.lyraforge.secrets.json`。
     - 提供 `is_sensitive_key()` 与 `redact_secret()` 对异常信息及 `Bearer ...` 令牌统一脱敏。
  2. 在 [store.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/library/store.py) 中加入启动自动迁移 `_migrate_legacy_plaintext_secrets()`：将历史 SQLite `settings` 表内所有敏感字段迁移至 `SecretStore` 后删除明文行；`set_setting()` 对敏感键拦截写入系统凭据库；`get_settings()` 仅返回脱敏后的 `"llm_api_key_configured": bool`。
  3. 在 [packaging.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/library/packaging.py) 导出完整备份 `export_backup_zip()` 时强制清洗副本 SQLite `settings` 表中的敏感键并排除 `.lyraforge.secrets.json` / `*.secrets.json`；`.lyrapack` 分享包亦仅打包编曲元数据而不含系统设置或秘钥。
  4. 更新 [llm.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/agent/llm.py)、[orchestrator.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/agent/orchestrator.py) 与 [App.vue](file:///Users/wuzhao/Program/Github/lyraforge_starter/apps/desktop/web/src/App.vue)（保存 Key 后清空明文输入框并展示“已安全保存”状态）。
- **自动化测试**：
  - [test_layering.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/tests/unit/test_layering.py)：`test_secrets_cross_platform_has_no_win32_imports` 确保跨平台代码不直接引入 Windows `ctypes`。
  - [test_secrets_and_security.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/tests/unit/test_secrets_and_security.py)：`test_secret_backends_env_precedence_and_redaction`、`test_library_secrets_excluded_from_sqlite_api_backup_and_lyrapack`。

### FIX-003：Windows 自动演奏按键释放状态一致性（P1）

- **问题复核**：[driver.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/playback/windows/driver.py) 原实现在调用 `self._send(spec)` 发送松键事件前即调用 `self.pressed.discard(key_id)`，且旧版单元测试误断言在 `SendInput` 异常后 `driver.pressed == set()`，导致真实的卡键状态差异被测试掩盖。
- **修复内容**：
  1. 在 [win32_types.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/playback/windows/win32_types.py) 使用 `ctypes.WinDLL("user32", use_last_error=True)`，并在 `sent != 1` 时上报 `ctypes.get_last_error()`。
  2. 在 `WindowsKeyboardDriver` 新增 `max_release_retries: int = 2` 与 `_send_release_with_retry()`；`key_up()` 仅在确认松键 `SendInput` 发送成功后才执行 `self.pressed.discard(key_id)`；若最终仍失败，按键留在 `self.pressed` 中以便后续再次 `release_all()` 恢复。
- **自动化测试**：[test_windows_playback.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/tests/unit/test_windows_playback.py) 中的 `test_windows_keyboard_driver_release_all_attempts_every_key_on_error` 与 `test_windows_keyboard_driver_transient_key_up_retry_recovers`（全量 Mock 验证；真实 Windows `SendInput` 需真机测）。

### FIX-004：备份恢复分阶段校验与故障回滚（P1）

- **问题复核**：原 `restore_backup_zip()` 解压校验不充分且直接清理写入目标数据目录，若备份损坏、版本不兼容或拷贝中断，可能导致用户现存曲库永久丢失。
- **修复内容**：在 [packaging.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/library/packaging.py) 重构 `restore_backup_zip()`：
  1. 先于独立临时 `stage_root` 解压校验 ZIP（防路径穿越、软链、ZIP 炸弹），校验 `backup_manifest.json` (`1 <= schema_version <= SCHEMA_VERSION`)。
  2. 调用 `_verify_sqlite_backup()` 执行 `PRAGMA integrity_check == [("ok",)]`、核心表存在检查与 `MAX(version) <= SCHEMA_VERSION` 校验。
  3. 在暂存目录内验证迁移并执行 `PRAGMA wal_checkpoint(TRUNCATE)` 与 `journal_mode=DELETE` 归并 sidecar。
  4. 将目标目录现有内容（保留 `.lyraforge.secrets.json`）备份至兄弟目录 `.rollback-*`；换入后复验恢复后的 `LibraryStore`，任意异常（含模拟磁盘写入 `OSError`）自动清空失败现场并将 `.rollback-*` 完整恢复。
- **自动化测试**：[test_lyrapack_and_m5.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/tests/unit/test_lyrapack_and_m5.py) 新增 `test_restore_backup_rejects_corrupt_incompatible_and_rolls_back_on_error`。

### FIX-005：外网下载安全性与防 DNS 重绑定加固（P1）

- **问题复核**：原 `validate_public_http_url()` 在建立 TCP 连接之前通过系统 `getaddrinfo` 校验公网 IP，但真实连接交给默认 `urllib` 完成，存在 DNS Rebinding TOCTOU 窗口；且未拦截 IPv4-mapped IPv6/6to4/CGNAT 地址、内嵌凭据 URL、过深重定向与超大慢速响应超时流。
- **修复内容**：在 [url.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/sources/url.py) 实现：
  1. `resolve_public_http_url()`：拒绝带 `username/password` URL，拆解 IPv4-mapped IPv6 (`ipv4_mapped`) / `sixtofour` 真实地址，并以 `ip.is_global` 严格拒绝环回、私网、链路本地与 CGNAT (`100.64.0.0/10`)，返回 `(parsed, pinned_ip)`。
  2. 自定义 `_PinnedHTTPConnection` / `_PinnedHTTPSConnection` 强制直连已校验 `pinned_ip`，同时在请求中完整保留原始 HTTP `Host` 头与 TLS SNI `server_hostname`。
  3. `_SafeRedirectHandler` 对每次重定向上限 (`max_redirects=5`) 及目标 URL 重新解析固定公网 IP；下载循环内实时强制检查 `max_duration_s=30.0` 与字节上限，失败时无临时写入残留。
- **自动化测试**：[test_secrets_and_security.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/tests/unit/test_secrets_and_security.py) `test_url_dns_pinning_redirect_caps_and_cleanup`。

### FIX-006：合法开放曲库在线检索与音频自动回退转谱（P2）

- **问题复核**：此前无 `allow_network` 在线搜歌路径时，自然语言查询本地未命中只能直接返回 `not_found`。
- **修复内容**：
  1. 新增 [online.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/sources/online.py)：实现确定性候选排序 `rank_candidates()`（本地曲库 > 本地目录 > 外部来源；MIDI 优先于音频；显式开放许可优先；标题/作者匹配度排序）与 `OpenMusicCatalogSourceAdapter`（检索 Internet Archive CC0 / Public Domain / Creative Commons 音频及数据条目，复用 DNS 固定与 2 MB JSON 安全读取上限）。
  2. 更新 [orchestrator.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/src/lyraforge/agent/orchestrator.py)：本地无匹配且 `allow_network=False` 时显式返回 `status="needs_confirmation"`；用户授权 `allow_network=True` 后执行开放曲库检索，若首选条目为音频则自动下载并运行 `builtin-mono` 转谱 → 原琴编曲 → 低分对比优化 → 离线试听。
  3. 更新 [App.vue](file:///Users/wuzhao/Program/Github/lyraforge_starter/apps/desktop/web/src/App.vue) UI 文案提示该联网授权开关涵盖开放曲库检索与外部直链下载。
- **自动化测试**：[test_agent_and_sources.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/tests/unit/test_agent_and_sources.py) `test_agent_orchestrator_end_to_end_and_optimization` 与 `test_online_catalog_ranking_search_and_audio_fallback`。

### FIX-007：转录引擎探测与可复现基准评测（P2）

- **实现内容**：新增 [scripts/eval_transcribers.py](file:///Users/wuzhao/Program/Github/lyraforge_starter/scripts/eval_transcribers.py)，自动探测 `ffmpeg`、`builtin-mono`、`basic-pitch`、`dettato` 可用性，并使用 22.05 kHz 多谐波合成音频（`solo_melody`、`polyphonic_piano_chords`、`dense_multi_register`）实测转录到风物之诗琴编曲全流程指标（耗时、音符召回率/精确率/F1、可演奏比例、综合评分）。
- **本机真实评测结果**（`uv run python scripts/eval_transcribers.py`）：
  - 环境探测：`ffmpeg_available=false`、`builtin-mono.available=true`、`basic-pitch.available=false`、`dettato.available=false`
  - `builtin-mono` 实测数据：

| 测试集 | 参考音符数 | 转录原始/清理音符 | F1 (50ms 容差精确音高) | 风物之诗琴 `playable_ratio` | 综合分 | 耗时 (ms) | 诚实结论 |
|---|---:|---:|---:|---:|---:|---:|---|
| `solo_melody` | 8 | 8 / 8 | **1.0000** (P=1.0, R=1.0) | 1.0 | 100.0 | 167.16 | 单音纯旋律表现优秀 |
| `polyphonic_piano_chords` | 12 | 4 / 4 | **0.0000** (P=0.0, R=0.0) | 1.0 | 100.0 | 142.91 | 单音 YIN 无法解算同时三音和弦 |
| `dense_multi_register` | 16 | 8 / 8 | **0.3333** (P=0.5, R=0.25) | 1.0 | 100.0 | 151.37 | 跨八度双声部仅能追踪主导单声线 |

### FIX-008 & FIX-009：文档对齐与真实状态呈现

- 更新 [AGENTS.md](file:///Users/wuzhao/Program/Github/lyraforge_starter/AGENTS.md)，废除过期 `M0 only` 初始化任务，固化 GPL-3.0、凭据安全边界与 `make check` 验收要求。
- 更新 [PROGRESS.md](file:///Users/wuzhao/Program/Github/lyraforge_starter/docs/PROGRESS.md)（严格采用五态分类矩阵）及 [README.md](file:///Users/wuzhao/Program/Github/lyraforge_starter/README.md)（补充 `pnpm@12.6.0`、安全存储架构、Internet Archive 搜索说明及 `eval_transcribers.py` 边界）。

---

## 三、完整回归验证结果（全部基于修改后真实运行）

> 全套最终门禁命令 `pnpm --dir apps/desktop/web install --frozen-lockfile && make check` 于所有源码及文档落盘完成后再次执行验证，确保零跳过、零报错：

1. **前端依赖锁定校验**：`pnpm --dir apps/desktop/web install --frozen-lockfile` → `pnpm v12.6.0` 一致通过。
2. **Python 静态检查**：`uv run ruff check .` → `All checks passed!`
3. **Python 单元、分层门禁与集成测试**：`uv run pytest --cov=lyraforge --cov-report=term-missing --cov-fail-under=80` → **111 passed, 1 warning**（`StarletteDeprecationWarning`），总覆盖率 **90.17%**（4692 语句 / 1114 分支）。
4. **Vue 3 前端测试与构建**：
   - `vitest run` → **Test Files 3 passed (3), Tests 5 passed (5)**
   - `vue-tsc --noEmit && vite build` → 构建成功。
5. **CLI 端到端冒烟**：`make smoke` → 退出码 `0`（DryRun 驱动完成 48 个动作、0 残留按键）。

---

## 四、遗留风险与 Windows 真机验收清单

1. **必须先推送至 GitHub 验证远端 CI**：本次本地已修复 `.github/workflows/ci.yml` 与锁文件同步，但 GitHub Actions 在推送前仍停留于失败记录 `44977619933`。推送后应核查 `test (macos-latest)`、`test (windows-latest)` 与 `package-windows` 下载产物内是否含可启动的 `dist/LyraForge/LyraForge.exe`。
2. **Windows 10/11 真机验收必查项（当前未在本机执行）**：
   - [ ] 普通非管理员用户启动 `dist/LyraForge/LyraForge.exe`，确认内置 WebView2 / FastAPI 服务正常拉起。
   - [ ] 测试 UI/API 配置与读取 LLM API Key，确认 `secrets_win32.py` 写入 **Windows 凭据管理器** 且重启后可复用、导出的 `backup.zip` 无密钥明文。
   - [ ] 在《原神》大世界**自由演奏界面**对 `genshin.windsong_lyre.v1` 与 `genshin.floral_zither.v1` 进行 21 键实音逐键校准，确认无误后再更新 `calibration.status`（当前为 `unverified`）。
   - [ ] 真实触发播放中途 `Alt+Tab` 切窗、`Stop` 与 `ESC` 急停，确认前景窗口守卫停止调度且无任何按键粘连。
   - [ ] 在目标机按需配置 `ffmpeg` 与 `LYRAFORGE_BASIC_PITCH_PYTHON`/`LYRAFORGE_DETTATO_PYTHON` 后运行 `uv run python scripts/eval_transcribers.py`，验证多音轨实际曲目 F1 指标。

---

## 五、下一阶段建议

1. 推送本次修复分支或提交至 GitHub，确认 `macos-latest`、`windows-latest` 与 `package-windows` CI 全绿，并试运行下载的便携 `.exe`。
2. 在 Windows 实体机完成一次完整实音校准并将经核实的按键映射结果与 `calibration.status` 回填乐器 JSON。
3. 如面向大众用户提升复杂混音识别效果，可补充一键检测脚本或可选插件向导指引用户在本机独立环境安装 `ffmpeg` 与 Apache-2.0 授权的 `basic-pitch`。
