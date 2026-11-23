<script setup lang="ts">
import { computed } from "vue";
import StudioIcon from "../components/StudioIcon.vue";
import { isImeEnter, type LyraStore } from "../composables/useLyraStore";

const props = defineProps<{
  store: LyraStore;
}>();

const AGENT_PRESETS = [
  "为当前曲目生成并对比 A/B 两版风物之诗琴编曲，保留主旋律并适度精简伴奏",
  "搜索千本樱合法开源 MIDI 并将主旋律适配为适合双手自由演奏的高可玩度版本",
  "将当前曲目转调至最适合 21 键风物之诗琴的调式，保留连贯高潮乐句",
];

const pipelineStage = computed<number>(() => {
  const job = props.store.activeJob.value;
  if (job?.status === "completed") return 4;
  if ((job?.status === "running" || job?.status === "queued") && (job.progress ?? 0) >= 0.7) {
    return 3;
  }
  if (job?.status === "running" || job?.status === "queued") return 2;
  if (props.store.transcribeTranscriptions.value.some((t) => t.status === "completed")) return 4;
  if (props.store.transcribeHasAudio.value) return 1;
  return 0;
});

const jobProgressValue = computed(() => {
  const raw = props.store.activeJob.value?.progress ?? 0;
  return Math.round(raw <= 1 ? raw * 100 : raw);
});

const stageLabel = computed(() => {
  const job = props.store.activeJob.value;
  if (!job) return "";
  const labels: Record<string, string> = {
    queued: "排队中",
    extracting: "提取音频",
    running: "识别中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return labels[job.status] ?? job.status;
});

const jobSongTitle = computed(() => {
  const job = props.store.activeJob.value;
  if (!job) return "";
  return props.store.songs.value.find((song) => song.id === job.song_id)?.title ?? job.song_id;
});

async function onSongChange(event: Event): Promise<void> {
  const songId = (event.target as HTMLSelectElement).value;
  if (songId) {
    await props.store.selectTranscribeSong(songId);
  }
}

function onAgentKeydown(event: KeyboardEvent): void {
  if (!isImeEnter(event) || event.shiftKey) return;
  event.preventDefault();
  void props.store.handleRunAgent();
}
</script>

<template>
  <section class="view-stack" aria-label="音频转谱与可选编排">
    <header class="view-header">
      <div>
        <h1 class="view-title">音频转谱</h1>
        <p class="view-subtitle">
          音频转 MIDI 多引擎管理；高级选项中可使用自然语言辅助编排。
        </p>
      </div>
      <button
        v-if="store.canArrange.value"
        class="secondary"
        type="button"
        @click="store.setView('studio')"
      >
        <StudioIcon name="sliders" />
        前往编曲工作室
      </button>
    </header>

    <div class="split-2">
      <div class="card">
        <div class="card-title-row">
          <h2>音频转 MIDI 转录</h2>
          <span
            class="pill"
            :class="store.transcribeHasAudio.value ? 'pill-ok' : ''"
          >
            {{ store.transcribeHasAudio.value ? "含音频来源" : "等待导入音频" }}
          </span>
        </div>

        <div class="field">
          <label for="transcribe-song-select">当前处理曲目</label>
          <select
            id="transcribe-song-select"
            :value="store.transcribeSongId.value ?? ''"
            :disabled="store.songs.value.length === 0"
            @change="onSongChange"
          >
            <option v-if="store.songs.value.length === 0" value="">暂无曲目，请先导入</option>
            <option v-for="s in store.songs.value" :key="s.id" :value="s.id">
              {{ s.title }}
            </option>
          </select>
        </div>

        <div class="pipeline-stepper" aria-label="转谱流程状态">
          <div class="pipe-step" :class="{ done: pipelineStage >= 1, current: pipelineStage === 0 }">
            <StudioIcon :name="pipelineStage >= 1 ? 'check' : 'music'" :size="14" />
            <span>1. 音频源</span>
          </div>
          <div class="pipe-step" :class="{ done: pipelineStage >= 3, current: pipelineStage === 2 }">
            <StudioIcon :name="pipelineStage >= 3 ? 'check' : 'sparkles'" :size="14" />
            <span>2. 引擎转录</span>
          </div>
          <div class="pipe-step" :class="{ done: pipelineStage >= 4, current: pipelineStage === 3 }">
            <StudioIcon :name="pipelineStage >= 4 ? 'check' : 'sliders'" :size="14" />
            <span>3. MIDI 入库</span>
          </div>
          <div class="pipe-step" :class="{ done: store.arrangements.value.length > 0 }">
            <StudioIcon :name="store.arrangements.value.length > 0 ? 'check' : 'play'" :size="14" />
            <span>4. 可编曲</span>
          </div>
        </div>

        <div class="field">
          <label for="transcribe-engine-select">转谱引擎</label>
          <select id="transcribe-engine-select" v-model="store.selectedEngineId.value">
            <option
              v-for="eng in store.transcribers.value"
              :key="eng.id"
              :value="eng.id"
              :disabled="!eng.available"
            >
              {{ eng.display_name }}（{{ eng.available ? "可用" : "未安装可选依赖" }} · {{ eng.license }}）
            </option>
          </select>
        </div>

        <div v-if="store.selectedEngineInfo.value" class="banner-info">
          <StudioIcon name="alert" :size="16" />
          <div>
            <strong>{{ store.selectedEngineInfo.value.display_name }}</strong> ·
            许可：<code>{{ store.selectedEngineInfo.value.license }}</code>
            <div class="muted" style="margin-block-start: 2px">
              {{ store.selectedEngineInfo.value.scope_note }}
            </div>
          </div>
        </div>

        <div class="button-row">
          <button
            class="primary"
            type="button"
            :disabled="!store.transcribeHasAudio.value || store.busy.value || !store.selectedEngineInfo.value?.available"
            @click="store.handleStartTranscribe"
          >
            <StudioIcon name="sparkles" />
            开始音频转谱
          </button>
          <button
            v-if="store.activeJob.value && (store.activeJob.value.status === 'running' || store.activeJob.value.status === 'queued')"
            class="danger"
            type="button"
            @click="store.handleCancelTranscribe"
          >
            <StudioIcon name="stop" />
            取消转谱
          </button>
        </div>

        <div
          v-if="store.activeJob.value"
          class="view-stack"
          style="gap: 6px; padding: 10px; border-radius: var(--radius-md); background: var(--bg-canvas); border: 1px solid var(--border-subtle)"
        >
          <div class="card-title-row">
            <strong>任务进度：{{ stageLabel }}</strong>
            <span class="pill tabular">{{ jobProgressValue }}%</span>
          </div>
          <progress max="100" :value="jobProgressValue" aria-label="音频转谱任务进度" />
          <p class="muted" style="margin: 0">
            曲目：{{ jobSongTitle }} · 引擎 {{ store.activeJob.value.engine_id }} · 已运行
            {{ Math.round(store.activeJob.value.elapsed_s ?? 0) }} 秒
          </p>
          <p class="muted" style="margin: 0">
            切换其他歌曲或去播放不会中断本任务；dettato 首次运行要加载模型，3–4 分钟的歌曲可能需要数分钟到十几分钟。
          </p>
          <p v-if="store.activeJob.value.transcription" class="muted" style="margin: 0">
            输出音符数：{{ store.activeJob.value.transcription.note_count }}
          </p>
          <div v-if="store.activeJob.value.error" class="banner-error">
            {{ store.activeJob.value.error.message }}
          </div>
        </div>
      </div>

    </div>

    <details class="advanced-box">
        <summary>高级（可选）：自然语言辅助编排</summary>
        <div class="card">
          <div class="card-title-row">
            <h2>自然语言辅助编排</h2>
            <span class="pill">
              {{ store.llmEnabledSetting.value ? "可选 HTTP 模型" : "确定性离线规划器" }}
            </span>
          </div>
        <p class="muted" style="margin: 0">
          离线模式下即可调度本地曲库、转录与 A/B 对比；外网检索仅在授权后抓取明确的 CC / Public Domain 来源。
        </p>

        <div class="button-row">
          <button
            v-for="preset in AGENT_PRESETS"
            :key="preset"
            class="ghost"
            type="button"
            style="font-size: 0.76rem; min-block-size: 28px; padding: 3px 10px"
            @click="store.agentPrompt.value = preset"
          >
            {{ preset.slice(0, 16) }}…
          </button>
        </div>

        <div class="field">
          <label for="agent-prompt">自然语言任务指令（Enter 提交 · Shift+Enter 换行）</label>
          <textarea
            id="agent-prompt"
            v-model="store.agentPrompt.value"
            rows="3"
            placeholder="例如：为当前曲目生成两版风物之诗琴编曲并选出更易双手演奏的版本"
            @keydown="onAgentKeydown"
          />
        </div>

        <label class="checkbox-row">
          <input v-model="store.agentAllowNetwork.value" type="checkbox" />
          允许检索外部合法 CC / Public Domain MIDI 来源（严格拒收 NoDerivatives / 闭源抓取）
        </label>

        <div class="button-row">
          <button
            class="primary"
            type="button"
            :disabled="store.busy.value"
            @click="store.handleRunAgent()"
          >
            <StudioIcon name="sparkles" />
            执行
          </button>
        </div>

        <div v-if="store.agentResult.value?.requires_confirmation" class="banner-warn">
          <StudioIcon name="alert" />
          <div class="view-stack" style="gap: 8px">
            <div>{{ store.agentResult.value.confirmation_prompt ?? store.agentResult.value.message }}</div>
            <div>
              <button
                class="primary"
                type="button"
                @click="store.handleRunAgent(true)"
              >
                授权外网 CC / PD 检索并继续
              </button>
            </div>
          </div>
        </div>

        <div v-if="store.agentResult.value" class="view-stack" style="gap: 8px">
          <div class="banner-info">
            <strong>执行结果：</strong>
            <span>{{ store.agentResult.value.message }}</span>
          </div>
          <ol v-if="store.agentResult.value.steps.length > 0" class="agent-steps">
            <li v-for="(step, idx) in store.agentResult.value.steps" :key="idx">
              <code>{{ step.tool }}</code> ({{ step.status }}) — {{ step.detail }}
            </li>
          </ol>
        </div>
        </div>
    </details>
  </section>
</template>
