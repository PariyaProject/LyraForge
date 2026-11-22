# LyraForge 第四轮 UI/UX 审查与实机交互验证报告

> **测试方式**：实时 Python FastAPI (`127.0.0.1`) + 真实编译前端产物 (`apps/desktop/web/dist`) + 无头 Google Chrome DevTools Protocol (CDP) 全视图渲染与 DOM 点击验证。  
> **前端门禁**：`vue-tsc --noEmit && vite build` 零错误（`833ms`，产物 `158.80 kB` JS / `20.52 kB` CSS）；`vitest run` **4/4 文件 · 6/6 用例全过**。

---

## 1. 本轮发现并修复的 UI/UX 问题

1. **修复 Windows 真机被误判禁用的平台字符串 Bug (`PlaybackView.vue`)**：
   - **根因**：此前前端检查 `platform !== 'windows'`，但 Python `sys.platform` 在 Windows 返回 `'win32'`，会导致 Windows 实体机上的 `Windows 原神窗口 SendInput` 下拉选项长期被禁用。
   - **修复**：改为绑定后端能力探测字段 `:disabled="!store.health.value?.windows_playback_available"`。
2. **修复“换页即断音”的全局试听连续性与壳层布局滚动问题 (`App.vue`, `global.css`)**：
   - **第一轮 Chrome 截屏发现**：采用 `min-block-size: 100dvh` 时，首页/曲库/工作室较长内容会把 `<footer class="studio-transport">` 推到首屏之下，侧栏底部 `GNU GPL-3.0` 也可能被裁切。
   - **二次修复与复测验证**：改为桌面端 `block-size: 100dvh; overflow: hidden` 固定壳层（`main` 与 `rail-nav` 各自平滑滚动；≤680 px 自动回落纵向流式 + `sticky` 传输栏），并把 `ToastStack` 抬高至 `inset-block-end: 66px` 避免遮挡底部试听按钮。
3. **补齐关键工作流闭环控件**：
   - **首页 (`HomeView.vue`)**：增加紧凑「首次使用 3 步指南 & 能力范围」卡片，直观标明纯 Python 单音边界与 Dry-Run 现状。
   - **编曲工作室 (`StudioView.vue`)**：头部增加一键「试听当前版本」，无需离页即可直接校验当前 Piano Roll 改动音频。
   - **本地曲库 (`LibraryView.vue`)**：新增「从全库备份恢复 (`.zip`)」上传与明确覆盖确认按钮，对应后端安全阶段校验与自动回滚机制。
   - **试听与演奏 (`PlaybackView.vue`) & 底部传输栏 (`App.vue`)**：新增「暂停演奏 / 继续演奏 / 紧急停止」全局控制联动。

---

## 2. 跨分辨率、High-DPI 与真实交互 CDP 验证结果

### 2.1 多分辨率与 `@2x` High-DPI 视口统计（14 / 14 全部零溢出、0 控制台报错）

| 视图 | 采样规格 | 测得 `docScrollW / winInnerW` | `mainScrollW / mainClientW` | 底部全局传输栏可见 (`hasFooterTransport`) | 控制台报错 |
|---|---|---|---|---|---|
| 首页 (`home`) | `1440×900@1x`, `1440×900@2x`, `1024×720@1x`, `1920×1080@1x` | 精确相等（0px 横向溢出） | 精确相等 | `true` | `0` |
| 本地曲库 (`library`) | `1440×900@1x`, `1024×720@1x` | 精确相等（0px 横向溢出） | 精确相等 | `true` | `0` |
| AI 转谱 (`transcribe`) | `1440×900@1x` | 精确相等（0px 横向溢出） | 精确相等 | `true` | `0` |
| 编曲工作室 (`studio`) | `1440×900@1x`, `1440×900@2x`, `1024×720@1x`, `1920×1080@1x` | 精确相等（0px 横向溢出） | 精确相等 | `true` | `0` |
| 试听与演奏 (`playback`) | `1440×900@1x`, `1024×720@1x` | 精确相等（0px 横向溢出） | 精确相等 | `true` | `0` |
| 设置与模型 (`settings`) | `1440×900@1x` | 精确相等（0px 横向溢出） | 精确相等 | `true` | `0` |

### 2.2 Chrome 真实点击交互端到端测试

| 交互链路 | 验证步骤 | 实测结果 |
|---|---|---|
| **A/B 编曲对比** | Studio 视图点击 `生成 A/B 对比版本` | 成功等待并渲染出 `A/B 编曲对比结果` 与胜出版本徽标 (`true`) |
| **Piano Roll 编辑与另存** | 点击选中音符 `.pr-note` → 点击 `+50ms` → 点击 `保存为新版本` | 版本下拉选项数由 `2` 实际递增至 `3` (`version_saved: true`) |
| **全局 WAV 跨视图连续试听** | 点击 `试听当前版本` → 确认 `footer audio[src^="blob:"]` 加载 → 点击切入 `本地曲库` | 切换视图后 `<audio>` `blob:` 音源继续挂在全局传输栏无销毁 (`audio_persists: true`) |
| **两段授权 + 暂停/继续/急停** | 进入 `试听与演奏` → `1. 准备演奏` → `2. 确认授权开始` → `暂停演奏` → `继续演奏` → `紧急停止` | 全状态转换正常可见，0 异常报错 (`console_errors: []`) |

---

## 3. 本轮刷新后的实机渲染图集（`1440×900@1x`）

- [首页（含 3 步引导与固定底部全局传输栏）](assets/ui/home.png)
- [本地曲库（含多版本切换、.lyrapack 与全库恢复）](assets/ui/library.png)
- [AI 音乐转谱流水线与离线 Agent](assets/ui/transcribe.png)
- [编曲工作室与 DAW Piano Roll](assets/ui/studio.png)
- [试听、导出与两段授权演奏控制台](assets/ui/playback.png)
- [设置、MCP 无密接入与引擎诊断](assets/ui/settings.png)
