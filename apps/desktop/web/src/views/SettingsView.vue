<script setup lang="ts">
import { ref } from "vue";
import StudioIcon from "../components/StudioIcon.vue";
import type { LyraStore } from "../composables/useLyraStore";

const props = defineProps<{
  store: LyraStore;
}>();

const activeMcpTab = ref<"claude" | "codex" | "antigravity">("claude");

function installOf(toolId: string) {
  return props.store.toolInstalls.value[toolId];
}

const MCP_SNIPPETS: Record<"claude" | "codex" | "antigravity", { title: string; code: string }> = {
  claude: {
    title: "Claude Code (.mcp.json / integrations/claude-code)",
    code: `{
  "mcpServers": {
    "lyraforge": {
      "command": "uv",
      "args": ["run", "lyraforge", "mcp"]
    }
  }
}`,
  },
  codex: {
    title: "Codex CLI (~/.codex/config.toml / integrations/codex)",
    code: `[mcp_servers.lyraforge]
command = "uv"
args = ["run", "lyraforge", "mcp"]`,
  },
  antigravity: {
    title: "Antigravity / 通用 MCP Client (integrations/antigravity)",
    code: `# 直接复刻仓库内置 Skill 并挂接本地只读+编曲 MCP：
uv run lyraforge mcp`,
  },
};

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    props.store.pushToast("ok", "已复制配置片段到剪贴板");
  } catch {
    props.store.pushToast("info", "当前环境不支持自动剪贴板写入，请手动选中复制");
  }
}
</script>

<template>
  <section class="view-stack" aria-label="系统设置与 AI 模型集成">
    <header class="view-header">
      <div>
        <h1 class="view-title">设置、MCP 接入与转谱引擎诊断</h1>
        <p class="view-subtitle">
          零外部 API Key 本地闭环、用户自有 AI 客户端 MCP 桥接、可选 HTTP 模型与密钥安全保管。
        </p>
      </div>
    </header>

    <div class="card">
      <div class="card-title-row">
        <h2>本地 MCP & AI 客户端免密钥接入（Layer 1 + Layer 2）</h2>
        <span class="pill pill-ok">无需重复支付 API Key</span>
      </div>
      <p class="muted" style="margin: 0">
        桌面端默认内置确定性规则引擎 <code>RuleBasedLLMProvider</code>，完全离线可用；若你已订阅 Claude Code、Codex 或 Antigravity，可直接挂载本地 <code>lyraforge mcp</code>，让你的客户端安全调用曲库、转谱、编曲与 Dry-Run（真机 <code>play_in_game</code> 始终在 MCP 中保持门控）。
      </p>

      <div class="button-row">
        <div class="segmented" role="tablist" aria-label="AI 客户端配置方式">
          <button
            type="button"
            role="tab"
            :aria-selected="activeMcpTab === 'claude'"
            :class="{ active: activeMcpTab === 'claude' }"
            @click="activeMcpTab = 'claude'"
          >
            Claude Code
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="activeMcpTab === 'codex'"
            :class="{ active: activeMcpTab === 'codex' }"
            @click="activeMcpTab = 'codex'"
          >
            Codex CLI
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="activeMcpTab === 'antigravity'"
            :class="{ active: activeMcpTab === 'antigravity' }"
            @click="activeMcpTab = 'antigravity'"
          >
            Antigravity
          </button>
        </div>

        <button
          class="secondary"
          type="button"
          @click="copyText(MCP_SNIPPETS[activeMcpTab].code)"
        >
          <StudioIcon name="copy" />
          复制配置
        </button>
      </div>

      <div class="field">
        <span class="muted">{{ MCP_SNIPPETS[activeMcpTab].title }}</span>
        <pre><code>{{ MCP_SNIPPETS[activeMcpTab].code }}</code></pre>
      </div>
    </div>

    <div class="split-2">
      <div class="card">
        <div class="card-title-row">
          <h2>外部工具与转谱引擎（可一键安装）</h2>
          <span class="pill">应用内下载 · 不改系统环境</span>
        </div>
        <p class="muted" style="margin-block: 0 var(--space-2)">
          工具安装到 <code>{{ store.toolsDir.value || "…" }}</code>，启动时自动注入子进程环境；也可先用系统已安装的版本。
        </p>
        <div class="view-stack" style="gap: 8px">
          <div v-for="tool in store.tools.value" :key="tool.id" class="track-card">
            <div class="card-title-row">
              <strong>{{ tool.display_name }}</strong>
              <span class="pill" :class="tool.installed ? 'pill-ok' : 'pill-warn'">
                {{
                  tool.installed
                    ? tool.source === "managed"
                      ? "已安装（应用内）"
                      : "已安装（系统）"
                    : "未安装"
                }}
              </span>
            </div>
            <div class="muted">{{ tool.description }}</div>
            <div class="muted">
              许可：<code>{{ tool.license }}</code>
              <template v-if="tool.version"> · 版本 <code>{{ tool.version }}</code></template>
              <template v-if="tool.download_mb"> · 约 {{ tool.download_mb }} MB</template>
            </div>
            <div class="button-row">
              <button
                v-if="!tool.installed"
                class="secondary"
                type="button"
                :disabled="store.toolBusy.value !== null"
                @click="store.handleInstallTool(tool.id)"
              >
                <StudioIcon name="download" />
                安装 {{ tool.display_name }}
              </button>
              <span v-else class="muted">路径：<code>{{ tool.path }}</code></span>
            </div>
            <div v-if="installOf(tool.id)" class="muted">
              {{ installOf(tool.id)?.message }}
              （{{ Math.round((installOf(tool.id)?.progress ?? 0) * 100) }}%）
              <span v-if="installOf(tool.id)?.error">{{ installOf(tool.id)?.error }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <h2>应用设置与安全凭据（Layer 3 可选）</h2>

        <div class="field">
          <label for="settings-default-style">默认编曲风格</label>
          <select id="settings-default-style" v-model="store.style.value">
            <option value="melody">melody（突出主旋律）</option>
            <option value="balanced">balanced（主旋律 + 和弦均衡）</option>
            <option value="rich">rich（丰满音区）</option>
          </select>
        </div>

        <div class="field">
          <label for="settings-allowed-titles">Windows 允许窗口标题白名单（逗号分隔）</label>
          <input
            id="settings-allowed-titles"
            v-model="store.allowedTitlesSetting.value"
            type="text"
          />
        </div>

        <details class="advanced-box">
          <summary>高级设置：可选 OpenAI 兼容 HTTP 模型接口</summary>
          <div class="view-stack" style="margin-block-start: var(--space-3); gap: var(--space-2)">
            <label class="checkbox-row">
              <input v-model="store.llmEnabledSetting.value" type="checkbox" />
              启用可选外部 LLM 意图规划（不启用时保持 100% 离线确定性规则引擎）
            </label>
            <div class="field">
              <label for="settings-llm-url">Base URL（例如 http://127.0.0.1:11434/v1 或服务端点）</label>
              <input
                id="settings-llm-url"
                v-model="store.llmBaseUrlSetting.value"
                type="url"
                placeholder="https://api.example.com/v1"
              />
            </div>
            <div class="field">
              <label for="settings-llm-model">模型名称</label>
              <input
                id="settings-llm-model"
                v-model="store.llmModelSetting.value"
                type="text"
                placeholder="例如：gpt-4o-mini / qwen2.5"
              />
            </div>
            <div class="field">
              <label for="settings-llm-key">
                API Key（仅写入 OS Keychain / 凭据库，绝不入 SQLite 或备份）
              </label>
              <input
                id="settings-llm-key"
                v-model="store.llmApiKeySetting.value"
                type="password"
                autocomplete="off"
                :placeholder="store.llmApiKeyConfigured.value ? '已安全保存（留空保持不变）' : '输入新密钥'"
              />
            </div>
            <div>
              <span
                class="pill"
                :class="store.llmApiKeyConfigured.value ? 'pill-ok' : ''"
              >
                {{ store.llmApiKeyConfigured.value ? "系统凭据库已保管密钥" : "未配置外部密钥" }}
              </span>
            </div>
          </div>
        </details>

        <div class="button-row">
          <button class="primary" type="button" @click="store.handleSaveSettings">
            <StudioIcon name="check" />
            保存设置
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
