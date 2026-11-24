<script setup lang="ts">
import { computed, ref } from "vue";
import LyreKeyboard from "../components/LyreKeyboard.vue";
import PianoRollEditor from "../components/PianoRollEditor.vue";
import StudioIcon from "../components/StudioIcon.vue";
import { arrangementTitle, type LyraStore } from "../composables/useLyraStore";

const props = defineProps<{
  store: LyraStore;
}>();

const inspectorOpen = ref(true);
const keyboardDockOpen = ref(false);

const STYLES: Array<{ id: "melody" | "balanced" | "rich"; label: string }> = [
  { id: "melody", label: "主旋律" },
  { id: "balanced", label: "均衡" },
  { id: "rich", label: "丰满" },
];

const currentArr = computed(() => props.store.arrDetail.value?.arrangement ?? null);

const activeStrategyInfo = computed(
  () =>
    props.store.arrangerStrategies.value.find(
      (s) => s.id === props.store.selectedArrangerStrategy.value,
    ) ?? null,
);

const effectiveMelodyTrack = computed(
  () => props.store.selectedMelodyTrack.value ?? props.store.detectedMelodyTrack.value,
);

async function onTranscriptionSelect(event: Event): Promise<void> {
  const trId = (event.target as HTMLSelectElement).value;
  await props.store.selectTranscriptionForStudio(trId);
}

function isTrackIncluded(index: number): boolean {
  const sel = props.store.selectedTrackIndices.value;
  if (sel === null) return true;
  return sel.includes(index);
}

function toggleMelodyTrack(index: number): void {
  props.store.selectedMelodyTrack.value =
    props.store.selectedMelodyTrack.value === index ? null : index;
}

const profilePresets = computed(() =>
  props.store.presets.value.filter(
    (preset) => preset.profile_id === props.store.selectedProfileId.value,
  ),
);

const overallScore = computed(() => {
  if (!currentArr.value || !props.store.arrDetail.value) return 0;
  return (
    props.store.arrDetail.value.report?.quality?.overall_score ??
    currentArr.value.playable_ratio * 100
  );
});

async function onArrangementChange(event: Event): Promise<void> {
  const arrId = (event.target as HTMLSelectElement).value;
  await props.store.selectArrangement(arrId);
}
</script>

<template>
  <section class="studio-workspace" aria-label="编曲工作室与 Piano Roll">
    <header class="studio-command-bar">
      <div class="cmd-left">
        <h1 class="studio-cmd-title">编曲工作室</h1>

        <select
          id="profile-select"
          v-model="store.selectedProfileId.value"
          aria-label="目标原神乐器"
          class="cmd-select"
          @change="store.handleProfileChange"
        >
          <option v-for="p in store.profiles.value" :key="p.id" :value="p.id">
            {{ p.display_name }}（{{ p.key_count }} 键）
          </option>
        </select>

        <span id="studio-style-label" class="sr-only-input">编曲风格</span>
        <div class="segmented" role="group" aria-labelledby="studio-style-label">
          <button
            v-for="item in STYLES"
            :key="item.id"
            type="button"
            :class="{ active: store.style.value === item.id }"
            @click="store.style.value = item.id"
          >
            {{ item.label }}
          </button>
        </div>

        <select
          v-if="store.arrangements.value.length > 0"
          id="studio-arr-select"
          aria-label="已保存编曲版本"
          class="cmd-select cmd-select-arr"
          :value="store.selectedArrId.value"
          @change="onArrangementChange"
        >
          <option v-for="a in store.arrangements.value" :key="a.id" :value="a.id">
            {{ arrangementTitle(a) }}（{{ a.event_count }} 音 · {{ a.profile_id }}）
          </option>
        </select>
      </div>

      <div class="cmd-right">
        <button
          class="primary btn-sm"
          type="button"
          :disabled="!store.canArrange.value || store.busy.value"
          @click="store.handleArrange"
        >
          <StudioIcon name="sliders" :size="14" />
          生成改编版本
        </button>
        <button
          class="secondary btn-sm"
          type="button"
          :disabled="!store.canArrange.value || store.busy.value"
          @click="store.handleArrangeAB"
        >
          生成 A/B 对比版本
        </button>
        <button
          class="secondary btn-sm"
          type="button"
          :disabled="!store.selectedArrId.value || store.busy.value"
          @click="store.handleAddToQueue"
        >
          <StudioIcon name="list-music" :size="14" />
          加入播放队列
        </button>
        <button
          class="secondary btn-sm"
          type="button"
          :disabled="!store.selectedArrId.value || store.busy.value"
          @click="store.handlePreview"
        >
          <StudioIcon name="play" :size="14" />
          试听当前版本
        </button>
        <button
          class="ghost btn-sm"
          type="button"
          :class="{ 'active-pill': keyboardDockOpen }"
          :aria-expanded="keyboardDockOpen"
          @click="keyboardDockOpen = !keyboardDockOpen"
        >
          <StudioIcon name="keyboard" :size="14" />
          21 键琴盘
        </button>
        <button
          class="ghost btn-sm"
          type="button"
          :class="{ 'active-pill': inspectorOpen }"
          :aria-expanded="inspectorOpen"
          @click="inspectorOpen = !inspectorOpen"
        >
          <StudioIcon name="panel-right" :size="14" />
          属性
        </button>
      </div>
    </header>

    <div class="studio-body" :class="{ 'inspector-closed': !inspectorOpen }">
      <div class="studio-canvas-col">
        <div class="studio-roll-slot">
          <PianoRollEditor
            v-if="store.arrDetail.value && store.profile.value"
            :keys="store.profile.value.keys"
            :events="store.arrDetail.value.performance.events"
            :saving="store.busy.value"
            :playhead-ms="store.previewCurrentMs.value"
            :is-playing="store.previewPlaying.value"
            @save="store.handleSaveEdited"
            @seek="store.requestPreviewSeek"
          />
          <div v-else class="empty-state" style="margin: var(--space-lg); flex: 1">
            <StudioIcon name="sliders" :size="24" />
            <template v-if="!store.selectedSong.value">
              <p style="margin: 0">尚未选择曲目，请先从顶部切换曲目或前往本地曲库选择。</p>
              <button class="primary" type="button" @click="store.setView('library')">
                浏览本地曲库
              </button>
            </template>
            <template v-else-if="!store.canArrange.value">
              <p style="margin: 0">
                当前曲目「{{ store.selectedSong.value.title }}」尚未完成音频转谱，请先转谱生成 MIDI 后再编曲。
              </p>
              <button class="primary" type="button" @click="store.setView('transcribe')">
                前往音频转谱
              </button>
            </template>
            <template v-else>
              <p style="margin: 0">
                当前曲目「{{ store.selectedSong.value.title }}」尚无改编版本。请点击上方「生成改编版本」或「生成 A/B 对比版本」。
              </p>
              <button
                class="primary"
                type="button"
                :disabled="store.busy.value"
                @click="store.handleArrange"
              >
                立即生成改编版本
              </button>
            </template>
          </div>
        </div>

        <div v-if="keyboardDockOpen && store.profile.value" class="studio-keyboard-dock">
          <div class="dock-head">
            <span class="subsection-heading">
              {{ store.profile.value.display_name }} 21 键热力映射
            </span>
            <button type="button" class="ghost btn-sm" @click="keyboardDockOpen = false">
              <StudioIcon name="chevron-down" :size="14" />
              收起琴盘
            </button>
          </div>
          <LyreKeyboard
            :keys="store.profile.value.keys"
            :event-counts="store.eventCounts.value"
            :active-key-ids="store.soundingKeyIds.value"
          />
        </div>
      </div>

      <aside
        v-show="inspectorOpen"
        class="studio-inspector"
        aria-label="编曲属性与质量检查器"
      >
        <div class="inspector-section">
          <h2 class="subsection-heading">转谱源与编曲算法</h2>
          <div
            v-if="!store.hasMidiSource.value && store.songTranscriptions.value.length > 0"
            class="field"
          >
            <label for="studio-transcription-select">当前使用的转谱版本</label>
            <select
              id="studio-transcription-select"
              :value="store.selectedTranscriptionId.value ?? ''"
              @change="onTranscriptionSelect"
            >
              <option
                v-for="tr in store.songTranscriptions.value"
                :key="tr.id"
                :value="tr.id"
              >
                {{ tr.pipeline_id ?? "direct" }} · {{ tr.engine }} ({{ tr.note_count }} 音符)
              </option>
            </select>
          </div>
          <div class="field">
            <label for="studio-arranger-strategy">编曲映射策略</label>
            <select
              id="studio-arranger-strategy"
              v-model="store.selectedArrangerStrategy.value"
            >
              <option
                v-for="strat in store.arrangerStrategies.value"
                :key="strat.id"
                :value="strat.id"
              >
                {{ strat.display_name }}
              </option>
            </select>
          </div>
          <p v-if="activeStrategyInfo" class="muted" style="margin: 0; font-size: 12px">
            {{ activeStrategyInfo.description }}
          </p>
        </div>

        <div v-if="store.songTracks.value.length > 0" class="inspector-section">
          <div class="pane-header">
            <h2 class="subsection-heading">MIDI 分轨与主旋律</h2>
            <button
              v-if="store.selectedMelodyTrack.value !== null"
              type="button"
              class="ghost btn-sm"
              @click="store.selectedMelodyTrack.value = null"
            >
              自动识别
            </button>
          </div>
          <ul class="line-list">
            <li
              v-for="track in store.songTracks.value"
              :key="track.index"
              class="track-row"
            >
              <label class="track-check-label">
                <input
                  type="checkbox"
                  :disabled="track.is_percussion"
                  :checked="!track.is_percussion && isTrackIncluded(track.index)"
                  @change="store.toggleTrackIncluded(track.index)"
                />
                <span class="track-title">{{ track.name }}</span>
              </label>
              <div class="track-meta-actions">
                <span class="muted tabular" style="font-size: 12px">
                  {{ track.note_count }} 音
                </span>
                <button
                  v-if="!track.is_percussion"
                  type="button"
                  class="btn-sm"
                  :class="effectiveMelodyTrack === track.index ? 'active-pill' : 'ghost'"
                  @click="toggleMelodyTrack(track.index)"
                >
                  {{ effectiveMelodyTrack === track.index ? "主旋律" : "设为主旋律" }}
                </button>
                <span v-else class="pill">打击乐</span>
              </div>
            </li>
          </ul>
        </div>

        <div class="inspector-section">
          <div class="pane-header">
            <h2 class="subsection-heading">编曲适配评分</h2>
            <span v-if="currentArr" class="pill tabular">
              {{ currentArr.event_count }} 音
            </span>
          </div>

          <template v-if="currentArr && store.arrDetail.value">
            <div class="score-hero">
              <strong class="score-value tabular">{{ overallScore.toFixed(1) }} / 100</strong>
              <span class="muted" style="font-size: 12px">相对输入 MIDI 可演奏性</span>
            </div>
            <progress max="100" :value="Math.min(100, Math.round(overallScore))" aria-label="编曲适配评分" />

            <dl class="inspector-dl">
              <div v-if="store.arrDetail.value.report?.quality" class="inspector-dl-row">
                <dt>主旋律保留</dt>
                <dd>{{ Math.round(store.arrDetail.value.report.quality.melody_preservation * 100) }}%</dd>
              </div>
              <div v-if="store.arrDetail.value.report?.quality" class="inspector-dl-row">
                <dt>节奏保真</dt>
                <dd>{{ Math.round(store.arrDetail.value.report.quality.rhythmic_fidelity * 100) }}%</dd>
              </div>
              <div v-if="store.arrDetail.value.report?.stats" class="inspector-dl-row">
                <dt>折半八度</dt>
                <dd>{{ store.arrDetail.value.report.stats.octave_folded }}</dd>
              </div>
              <div v-if="store.arrDetail.value.report?.stats" class="inspector-dl-row">
                <dt>邻音代偿</dt>
                <dd>{{ store.arrDetail.value.report.stats.semitone_substituted }}</dd>
              </div>
            </dl>

            <p class="muted" style="margin: 0; font-size: 12px">
              此分数衡量相对输入 MIDI 的 21 键可演奏性，不等同于音频转谱识别准确率。
            </p>

            <div class="button-row">
              <button
                type="button"
                class="btn-sm"
                :class="currentArr.is_favorite ? 'active-pill' : 'secondary'"
                @click="store.handleToggleFavorite"
              >
                <StudioIcon name="star" :size="13" />
                {{ currentArr.is_favorite ? "已收藏" : "收藏" }}
              </button>
              <button
                type="button"
                class="btn-sm"
                :class="currentArr.user_vote === 1 ? 'active-pill' : 'ghost'"
                @click="store.handleVote(1)"
              >
                推荐 (+1)
              </button>
              <button
                type="button"
                class="btn-sm"
                :class="currentArr.user_vote === -1 ? 'active-pill' : 'ghost'"
                @click="store.handleVote(-1)"
              >
                降权 (-1)
              </button>
            </div>
          </template>
          <p v-else class="muted" style="margin: 0; font-size: 12px">
            生成改编版本后将在此展示可演奏率、主旋律保留度与八度折半统计。
          </p>
        </div>

        <div v-if="store.comparisonResult.value" class="inspector-section">
          <div class="pane-header">
            <h2 class="subsection-heading">A/B 编曲对比结果</h2>
            <span class="pill pill-ok">胜出：{{ store.comparisonResult.value.winner }}</span>
          </div>
          <p class="muted" style="margin: 0; font-size: 12px">
            {{ store.comparisonResult.value.summary }}
          </p>
        </div>

        <div class="inspector-section">
          <h2 class="subsection-heading">一键预设（当前乐器）</h2>
          <div class="preset-list">
            <button
              v-for="preset in profilePresets"
              :key="preset.id"
              class="preset-item-btn"
              type="button"
              :title="preset.description"
              @click="store.applyPreset(preset.id)"
            >
              <span>{{ preset.name }}</span>
              <span class="muted" style="font-size: 12px">{{ preset.description }}</span>
            </button>
          </div>
        </div>

        <div class="inspector-section">
          <h2 class="subsection-heading">高级编曲参数</h2>
          <div class="field">
            <label for="studio-transpose">移调半音（auto 或整数）</label>
            <input id="studio-transpose" v-model="store.transposeInput.value" type="text" />
          </div>
          <div class="row">
            <div class="field" style="flex: 1 1 110px">
              <label for="studio-speed">速度倍率</label>
              <input
                id="studio-speed"
                v-model.number="store.speed.value"
                type="number"
                min="0.5"
                max="2.0"
                step="0.05"
              />
            </div>
            <div class="field" style="flex: 1 1 110px">
              <label for="studio-arp">和弦错峰 (0~60 ms)</label>
              <input
                id="studio-arp"
                v-model.number="store.arpeggiateMs.value"
                type="number"
                min="0"
                max="60"
                step="5"
              />
            </div>
          </div>
          <button
            class="secondary btn-sm"
            type="button"
            :disabled="!store.arrDetail.value"
            @click="store.setView('playback')"
          >
            <StudioIcon name="play" :size="13" />
            前往试听与演奏控制台
          </button>
        </div>

        <details class="advanced-box">
          <summary>快捷键说明</summary>
          <dl class="inspector-dl" style="margin-block-start: var(--space-xs)">
            <div class="inspector-dl-row">
              <dt>移动音符</dt>
              <dd><kbd>↑</kbd> <kbd>↓</kbd> <kbd>←</kbd> <kbd>→</kbd></dd>
            </div>
            <div class="inspector-dl-row">
              <dt>撤销 / 重做</dt>
              <dd><kbd>Ctrl+Z</kbd> / <kbd>Ctrl+Shift+Z</kbd></dd>
            </div>
            <div class="inspector-dl-row">
              <dt>删除选中</dt>
              <dd><kbd>Delete</kbd> / <kbd>Backspace</kbd></dd>
            </div>
            <div class="inspector-dl-row">
              <dt>更多操作</dt>
              <dd>右键音符 / 双击音轨插入</dd>
            </div>
          </dl>
        </details>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.studio-workspace {
  block-size: 100%;
  display: flex;
  flex-direction: column;
  min-block-size: 0;
  min-inline-size: 0;
  overflow: hidden;
}

.studio-command-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-xs);
  padding: var(--space-xs) var(--space-sm);
  background: var(--color-paper-2);
  border-block-end: var(--rule-hair) solid var(--color-rule);
  flex-shrink: 0;
}

.cmd-left,
.cmd-right {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-xs);
  min-inline-size: 0;
}

.studio-cmd-title {
  margin: 0;
  font-size: 15px;
  font-weight: var(--weight-semi);
  color: var(--color-ink);
  white-space: nowrap;
}

.cmd-select {
  inline-size: auto !important;
  min-inline-size: 124px;
  max-inline-size: 168px;
  min-block-size: 32px !important;
  padding-block: var(--space-3xs) !important;
}

.cmd-select-arr {
  max-inline-size: 188px;
}

.studio-body {
  flex: 1 1 auto;
  min-block-size: 0;
  min-inline-size: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 304px;
}

.studio-body.inspector-closed {
  grid-template-columns: minmax(0, 1fr);
}

.studio-canvas-col {
  display: flex;
  flex-direction: column;
  min-block-size: 0;
  min-inline-size: 0;
  overflow: hidden;
}

.studio-roll-slot {
  flex: 1 1 auto;
  min-block-size: 0;
  min-inline-size: 0;
  display: flex;
  flex-direction: column;
}

.studio-keyboard-dock {
  flex-shrink: 0;
  padding: var(--space-xs) var(--space-md) var(--space-sm);
  background: var(--color-paper-2);
  border-block-start: var(--rule-hair) solid var(--color-rule-strong);
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.dock-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-xs);
}

.studio-inspector {
  background: var(--color-paper-2);
  border-inline-start: var(--rule-hair) solid var(--color-rule);
  padding: var(--space-sm) var(--space-md);
  overflow-y: auto;
  min-inline-size: 0;
  min-block-size: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  scrollbar-color: var(--sb-thumb) var(--sb-track);
  scrollbar-width: auto;
}

.inspector-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  padding-block-end: var(--space-sm);
  border-block-end: var(--rule-hair) solid var(--color-rule);
}

.score-hero {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-xs);
}

.score-value {
  font-size: 20px;
  font-weight: var(--weight-semi);
  color: var(--color-accent);
}

.inspector-dl {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2xs);
}

.inspector-dl-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-xs);
  font-size: 12px;
}

.inspector-dl-row dt {
  color: var(--color-muted);
}

.inspector-dl-row dd {
  margin: 0;
  font-family: var(--font-mono);
  color: var(--color-ink);
  font-variant-numeric: tabular-nums;
}

.preset-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2xs);
}

.track-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2xs);
  padding-block: var(--space-2xs);
  border-block-end: var(--rule-hair) solid var(--color-rule);
}

.track-row:last-child {
  border-block-end: 0;
}

.track-check-label {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2xs);
  min-inline-size: 0;
  cursor: pointer;
}

.track-title {
  font-size: 12px;
  color: var(--color-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-inline-size: 124px;
}

.track-meta-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2xs);
}

.preset-item-btn {
  inline-size: 100%;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-3xs);
  padding: var(--space-xs);
  text-align: start;
  white-space: normal;
  background: var(--color-paper);
  border-color: var(--color-rule);
}

@media (hover: hover) {
  .preset-item-btn:hover:not(:disabled) {
    background: var(--color-paper-3);
    border-color: var(--color-accent-border);
  }
}

@media (max-width: 1024px) {
  .studio-body {
    grid-template-columns: minmax(0, 1fr);
    overflow-y: auto;
  }

  .studio-inspector {
    border-inline-start: 0;
    border-block-start: var(--rule-hair) solid var(--color-rule);
    overflow-y: visible;
  }
}
</style>
