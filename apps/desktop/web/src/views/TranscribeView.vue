<script setup lang="ts">
import { computed } from "vue";
import type { TranscriptionJob } from "../api";
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

const currentJob = computed(() => props.store.currentSongJob.value);

const currentJobRunning = computed(() => {
  const st = currentJob.value?.status;
  return st === "running" || st === "queued";
});

const pipelineStage = computed<number>(() => {
  const job = currentJob.value;
  if (job?.status === "completed") return 4;
  if (currentJobRunning.value) {
    return (job?.progress ?? 0) >= 0.7 ? 3 : 2;
  }
  if (
    props.store.songTranscriptions.value.some((t) => t.status === "completed") ||
    props.store.hasMidiSource.value
  ) {
    return 4;
  }
  if (props.store.hasAudioSource.value) return 1;
  return 0;
});

function jobProgressPercent(job: TranscriptionJob | null): number {
  const raw = job?.progress ?? 0;
  return Math.round(raw <= 1 ? raw * 100 : raw);
}

const jobProgressValue = computed(() => jobProgressPercent(currentJob.value));

function jobStageLabel(job: TranscriptionJob | null): string {
  if (!job) return "";
  const labels: Record<string, string> = {
    queued: "排队中",
    extracting: "提取音频",
    analyzing: "分析音高",
    transcribing: "识别中",
    running: "识别中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return labels[job.stage ?? ""] ?? labels[job.status] ?? job.stage ?? job.status;
}

const stageLabel = computed(() => jobStageLabel(currentJob.value));

const jobSongTitle = computed(() => {
  const job = currentJob.value;
  if (!job) return "";
  return props.store.songTitleById(job.song_id);
});

async function onSongChange(event: Event): Promise<void> {
  const songId = (event.target as HTMLSelectElement).value;
  if (songId) {
    await props.store.selectSong(songId);
  }
}

async function onQuickAudioPick(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) {
    await props.store.importDroppedOrPickedFile(file);
    input.value = "";
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
          从音频或视频提取旋律生成标准 MIDI；转谱识别准确率与后续 21 键可演奏性相互独立评估。
        </p>
      </div>
      <button
        v-if="store.canArrange.value"
        class="secondary"
        type="button"
        @click="store.setView('studio')"
      >
        <StudioIcon name="sliders" :size="15" />
        前往编曲工作室
      </button>
    </header>

    <div class="pipeline-stepper" aria-label="转谱流程状态">
      <div class="pipe-step" :class="{ done: pipelineStage >= 1, current: pipelineStage === 0 }">
        <StudioIcon :name="pipelineStage >= 1 ? 'check' : 'music'" :size="14" />
        <span>1. 选择或导入音频</span>
      </div>
      <div class="pipe-step" :class="{ done: pipelineStage >= 3, current: pipelineStage === 2 }">
        <StudioIcon :name="pipelineStage >= 3 ? 'check' : 'sparkles'" :size="14" />
        <span>2. 引擎音符识别</span>
      </div>
      <div class="pipe-step" :class="{ done: pipelineStage >= 4, current: pipelineStage === 3 }">
        <StudioIcon :name="pipelineStage >= 4 ? 'check' : 'sliders'" :size="14" />
        <span>3. MIDI 入库校验</span>
      </div>
      <div class="pipe-step" :class="{ done: store.arrangements.value.length > 0 }">
        <StudioIcon :name="store.arrangements.value.length > 0 ? 'check' : 'play'" :size="14" />
        <span>4. 进入编曲适配</span>
      </div>
    </div>

    <div class="split-asymmetric">
      <div class="pane">
        <div class="pane-header">
          <h2>音频转 MIDI 转录</h2>
          <span
            class="pill"
            :class="store.hasAudioSource.value || store.hasMidiSource.value ? 'pill-ok' : ''"
          >
            {{
              store.hasAudioSource.value
                ? "含音频来源"
                : store.hasMidiSource.value
                  ? "纯 MIDI 来源"
                  : "等待导入音频"
            }}
          </span>
        </div>

        <div class="field">
          <label for="transcribe-song-select">当前转谱曲目（与顶部工作区曲目同步）</label>
          <select
            id="transcribe-song-select"
            :value="store.selectedSongId.value ?? ''"
            :disabled="store.allSongs.value.length === 0"
            @change="onSongChange"
          >
            <option v-if="store.allSongs.value.length === 0" value="">暂无曲目，请先导入</option>
            <option v-for="s in store.allSongs.value" :key="s.id" :value="s.id">
              {{ s.title }}{{ store.isSongTranscribing(s.id) ? "（转谱中）" : "" }}
            </option>
          </select>
        </div>

        <div class="transcribe-upload-row">
          <span class="muted" style="font-size: 13px">还没有音频曲目？支持直接导入 mp3、wav、mp4 或 m4s</span>
          <label class="tr-file-btn" for="transcribe-file-input">
            <StudioIcon name="upload" :size="13" />
            <span>导入新音频</span>
            <input
              id="transcribe-file-input"
              class="sr-only-input"
              type="file"
              accept=".wav,.mp3,.flac,.ogg,.oga,.opus,.m4a,.m4b,.aac,.wma,.aiff,.aif,.m4s,.mp4,.m4v,.mkv,.webm,.mov,.avi,.flv,.wmv,.ts,.m2ts,.mts,.3gp,.mpg,.mpeg,.vob,.ogv"
              :disabled="store.busy.value"
              @change="onQuickAudioPick"
            />
          </label>
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
          <StudioIcon name="info" :size="15" />
          <div style="min-inline-size: 0">
            <strong>{{ store.selectedEngineInfo.value.display_name }}</strong>
            <div class="meta-row" style="margin-block-start: var(--space-3xs)">
              <code>{{ store.selectedEngineInfo.value.license }}</code>
              <span>{{ store.selectedEngineInfo.value.scope_note }}</span>
            </div>
          </div>
        </div>

        <div class="button-row">
          <button
            class="primary"
            type="button"
            :disabled="
              !store.hasAudioSource.value ||
              store.busy.value ||
              !store.selectedEngineInfo.value?.available ||
              currentJobRunning
            "
            @click="store.handleStartTranscribe"
          >
            <StudioIcon name="sparkles" :size="15" />
            {{ currentJobRunning ? "正在转谱中…" : "开始音频转谱" }}
          </button>
          <button
            v-if="currentJobRunning && currentJob"
            class="danger"
            type="button"
            @click="store.handleCancelTranscribe(currentJob.id)"
          >
            <StudioIcon name="stop" :size="15" />
            取消转谱
          </button>
        </div>
      </div>

      <div class="pane">
        <div class="pane-header">
          <h2>当前曲目任务状态</h2>
          <span v-if="currentJob" class="pill tabular">{{ jobProgressValue }}%</span>
        </div>

        <div v-if="currentJob" class="job-panel">
          <div class="pane-header">
            <strong>{{ stageLabel }}</strong>
            <span class="muted tabular" style="font-size: 12px">
              已运行 {{ Math.round(currentJob.elapsed_s ?? 0) }} 秒
            </span>
          </div>
          <progress max="100" :value="jobProgressValue" aria-label="音频转谱任务进度" />
          <div class="meta-row">
            <span>曲目：{{ jobSongTitle }}</span>
            <span>引擎：{{ currentJob.engine_id }}</span>
          </div>
          <p class="muted" style="margin: 0; font-size: 12px">
            切换到其他曲目或页面不会中断本任务。dettato 首次运行需加载模型权重，3 到 4 分钟曲目可能需要数分钟。
          </p>
          <div v-if="currentJob.transcription || currentJob.status === 'completed'" class="banner-info">
            <StudioIcon name="check" :size="15" />
            <div style="display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-xs); flex: 1">
              <span>
                已完成入库，共识别
                <strong>{{ currentJob.transcription?.note_count ?? 0 }}</strong>
                个原始音符，可直接前往编曲工作室。
              </span>
              <button
                type="button"
                class="secondary btn-sm"
                @click="store.openSongInView(currentJob.song_id, 'studio')"
              >
                前往编曲工作室
              </button>
            </div>
          </div>
          <div v-if="currentJob.error" class="banner-error">
            <div>
              <div>{{ currentJob.error.message }}</div>
              <div class="muted" style="font-size: 12px; margin-block-start: var(--space-3xs)">
                建议检查 FFmpeg / 引擎安装路径，或尝试更换内置单音 / Basic Pitch 引擎后重试。
              </div>
            </div>
          </div>
        </div>

        <div v-else class="banner-info">
          <StudioIcon name="info" :size="15" />
          <div style="display: flex; flex-direction: column; gap: var(--space-xs); flex: 1; min-inline-size: 0">
            <div>
              当前选中曲目：<strong>{{ store.selectedSong.value?.title || "未选择" }}</strong>
            </div>
            <div class="muted" style="font-size: 12px">
              {{
                !store.selectedSong.value
                  ? "请先导入音频/MIDI，或从顶部和左侧曲库选择曲目。"
                  : store.hasAudioSource.value
                    ? store.songTranscriptions.value.some((t) => t.status === "completed")
                      ? "本曲目已有可用转谱记录，可直接进入编曲工作室或更换引擎重新转谱。"
                      : "已检测到音频或视频源，选择引擎后点击「开始音频转谱」即可提交后台任务。"
                    : "当前曲目为纯 MIDI 来源，无需 AI 转谱，可直接前往编曲工作室调整指法。"
              }}
            </div>
            <div v-if="store.canArrange.value">
              <button
                type="button"
                class="secondary btn-sm"
                @click="store.setView('studio')"
              >
                前往编曲工作室
              </button>
            </div>
          </div>
        </div>

        <div class="section-block">
          <h3 class="subsection-heading">
            本曲目转谱记录 ({{ store.songTranscriptions.value.length }})
          </h3>
          <ul v-if="store.songTranscriptions.value.length > 0" class="line-list">
            <li v-for="tr in store.songTranscriptions.value" :key="tr.id" class="line-list-row">
              <div class="meta-row">
                <span class="pill" :class="tr.status === 'completed' ? 'pill-ok' : ''">
                  {{ tr.engine }}
                </span>
                <span>{{ tr.status }}</span>
              </div>
              <span class="tabular" style="font-size: 13px; font-weight: var(--weight-medium)">
                {{ tr.note_count }} 音符
              </span>
            </li>
          </ul>
          <p v-else class="muted" style="margin: 0; font-size: 12px">
            尚无转谱记录；完成后将自动保存为标准 MIDI 供 21 键编曲器使用。
          </p>
        </div>

        <div
          v-if="store.otherSongJobs.value.length > 0"
          class="section-block"
          style="padding-block-start: var(--space-sm)"
        >
          <h3 class="subsection-heading">
            其他曲目的转谱任务 ({{ store.otherSongJobs.value.length }})
          </h3>
          <ul class="line-list">
            <li v-for="job in store.otherSongJobs.value" :key="job.id" class="line-list-row">
              <div style="min-inline-size: 0; flex: 1">
                <div style="font-size: 13px; font-weight: var(--weight-medium)" class="truncate">
                  {{ store.songTitleById(job.song_id) }}
                </div>
                <div class="meta-row">
                  <span
                    class="pill"
                    :class="
                      job.status === 'completed'
                        ? 'pill-ok'
                        : job.status === 'failed'
                          ? 'pill-danger'
                          : job.status === 'running' || job.status === 'queued'
                            ? 'pill-accent'
                            : ''
                    "
                  >
                    {{ jobStageLabel(job) }}
                    <template v-if="job.status === 'running' || job.status === 'queued'">
                      {{ jobProgressPercent(job) }}%
                    </template>
                  </span>
                  <span>{{ job.engine_id }}</span>
                </div>
              </div>
              <div class="button-row" style="flex-shrink: 0">
                <button
                  v-if="job.status === 'completed'"
                  type="button"
                  class="secondary btn-sm"
                  @click="store.openSongInView(job.song_id, 'studio')"
                >
                  去编曲
                </button>
                <button
                  type="button"
                  class="secondary btn-sm"
                  @click="store.selectSong(job.song_id)"
                >
                  {{ job.status === 'running' || job.status === 'queued' ? "切换查看" : "查看" }}
                </button>
                <button
                  v-if="job.status === 'running' || job.status === 'queued'"
                  type="button"
                  class="danger btn-sm"
                  @click="store.handleCancelTranscribe(job.id)"
                >
                  取消
                </button>
              </div>
            </li>
          </ul>
        </div>

        <div class="section-block" style="padding-block-start: var(--space-sm)">
          <div class="pane-header">
            <h3 class="subsection-heading">已支持引擎状态</h3>
            <button
              type="button"
              class="ghost btn-sm"
              @click="store.setView('settings')"
            >
              前往设置安装依赖
            </button>
          </div>
          <ul class="line-list">
            <li v-for="eng in store.transcribers.value" :key="eng.id" class="line-list-row">
              <div style="min-inline-size: 0; flex: 1">
                <div style="font-size: 13px; font-weight: var(--weight-medium)">{{ eng.display_name }}</div>
                <div class="meta-row">
                  <code>{{ eng.license }}</code>
                  <span class="truncate">{{ eng.scope_note }}</span>
                </div>
              </div>
              <span class="pill" :class="eng.available ? 'pill-ok' : 'pill-warn'">
                {{ eng.available ? "已就绪" : "未安装" }}
              </span>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <details class="advanced-box">
      <summary>高级（可选）：自然语言辅助编排</summary>
      <div class="agent-box-body">
        <div class="pane-header">
          <p class="muted" style="margin: 0; font-size: 12px">
            离线模式下即可调度本地曲库、转录与 A/B 对比；外网检索仅在授权后抓取明确的 CC / Public Domain 来源。
          </p>
          <span class="pill">
            {{ store.llmEnabledSetting.value ? "可选 HTTP 模型" : "确定性离线规划器" }}
          </span>
        </div>

        <div class="button-row">
          <button
            v-for="preset in AGENT_PRESETS"
            :key="preset"
            class="ghost btn-sm"
            type="button"
            @click="store.agentPrompt.value = preset"
          >
            {{ preset.slice(0, 16) }}…
          </button>
        </div>

        <div class="field">
          <label for="agent-prompt">自然语言任务指令（Enter 提交，Shift+Enter 换行）</label>
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
            class="secondary"
            type="button"
            :disabled="store.busy.value"
            @click="store.handleRunAgent()"
          >
            <StudioIcon name="sparkles" :size="14" />
            执行
          </button>
        </div>

        <div v-if="store.agentResult.value?.requires_confirmation" class="banner-warn">
          <StudioIcon name="alert" :size="15" />
          <div style="display: flex; flex-direction: column; gap: var(--space-xs)">
            <div>{{ store.agentResult.value.confirmation_prompt ?? store.agentResult.value.message }}</div>
            <div>
              <button
                class="primary btn-sm"
                type="button"
                @click="store.handleRunAgent(true)"
              >
                授权外网 CC / PD 检索并继续
              </button>
            </div>
          </div>
        </div>

        <div v-if="store.agentResult.value" style="display: flex; flex-direction: column; gap: var(--space-xs)">
          <div class="banner-info">
            <strong>执行结果：</strong>
            <span>{{ store.agentResult.value.message }}</span>
          </div>
          <ol v-if="store.agentResult.value.steps.length" class="agent-steps">
            <li v-for="(step, idx) in store.agentResult.value.steps" :key="idx">
              <code>{{ step.tool }}</code> ({{ step.status }}) {{ step.detail }}
            </li>
          </ol>
        </div>
      </div>
    </details>
  </section>
</template>

<style scoped>
.transcribe-upload-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-xs);
  padding: var(--space-xs) var(--space-sm);
  background: var(--color-paper);
  border: var(--rule-hair) solid var(--color-rule);
  border-radius: var(--radius-sm);
}

.tr-file-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2xs);
  padding: var(--space-2xs) var(--space-xs);
  border: var(--rule-hair) solid var(--color-rule-strong);
  border-radius: var(--radius-sm);
  background: var(--color-paper-3);
  color: var(--color-ink);
  font-size: 12px;
  font-weight: var(--weight-medium);
  cursor: pointer;
}

.job-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  padding: var(--space-sm);
  background: var(--color-paper);
  border: var(--rule-hair) solid var(--color-rule);
  border-radius: var(--radius-sm);
}

.agent-box-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  margin-block-start: var(--space-sm);
  padding-block-start: var(--space-sm);
  border-block-start: var(--rule-hair) solid var(--color-rule);
}
</style>
