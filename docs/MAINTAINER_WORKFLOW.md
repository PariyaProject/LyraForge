# LyraForge 长期自主维护工作流（Maintainer Workflow）

> 本手册配合根目录 [AGENTS.md](../AGENTS.md) 使用，固化跨会话的侦测、开发、PR、CI 诊断、合并与安全升级规范，减少人工重复干预。

---

## 1. 会话启动例行检查

每次开始开发或维护会话时，按顺序确认本机与 GitHub 真实状态（切勿依赖缓存或记忆）：

```bash
git status --short --branch
git fetch origin --prune
git rev-parse HEAD
git rev-parse origin/main
git log --oneline --decorate -8
gh auth status
gh repo view PariyaProject/LyraForge --json defaultBranchRef,url
gh pr list --repo PariyaProject/LyraForge --state all --limit 10
uv run python scripts/check_ci.py --sha origin/main
```

- 如 `gh auth status` 未登录或权限不足，**一次性提示用户运行 `gh auth login`**（`repo` + `workflow` scope），严禁读取、打印或搬运用户的个人 OAuth Token。

---

## 2. 任务优先级与规划原则

1. **P0 — 安全 / 数据完整性 / 许可证合规**：密钥泄漏、SSRF、备份损坏回滚、权限门禁失效、GPL-3.0 兼容冲突。
2. **P0 — CI / 构建可用性**：GitHub Actions `macos-latest`、`windows-latest` 与 `package-windows` 失败诊断与修复。
3. **P1 — 核心用户可用性**：桌面 UI、本地库导入导出、MCP `stdio` 工具链与真实文档对齐。
4. **P1/P2 — 音乐识别与编曲质量**：转录准确率与适配度分离指标、主旋律与和弦编曲效果、回归用例。
5. **P2 — 增量功能扩展**。

---

## 3. 常规开发闭环（无需每步停下等待确认）

在预授权的常规开发范围内（`fix/...` / `feat/...` 分支修改、测试、提交、推分支、开 PR、修 CI），自主连续推进：

1. **保护工作区**：切新分支前先看 `git status --short`，不得覆盖或丢弃用户未提交的改动。
2. **垂直切片实现与测试**：严格保持 `music_core` 无头分层、Windows 驱动与 `secrets_win32` 隔离，同步更新单元/集成测试与相关文档（所有文档使用仓库内相对路径，禁止 `file:///` 本地绝对路径）。
3. **本地全量门禁**：
   ```bash
   pnpm --dir apps/desktop/web install --frozen-lockfile && make check
   ```
   若修改转录器/评分/测试基准逻辑，同步运行：
   ```bash
   uv run python scripts/eval_transcribers.py
   ```
4. **清理临时文件并提交推送**：核查 `git status --short` 无临时草稿、无密钥、无 `.DS_Store` 或打包残留后提交并推送：
   ```bash
   git push -u origin <branch>
   gh pr create --base main --head <branch> --title "..." --body "..."
   ```
5. **追踪真实远端 CI（最多 3 轮自愈）**：
   ```bash
   uv run python scripts/check_ci.py --sha HEAD --watch
   ```
   - 若任意 Job 失败，分析 `failed_log_excerpt`（或 `gh run view <run_id> --log-failed`），定位根因、修复、追加提交并重新推送监控。
   - **最多连续自动修复 3 轮**；若 3 轮后仍受平台、Runner 环境或外部权限阻塞，停止盲试并在 PR/Issue 与 [PROGRESS.md](PROGRESS.md) 记录完整可复现诊断与日志链接。
6. **授权合并与 merge 后回归确认**：
   - 检查分支保护规则（`gh api repos/PariyaProject/LyraForge/branches/main/protection`）与所有 CI 状态。
   - 仅在 PR CI 全绿、符合保护规则且属于用户已授权范围时执行合并（默认 `--squash --delete-branch`），切禁 `--admin` 绕过保护或强推 `main`。
   - 合并后切回 `main` 拉取最新提交，**再次核查合并后 `main` 的真实 CI**：
     ```bash
     git checkout main && git pull origin main
     uv run python scripts/check_ci.py --sha HEAD --watch
     ```
7. **记录真相并继续**：在 [PROGRESS.md](PROGRESS.md) 或报告中记录真实 commit SHA、PR URL、CI Run URL 与实测结果，随后无缝选择下一优先级任务。

---

## 4. 必须请求用户确认的高风险边界

出现以下任意情形时**立即暂停相关操作并请求明确确认**：

- 变更开源许可证（GPL-3.0 为最终确认规则）或疑似引入不兼容版权代码/音频资产；
- 向仓库、Issue、日志或分享包写入敏感信息或真实用户凭据；
- 删除用户数据或非临时性的正式项目文档/测试资产；
- 强推受保护分支或关闭仓库分支保护/CI 门禁；
- 触发产生费用或消耗额度的外部收费 API、云构建额度或大模型自动循环；
- 调用真实 Windows《原神》自动按键演奏或发布正式稳定版（Release / Tag）。

---

## 5. 可选无人值守自动化边界

单个 `/goal` 会话在模型额度耗尽、会话结束或开发机休眠后不会永久后台运行。如未来需要真正的跨天无人值守运维（例如定期巡检失败 CI 或 Open Issues）：

- 须经用户单独批准后再安装 GitHub Scheduled Workflow 或本机定时任务（`launchd`/`cron`）；
- 必须明确定义：**认证来源**（`GITHUB_TOKEN` 最小权限，严禁放个人 OAuth Session 至公开 CI）、**安全边界**（仅诊断或开草稿 PR，不自动合并/不改许可证/不发包）、**预算与重试上限**（单次成本与连续失败熔断）及**随时可暂停/关闭的开关**。

---

## 6. Alpha / Stable 发布前门禁与断点续做交接规范

- **Alpha Pre-Flight Gate**：合并或标记 Alpha 预发行前，必须同时满足 `make check` 全绿、Chrome CDP 无交互报错/溢出、双平台 CI（含 Windows `LyraForge.exe --self-check`）全绿，且 `README.md` / [PROGRESS.md](PROGRESS.md) 如实标明真机未验证项。
- **Stable Release Gate**：公开标称稳定版前，除全部自动 CI 外，还必须在 Windows 10/11 实体机按 [TEST_REPORT.md](TEST_REPORT.md) §5 完成真机《原神》21 键校准、切窗/ESC 松键与独立多音识别联调，并经项目所有者明确批准后方可打 Tag / 发 Release。
- **断点交接（Resumable Handoff）**：跨会话持续推进时，[PROGRESS.md](PROGRESS.md) 仅写入真实已观测提交 SHA、PR/CI URL 与命令原始结果；严禁根据记忆补全未运行检查项。
