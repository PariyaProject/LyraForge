# LyraForge AI 集成与无需 API Key 的三层架构说明

LyraForge 明确不将“单独购买 OpenAI / Anthropic / Gemini API Key”设为使用门槛，而是采用清晰的三层 AI 架构：

1. **第一层：完全离线、零模型、零 API Key（核心默认）**
   - 本地导入 MIDI/音频、内置单音转谱（YIN）、《原神》风物之诗琴/镜花之琴编曲、主旋律保留与和弦琶音、Piano Roll 编辑、离线 WAV 试听、SQLite 曲库与 `.lyrapack` 导出**全部 100% 离线免费可用**。
   - `RuleBasedLLMProvider` 是确定性**离线规则命令解析器**（正则与关键词匹配），并非大模型生成。

2. **第二层：MCP Server + Client Skill 接入用户自有已登录客户端（推荐 AI 工作流）**
   - LyraForge 提供零外部依赖的 `stdio` JSON-RPC MCP Server（启动命令：`uv run lyraforge mcp`），向用户已有的 Claude Code、Codex CLI、Antigravity 等客户端暴露 10 个类型化工具：
     - `search_music`、`import_media`、`transcribe`、`arrange`、`evaluate`、`preview`、`save_to_library`、`export_score`、`get_task_status`、`play_in_game`（强制交互确认守卫，绝不直接向操作系统注入按键）。
   - 该模式下模型推理和鉴权**完全保留在用户自己登录的官方客户端会话内部**；LyraForge **绝不读取、复制、转发、中继用户的 OAuth 凭据或订阅会话 Token**。

3. **第三层：可选高级 HTTP LLM 接口与谨慎边界说明**
   - 如用户自有 OpenAI-compatible 兼容端点（例如本地 Ollama `http://127.0.0.1:11434/v1` 或用户自行输入的 API Key），可在桌面“设置与默认偏好”中手动开启。API Key 通过 OS Keychain / Windows Credential Manager / `0o600` 本地受限文件或环境变量存储，不默认展示强制配置弹窗。

---

## 各客户端接入与条款合规矩阵（诚实标注）

| 客户端 / 协议 | 推荐接入模式 | 本地实测与可用状态 | 账号条款与安全边界（严禁逾越） |
|---|---|---|---|
| **LyraForge `stdio` MCP (`lyraforge mcp`)** | 标准 MCP Server（JSON-RPC over stdio） | **已实现并通过真实子进程 `stdio` 全链路测试** | 完全运行于本地库与用户文件；`play_in_game` 在 MCP 端始终拒绝自动按键 |
| **Claude Code (`claude`)** | 使用官方 `claude mcp add` 加载本地 MCP + [SKILL.md](../integrations/claude-code/SKILL.md) | 本机已安装 `claude 2.1.267`，已核验 `claude mcp` 子命令语法与配置格式 | 遵守 Anthropic 消费端条款：不得从本机读取/复用 Claude Pro/Max OAuth 令牌绕过官方客户端建立第三方模型 Adapter；若要脱离 Claude 客户端在外部软件调大模型，须使用单独 Anthropic API Key |
| **Codex CLI (`codex`)** | 在 `config.toml` 配置 `[mcp_servers.lyraforge]` + [SKILL.md](../integrations/codex/SKILL.md) | **配置与 Skill 已提供；本机未安装 `codex` CLI，实机连通待安装验证** | 不擅自提取 ChatGPT OAuth 凭据或将用户订阅静默切回按量 API 计费；须在官方 Codex CLI 会话内启用 MCP |
| **Antigravity IDE / CLI (`agy`)** | 配置 [mcp_config.example.json](../integrations/antigravity/mcp_config.example.json) + [SKILL.md](../integrations/antigravity/SKILL.md) | **配置与 Skill 已提供；当前环境未安装独立 `agy` CLI，正式软件运行时绝不强依赖 Antigravity CLI** | Antigravity 仅作为开发期/MCP 宿主工具选项，不绑定进发行版客户端；若实验无头 SDK 需遵循对应条款与用户明确计费授权 |

---

## 快速配置示例

### Claude Code

```bash
# 在项目目录中注册项目级或用户级 MCP Server（二选一）
claude mcp add lyraforge -- uv run --directory /ABSOLUTE/PATH/TO/LyraForge lyraforge mcp
```

也可直接将 [mcp.example.json](../integrations/claude-code/mcp.example.json) 中的配置加入项目的 `.mcp.json`（注意将路径改为你本机的 LyraForge 仓库路径），并把 [SKILL.md](../integrations/claude-code/SKILL.md) 放入 `~/.claude/skills/lyraforge-music-workbench/SKILL.md`。

### Codex CLI

将 [config.toml.example](../integrations/codex/config.toml.example) 内容追加至 `~/.codex/config.toml`，并将 [SKILL.md](../integrations/codex/SKILL.md) 放入对应的 Codex Skills 目录。

### Antigravity

参考 [mcp_config.example.json](../integrations/antigravity/mcp_config.example.json) 添加 MCP Server，并安装 [SKILL.md](../integrations/antigravity/SKILL.md)。
