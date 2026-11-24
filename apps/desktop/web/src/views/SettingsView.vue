<script setup lang="ts">
import { ref } from "vue";
import StudioIcon from "../components/StudioIcon.vue";
import type { LyraStore } from "../composables/useLyraStore";

const props = defineProps<{
  store: LyraStore;
}>();

type SettingsSectionId = "general" | "playback" | "hotkeys" | "toolchain" | "ai-mcp";

const activeCategory = ref<SettingsSectionId>("general");
const activeMcpTab = ref<"claude" | "codex" | "antigravity" | "deepseek">("claude");

const CATEGORIES: Array<{ id: SettingsSectionId; label: string }> = [
  { id: "general", label: "常规与编曲" },
  { id: "playback", label: "游戏演奏与窗口" },
  { id: "hotkeys", label: "全局热键" },
  { id: "toolchain", label: "转谱引擎与 GPU" },
  { id: "ai-mcp", label: "AI 与 MCP 集成" },
];

function scrollToSection(id: SettingsSectionId): void {
  activeCategory.value = id;
  if (typeof document !== "undefined") {
    document.getElementById(`settings-sec-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function installOf(toolId: string) {
  return props.store.toolInstalls.value[toolId];
}

function onDettatoDeviceChange(event: Event): void {
  void props.store.handleSetGpuDevice((event.target as HTMLSelectElement).value);
}

const MCP_SNIPPETS: Record<
  "claude" | "codex" | "antigravity" | "deepseek",
  { title: string; code: string }
> = {
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
    title: "Antigravity / MCP 客户端 (integrations/antigravity)",
    code: `# 复刻仓库内置 Skill 并挂接本地只读与编曲 MCP：
uv run lyraforge mcp`,
  },
  deepseek: {
    title: "DeepSeek / 通用 stdio MCP 客户端",
    code: `# 任意支持 stdio MCP 的本地 Agent Harness 均可使用：
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
  <section class="view-stack" aria-label="设置与外部工具">
    <header class="view-header">
      <div>
        <h1 class="view-title">设置</h1>
        <p class="view-subtitle">
          默认流程完全离线：转谱引擎、一键预设与本地曲库开箱即用；AI 与 MCP 接入均为可选高级选项。
        </p>
      </div>
    </header>

    <div class="settings-layout">
      <nav class="settings-nav" aria-label="设置分类">
        <button
          v-for="cat in CATEGORIES"
          :key="cat.id"
          type="button"
          class="settings-nav-btn"
          :class="{ active: activeCategory === cat.id }"
          @click="scrollToSection(cat.id)"
        >
          {{ cat.label }}
        </button>
      </nav>

      <div class="settings-content">
        <section id="settings-sec-general" class="settings-section">
          <div class="pane-header">
            <h2>常规与默认编曲</h2>
          </div>
          <div class="field" style="max-inline-size: 380px">
            <label for="settings-default-style">默认编曲风格</label>
            <select id="settings-default-style" v-model="store.style.value">
              <option value="melody">melody（突出主旋律）</option>
              <option value="balanced">balanced（主旋律 + 和弦均衡）</option>
              <option value="rich">rich（丰满音区）</option>
            </select>
          </div>
        </section>

        <section id="settings-sec-playback" class="settings-section">
          <div class="pane-header">
            <h2>游戏演奏与窗口白名单</h2>
          </div>
          <div class="field">
            <label for="settings-allowed-titles">Windows 允许窗口标题白名单（逗号分隔）</label>
            <input
              id="settings-allowed-titles"
              v-model="store.allowedTitlesSetting.value"
              type="text"
            />
          </div>
          <div class="field">
            <label for="settings-allowed-processes">
              Windows 游戏进程白名单（逗号分隔，默认 GenshinImpact.exe, YuanShen.exe）
            </label>
            <input
              id="settings-allowed-processes"
              v-model="store.allowedProcessesSetting.value"
              type="text"
            />
          </div>
          <div>
            <button class="primary" type="button" @click="store.handleSaveSettings">
              <StudioIcon name="check" :size="14" />
              保存设置
            </button>
          </div>
        </section>

        <section id="settings-sec-hotkeys" class="settings-section">
          <div class="pane-header">
            <h2>Windows 全局热键（默认未绑定）</h2>
            <span class="pill">{{ store.hotkeySupported.value ? "Windows 支持" : "仅 Windows 可用" }}</span>
          </div>
          <p class="muted" style="margin: 0; font-size: 12px">
            留空表示不绑定。输入形如 <code>Ctrl+Alt+F9</code>（必须包含 Ctrl/Alt/Shift/Win 修饰键），建议使用 F9 到 F12 避免与 21 键冲突。
          </p>
          <div class="hotkey-grid">
            <div v-for="action in store.hotkeyActions.value" :key="action.id" class="field">
              <label :for="`hotkey-${action.id}`">{{ action.label }}</label>
              <input
                :id="`hotkey-${action.id}`"
                v-model="store.hotkeyBindings.value[action.id]"
                type="text"
                placeholder="未绑定，例如 Ctrl+Alt+F9"
              />
              <span v-if="store.hotkeyErrors.value[action.id]" class="muted" style="font-size: 12px">
                {{ store.hotkeyErrors.value[action.id] }}
              </span>
            </div>
          </div>
          <div>
            <button class="secondary" type="button" @click="store.handleSaveHotkeys">
              <StudioIcon name="check" :size="14" />
              保存热键
            </button>
          </div>
        </section>

        <section id="settings-sec-toolchain" class="settings-section">
          <div class="pane-header">
            <h2>外部工具与转谱引擎</h2>
            <span class="pill">应用内独立安装目录</span>
          </div>
          <p class="muted" style="margin: 0; font-size: 12px">
            托管安装目录：<code>{{ store.toolsDir.value || "默认用户数据目录" }}</code>，启动时自动注入子进程环境。
          </p>

          <ul class="line-list">
            <li v-for="tool in store.tools.value" :key="tool.id" class="tool-row">
              <div class="tool-row-main">
                <div class="pane-header">
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
                <div class="muted" style="font-size: 12px">{{ tool.description }}</div>
                <div class="meta-row">
                  <code>{{ tool.license }}</code>
                  <span v-if="tool.version">版本 {{ tool.version }}</span>
                  <span v-if="tool.download_mb">约 {{ tool.download_mb }} MB</span>
                  <code v-if="tool.installed && tool.path">{{ tool.path }}</code>
                </div>
                <div v-if="installOf(tool.id)" class="muted" style="font-size: 12px">
                  {{ installOf(tool.id)?.message }}
                  （{{ Math.round((installOf(tool.id)?.progress ?? 0) * 100) }}%）
                  <span v-if="installOf(tool.id)?.error">{{ installOf(tool.id)?.error }}</span>
                </div>
              </div>
              <button
                v-if="!tool.installed"
                class="secondary btn-sm"
                type="button"
                style="flex-shrink: 0"
                :disabled="store.toolBusy.value !== null"
                @click="store.handleInstallTool(tool.id)"
              >
                <StudioIcon name="download" :size="14" />
                安装 {{ tool.display_name }}
              </button>
            </li>
          </ul>

          <div class="gpu-block">
            <div class="pane-header">
              <div class="button-row">
                <StudioIcon name="cpu" :size="15" />
                <strong>dettato GPU 加速</strong>
              </div>
              <span
                class="pill"
                :class="store.gpuStatus.value?.dettato_torch?.cuda_available ? 'pill-ok' : 'pill-warn'"
              >
                {{ store.gpuStatus.value?.dettato_torch?.cuda_available ? "CUDA 可用" : "CPU 推理" }}
              </span>
            </div>

            <template v-if="store.gpuStatus.value">
              <div class="meta-row">
                <span>
                  NVIDIA：{{
                    store.gpuStatus.value.nvidia.present
                      ? `${store.gpuStatus.value.nvidia.name ?? "未知 GPU"}（驱动 ${store.gpuStatus.value.nvidia.driver ?? "?"}）`
                      : "未检测到 NVIDIA GPU"
                  }}
                </span>
                <span>
                  PyTorch：{{
                    store.gpuStatus.value.dettato_torch
                      ? `${store.gpuStatus.value.dettato_torch.version ?? "?"} (CUDA ${store.gpuStatus.value.dettato_torch.cuda_build ?? "无"})`
                      : "未安装 dettato"
                  }}
                </span>
              </div>

              <div class="row">
                <div class="field" style="flex: 1 1 240px">
                  <label for="dettato-device">推理设备</label>
                  <select
                    id="dettato-device"
                    :value="store.gpuStatus.value.device"
                    @change="onDettatoDeviceChange"
                  >
                    <option value="auto">自动（优先 CUDA/MPS，否则 CPU）</option>
                    <option value="cpu">CPU</option>
                    <option value="cuda">CUDA</option>
                    <option value="mps">MPS（Apple Silicon）</option>
                  </select>
                </div>
                <button
                  v-if="!store.gpuStatus.value.dettato_torch?.cuda_available"
                  class="secondary"
                  type="button"
                  :disabled="!store.gpuStatus.value.nvidia.present || store.toolBusy.value !== null"
                  @click="store.handleInstallGpuTorch"
                >
                  <StudioIcon name="download" :size="14" />
                  安装 CUDA 版 PyTorch（约 2.5 GB）
                </button>
              </div>
              <div v-if="store.toolInstalls.value['dettato-gpu']" class="muted" style="font-size: 12px">
                {{ store.toolInstalls.value["dettato-gpu"]?.message }}
                （{{ Math.round((store.toolInstalls.value["dettato-gpu"]?.progress ?? 0) * 100) }}%）
                <span v-if="store.toolInstalls.value['dettato-gpu']?.error">
                  {{ store.toolInstalls.value["dettato-gpu"]?.error }}
                </span>
              </div>
            </template>
          </div>
        </section>

        <section id="settings-sec-ai-mcp" class="settings-section">
          <div class="pane-header">
            <h2>AI 与 MCP 客户端集成（高级可选）</h2>
          </div>

          <details class="advanced-box">
            <summary>可选 OpenAI 兼容 HTTP 模型接口</summary>
            <div class="settings-disclosure-body">
              <label class="checkbox-row">
                <input v-model="store.llmEnabledSetting.value" type="checkbox" />
                启用可选外部 LLM 意图规划（不启用时保持 100% 离线确定性规则引擎）
              </label>
              <div class="field">
                <label for="settings-llm-url">Base URL（例如 http://127.0.0.1:11434/v1）</label>
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
              <div class="button-row">
                <span
                  class="pill"
                  :class="store.llmApiKeyConfigured.value ? 'pill-ok' : ''"
                >
                  {{ store.llmApiKeyConfigured.value ? "系统凭据库已保管密钥" : "未配置外部密钥" }}
                </span>
                <button class="secondary btn-sm" type="button" @click="store.handleSaveSettings">
                  保存模型设置
                </button>
              </div>
            </div>
          </details>

          <details class="advanced-box">
            <summary>MCP 客户端接入（Claude Code / Codex / Antigravity / DeepSeek）</summary>
            <div class="settings-disclosure-body">
              <p class="muted" style="margin: 0; font-size: 12px">
                桌面端默认内置确定性规划器，完全离线可用；如已订阅外部客户端，可挂载本地
                <code>lyraforge mcp</code>（真机 <code>play_in_game</code> 始终在 MCP 中保持门控）。
              </p>

              <div class="mcp-tabs-row">
                <div class="tab-bar" role="tablist" aria-label="AI 客户端配置方式">
                  <button
                    type="button"
                    role="tab"
                    class="tab-btn"
                    :aria-selected="activeMcpTab === 'claude'"
                    @click="activeMcpTab = 'claude'"
                  >
                    Claude Code
                  </button>
                  <button
                    type="button"
                    role="tab"
                    class="tab-btn"
                    :aria-selected="activeMcpTab === 'codex'"
                    @click="activeMcpTab = 'codex'"
                  >
                    Codex CLI
                  </button>
                  <button
                    type="button"
                    role="tab"
                    class="tab-btn"
                    :aria-selected="activeMcpTab === 'antigravity'"
                    @click="activeMcpTab = 'antigravity'"
                  >
                    Antigravity
                  </button>
                  <button
                    type="button"
                    role="tab"
                    class="tab-btn"
                    :aria-selected="activeMcpTab === 'deepseek'"
                    @click="activeMcpTab = 'deepseek'"
                  >
                    DeepSeek / 通用
                  </button>
                </div>

                <button
                  class="secondary btn-sm"
                  type="button"
                  @click="copyText(MCP_SNIPPETS[activeMcpTab].code)"
                >
                  <StudioIcon name="copy" :size="14" />
                  复制配置
                </button>
              </div>

              <div class="field">
                <span class="muted" style="font-size: 12px">{{ MCP_SNIPPETS[activeMcpTab].title }}</span>
                <pre><code>{{ MCP_SNIPPETS[activeMcpTab].code }}</code></pre>
              </div>
            </div>
          </details>
        </section>
      </div>
    </div>
  </section>
</template>

<style scoped>
.settings-layout {
  display: grid;
  grid-template-columns: 192px minmax(0, 760px);
  gap: var(--space-lg);
  align-items: start;
}

.settings-nav {
  position: sticky;
  inset-block-start: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2xs);
}

.settings-nav-btn {
  justify-content: flex-start;
  inline-size: 100%;
  background: transparent;
  border-color: transparent;
  color: var(--color-muted);
  padding: var(--space-xs) var(--space-sm);
}

@media (hover: hover) {
  .settings-nav-btn:hover:not(:disabled) {
    background: var(--color-paper-2);
    border-color: transparent;
    color: var(--color-ink);
  }
}

.settings-nav-btn.active {
  background: var(--color-paper-2);
  border-color: var(--color-rule);
  color: var(--color-ink);
  box-shadow: inset 2px 0 0 var(--color-accent);
}

.settings-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  min-inline-size: 0;
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  padding-block-end: var(--space-lg);
  border-block-end: var(--rule-hair) solid var(--color-rule);
}

.hotkey-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-sm);
}

.tool-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-sm);
  padding-block: var(--space-sm);
  border-block-end: var(--rule-hair) solid var(--color-rule);
}

.tool-row:first-child {
  border-block-start: var(--rule-hair) solid var(--color-rule);
}

.tool-row-main {
  flex: 1 1 300px;
  min-inline-size: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2xs);
}

.gpu-block {
  padding: var(--space-sm);
  background: var(--color-paper-2);
  border: var(--rule-hair) solid var(--color-rule);
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.settings-disclosure-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  margin-block-start: var(--space-sm);
}

.mcp-tabs-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-xs);
}

@media (max-width: 820px) {
  .settings-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-md);
  }

  .settings-nav {
    position: static;
    flex-direction: row;
    overflow-x: auto;
    border-block-end: var(--rule-hair) solid var(--color-rule);
    padding-block-end: var(--space-xs);
  }

  .settings-nav-btn {
    inline-size: auto;
  }
}
</style>
