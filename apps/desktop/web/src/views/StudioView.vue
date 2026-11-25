<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { ArrangePresetInfo, SongTrackInfo } from "../api";
import LyreKeyboard from "../components/LyreKeyboard.vue";
import PianoRollEditor, { type LivePreviewSummary } from "../components/PianoRollEditor.vue";
import StudioIcon from "../components/StudioIcon.vue";
import { arrangementTitle, type LyraStore } from "../composables/useLyraStore";
import { buildTrackColorMap, trackColorClass } from "../utils/trackColors";
import {
  formatTrackPitchRange,
  formatTrackTooltip,
  localizeTrackName,
} from "../utils/trackNames";

const props = defineProps<{
  store: LyraStore;
}>();

const inspectorOpen = ref(true);
const keyboardDockOpen = ref(false);
const confirmDeleteArrId = ref<string | null>(null);

watch(
  () => props.store.selectedArrId.value,
  () => {
    confirmDeleteArrId.value = null;
  },
);

const DROP_REASON_LABELS: Record<string, string> = {
  duplicate_key: "同键去重",
  repeat_too_fast: "过密连击过滤",
  polyphony_limit: "复音上限裁剪",
  semitone_dropped: "半音丢弃",
  out_of_range: "超音域丢弃",
  accomp_thinned: "伴奏节奏让路",
};

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

const arrangedCountByTrack = computed(() => {
  const counts = new Map<number, number>();
  for (const ev of props.store.arrDetail.value?.performance.events ?? []) {
    const trackIdx = ev.source_track ?? 0;
    counts.set(trackIdx, (counts.get(trackIdx) ?? 0) + 1);
  }
  return counts;
});

const trackColorMap = computed(() =>
  buildTrackColorMap(
    props.store.songTracks.value,
    effectiveMelodyTrack.value,
    Array.from(arrangedCountByTrack.value.keys()),
  ),
);

const dropBreakdown = computed(() => {
  const dropped = props.store.arrDetail.value?.report?.stats?.dropped;
  if (!dropped) return [];
  return Object.entries(dropped)
    .filter(([, count]) => typeof count === "number" && count > 0)
    .map(([reason, count]) => ({
      reason,
      label: DROP_REASON_LABELS[reason] ?? reason,
      count: count as number,
    }));
});

const timingAdjustmentItems = computed(() => {
  const adj = props.store.arrDetail.value?.report?.stats?.timing_adjustments;
  if (!adj) return [];
  const items: Array<{ key: string; label: string; value: number }> = [];
  if ((adj.arpeggiated_events ?? 0) > 0) {
    items.push({
      key: "arpeggiated",
      label: "和弦自动琶音",
      value: adj.arpeggiated_events ?? 0,
    });
  }
  if ((adj.melody_retrigger_replacements ?? 0) > 0) {
    items.push({
      key: "melody_replace",
      label: "同键让位主旋律",
      value: adj.melody_retrigger_replacements ?? 0,
    });
  }
  if ((adj.hold_shortened_for_retrigger ?? 0) > 0) {
    items.push({
      key: "hold_gap",
      label: "释放间隙缩短保持",
      value: adj.hold_shortened_for_retrigger ?? 0,
    });
  }
  if ((adj.inter_key_adjusted ?? 0) > 0) {
    items.push({
      key: "inter_key",
      label: "异键防吞音微调",
      value: adj.inter_key_adjusted ?? 0,
    });
  }
  return items;
});

const dynamicsAdjustmentItems = computed(() => {
  const dyn = props.store.arrDetail.value?.report?.stats?.dynamics_adjustments;
  if (!dyn) return [];
  const items: Array<{ key: string; label: string; value: number }> = [];
  if ((dyn.phrases_shifted_up ?? 0) > 0) {
    items.push({
      key: "phrases_up",
      label: "低音句抬升八度",
      value: dyn.phrases_shifted_up ?? 0,
    });
  }
  if ((dyn.phrases_shifted_down ?? 0) > 0) {
    items.push({
      key: "phrases_down",
      label: "高音句回落八度",
      value: dyn.phrases_shifted_down ?? 0,
    });
  }
  if ((dyn.cross_stem_aligned ?? 0) > 0) {
    items.push({
      key: "stem_align",
      label: "跨轨微对齐",
      value: dyn.cross_stem_aligned ?? 0,
    });
  }
  return items;
});

async function confirmDeleteCurrentArrangement(): Promise<void> {
  const targetId = confirmDeleteArrId.value;
  if (!targetId) return;
  confirmDeleteArrId.value = null;
  await props.store.handleDeleteArrangement(targetId);
}

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

function profileDisplayName(profileId: string): string {
  return (
    props.store.profiles.value.find((p) => p.id === profileId)?.display_name ?? profileId
  );
}

function presetShortTitle(preset: ArrangePresetInfo): string {
  const parts = preset.name.split("·");
  return parts.length > 1 ? parts[parts.length - 1].trim() : preset.name;
}

function presetParamBadge(preset: ArrangePresetInfo): string {
  const styleLabel =
    STYLES.find((s) => s.id === preset.style)?.label ?? preset.style;
  const parts = [styleLabel];
  if (preset.speed !== 1) parts.push(`${preset.speed}x`);
  if (preset.arpeggiate_ms > 0) parts.push(`错峰${preset.arpeggiate_ms}ms`);
  return parts.join(" · ");
}

function presetMatchesCurrent(preset: ArrangePresetInfo): boolean {
  const curTr = props.store.transposeInput.value.trim();
  const expectedTr = preset.transpose === null ? "auto" : String(preset.transpose);
  return (
    props.store.style.value === preset.style &&
    Math.abs(props.store.speed.value - preset.speed) < 0.01 &&
    props.store.arpeggiateMs.value === preset.arpeggiate_ms &&
    (curTr === expectedTr || (expectedTr === "auto" && curTr === ""))
  );
}

function displayTrackTitle(track: SongTrackInfo): string {
  return localizeTrackName(track.name, track.index, track.is_percussion);
}

function trackRangeLabel(track: SongTrackInfo): string {
  return formatTrackPitchRange(track);
}

const overallScore = computed(() => {
  if (!currentArr.value || !props.store.arrDetail.value) return 0;
  return (
    props.store.arrDetail.value.report?.quality?.overall_score ??
    currentArr.value.playable_ratio * 100
  );
});

const livePreviewSummary = computed<LivePreviewSummary | null>(() => {
  const meta = props.store.livePreviewMeta.value;
  const evs = props.store.livePreviewEvents.value;
  const baseEvs = props.store.arrDetail.value?.performance.events;
  if (!meta || !evs || !baseEvs) return null;
  return {
    baseCount: baseEvs.length,
    nextCount: evs.length,
    baseScore: props.store.arrDetail.value ? overallScore.value : null,
    nextScore: meta.nextScore,
    alreadyExists: meta.alreadyExists,
    existingLabel: meta.existingLabel,
    loading: meta.loading,
  };
});

watch(
  [
    () => props.store.style.value,
    () => props.store.selectedArrangerStrategy.value,
    () => props.store.accompDensity.value,
    () => props.store.phraseOctaveMode.value,
    () => props.store.crossStemAlignMs.value,
    () => props.store.transposeInput.value,
    () => props.store.speed.value,
    () => props.store.arpeggiateMs.value,
    () => props.store.timingMode.value,
    () => props.store.selectedProfileId.value,
    () => props.store.selectedTrackIndices.value,
    () => props.store.selectedMelodyTrack.value,
    () => props.store.selectedTranscriptionId.value,
  ],
  () => {
    if (!props.store.suppressLivePreview.value && props.store.arrDetail.value) {
      props.store.requestLiveArrangePreview();
    }
  },
  { deep: true },
);

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

        <select
          v-if="store.arrangements.value.length > 0"
          id="studio-arr-select"
          aria-label="已保存编曲版本"
          class="cmd-select cmd-select-arr"
          :value="store.selectedArrId.value"
          @change="onArrangementChange"
        >
          <option v-for="a in store.arrangements.value" :key="a.id" :value="a.id">
            {{ store.recentCreatedArrIds.value.has(a.id) ? "[新] " : "" }}{{ arrangementTitle(a) }}（{{ a.event_count }} 音 · {{ profileDisplayName(a.profile_id) }}）
          </option>
        </select>
        <template v-if="store.selectedArrId.value">
          <button
            v-if="confirmDeleteArrId !== store.selectedArrId.value"
            type="button"
            class="ghost btn-sm"
            :disabled="store.busy.value"
            @click="confirmDeleteArrId = store.selectedArrId.value"
          >
            <StudioIcon name="trash" :size="13" />
            删除版本
          </button>
          <template v-else>
            <button
              type="button"
              class="danger btn-sm"
              :disabled="store.busy.value"
              @click="confirmDeleteCurrentArrangement"
            >
              确认删除
            </button>
            <button
              type="button"
              class="ghost btn-sm"
              @click="confirmDeleteArrId = null"
            >
              取消
            </button>
          </template>
        </template>
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
            v-model:preview-timbre="store.previewTimbre.value"
            :keys="store.profile.value.keys"
            :events="store.arrDetail.value.performance.events"
            :arrangement-id="store.selectedArrId.value"
            :tracks="store.songTracks.value"
            :melody-track="effectiveMelodyTrack"
            :saving="store.busy.value"
            :playhead-ms="store.previewCurrentMs.value"
            :is-playing="store.previewPlaying.value"
            :fixed-velocity-preview="store.gameFixedPreview.value"
            :profile-id="store.selectedProfileId.value"
            :preview-events="store.livePreviewEvents.value"
            :preview-summary="livePreviewSummary"
            @save="store.handleSaveEdited"
            @seek="store.requestPreviewSeek"
            @apply-preview="store.handleArrange"
            @discard-preview="store.syncStudioParamsFromCurrentArrangement"
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
                当前曲目「{{ store.selectedSong.value.title }}」尚无改编版本，点击上方或下方按钮即可生成。
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
        aria-label="编曲方案与质量检查器"
      >
        <div class="inspector-section">
          <h2 class="subsection-heading">编曲方案（预设与核心设置）</h2>
          <p class="muted" style="margin: 0; font-size: 12px">
            点击场景预设会填入参数并立即生成；微调任何选项时，左侧谱面会实时预览变化。
          </p>

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
                {{ tr.pipeline_id === "vocal_split_full" ? "双轨分离" : tr.pipeline_id === "vocal_split_lead" ? "人声分离" : "单引擎直转" }} · {{ tr.engine }} ({{ tr.note_count }} 音符)
              </option>
            </select>
          </div>

          <div class="preset-list">
            <button
              v-if="!store.hasMidiSource.value || store.songTracks.value.length > 1"
              class="preset-item-btn"
              type="button"
              :disabled="!store.canArrange.value || store.busy.value"
              @click="store.applyRecommendedVocalSetup"
            >
              <span class="preset-title-row">
                <strong>流行人声护航（推荐）</strong>
                <span class="badge pill-accent">强弱动态 · 自动抬升</span>
              </span>
              <span class="muted" style="font-size: 12px">
                高潮自动精简伴奏、低音主歌整句抬高八度，适合带人声的多轨流行歌。
              </span>
            </button>
            <button
              v-for="preset in profilePresets"
              :key="preset.id"
              class="preset-item-btn"
              :class="{ 'is-active': presetMatchesCurrent(preset) }"
              type="button"
              :title="preset.description"
              @click="store.applyPreset(preset.id, { autoArrange: true })"
            >
              <span class="preset-title-row">
                <span>{{ presetShortTitle(preset) }}</span>
                <span class="badge">{{ presetParamBadge(preset) }}</span>
              </span>
              <span class="muted" style="font-size: 12px">{{ preset.description }}</span>
            </button>
          </div>

          <div class="field">
            <span id="studio-style-label" class="field-label-text">编曲风格（决定同时按下的键数上限）</span>
            <div class="segmented" role="group" aria-labelledby="studio-style-label">
              <button
                v-for="item in STYLES"
                :key="item.id"
                type="button"
                class="style-picto-btn"
                :class="{ active: store.style.value === item.id }"
                @click="store.style.value = item.id"
              >
                <svg class="style-picto" width="18" height="12" viewBox="0 0 18 12" aria-hidden="true">
                  <rect x="1" y="2" width="14" height="2" rx="1" fill="currentColor" />
                  <rect v-if="item.id !== 'melody'" x="3" y="5" width="11" height="2" rx="1" fill="currentColor" opacity="0.72" />
                  <rect v-if="item.id === 'rich'" x="5" y="8" width="11" height="2" rx="1" fill="currentColor" opacity="0.52" />
                </svg>
                <span>{{ item.label }}</span>
              </button>
            </div>
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

          <div class="row">
            <div class="field" style="flex: 1 1 130px">
              <label for="studio-accomp-density">伴奏动态密度</label>
              <select id="studio-accomp-density" v-model="store.accompDensity.value">
                <option value="">跟随策略默认</option>
                <option value="auto">智能强弱分明（高潮稳重、间奏放开）</option>
                <option value="minimal">极简纯净伴奏（仅重拍骨架）</option>
                <option value="balanced">适度双声部（人声段适度减密）</option>
                <option value="full">完整保留全部伴奏音符</option>
              </select>
            </div>
            <div class="field" style="flex: 1 1 130px">
              <label for="studio-phrase-octave">分句八度平滑</label>
              <select id="studio-phrase-octave" v-model="store.phraseOctaveMode.value">
                <option value="">跟随策略默认</option>
                <option value="smooth_lift">低音句智能抬升 (+12)</option>
                <option value="centered">全曲均值居中平滑</option>
                <option value="original">保持原始八度</option>
              </select>
            </div>
          </div>

          <details class="advanced-box">
            <summary>专业微调（移调 / 倍速 / 和弦错峰 / 时序）</summary>
            <div class="advanced-stack">
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
              <div class="field">
                <label for="studio-timing-mode">时序适配策略</label>
                <select id="studio-timing-mode" v-model="store.timingMode.value">
                  <option value="adapted">乐器时序适配（保真琶音顺序 + 同键释放间隙）</option>
                  <option value="strict_fidelity">严格忠实原谱（保留 0 ms 原始时值）</option>
                </select>
              </div>
              <div class="field">
                <label for="studio-cross-align">跨轨微对齐 (0~60 ms)</label>
                <input
                  id="studio-cross-align"
                  v-model="store.crossStemAlignMs.value"
                  type="number"
                  min="0"
                  max="60"
                  step="5"
                  placeholder="默认"
                />
              </div>
            </div>
          </details>
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
              :title="formatTrackTooltip(track)"
            >
              <label class="track-check-label">
                <input
                  type="checkbox"
                  :disabled="track.is_percussion"
                  :checked="!track.is_percussion && isTrackIncluded(track.index)"
                  @change="store.toggleTrackIncluded(track.index)"
                />
                <span
                  class="track-dot"
                  :class="track.is_percussion ? '' : trackColorClass(trackColorMap.get(track.index) ?? 0)"
                />
                <span class="track-title">{{ displayTrackTitle(track) }}</span>
                <span v-if="trackRangeLabel(track)" class="track-range-tag">
                  {{ trackRangeLabel(track) }}
                </span>
              </label>
              <div class="track-meta-actions">
                <span class="track-count-delta">
                  <template v-if="currentArr && !track.is_percussion">
                    {{ track.note_count }} → {{ arrangedCountByTrack.get(track.index) ?? 0 }} 音
                  </template>
                  <template v-else>
                    {{ track.note_count }} 音
                  </template>
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
          <p class="muted" style="margin: 0; font-size: 12px">
            勾选或取消音轨时左侧谱面会实时预览；悬停音轨可查看原始英文轨名，21 键映射会合并超音域与极密重复音。
          </p>
        </div>

        <div class="inspector-section">
          <div class="pane-header">
            <h2 class="subsection-heading">编曲适配评分</h2>
            <span
              v-if="currentArr && store.lastArrangeOutcome.value?.arrangementId === currentArr.id"
              class="pill"
              :class="store.lastArrangeOutcome.value.created ? 'pill-ok' : ''"
            >
              {{ store.lastArrangeOutcome.value.created ? "本次新建" : "匹配已有版本" }}
            </span>
            <span v-else-if="currentArr" class="pill tabular">
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

            <div v-if="store.arrDetail.value.report?.stats" class="drop-summary">
              <div>
                参与编曲 {{ store.arrDetail.value.report.stats.considered_notes }} 音 → 输出
                {{ store.arrDetail.value.report.stats.emitted_events }} 音
                <template
                  v-if="
                    (store.arrDetail.value.report.stats.excluded_tracks ?? 0) > 0 ||
                    (store.arrDetail.value.report.stats.excluded_percussion ?? 0) > 0
                  "
                >
                  （已忽略未选音轨 {{ store.arrDetail.value.report.stats.excluded_tracks ?? 0 }} 音、打击乐
                  {{ store.arrDetail.value.report.stats.excluded_percussion ?? 0 }} 音）
                </template>
              </div>
              <div v-if="dropBreakdown.length > 0" class="drop-summary-list">
                <span
                  v-for="item in dropBreakdown"
                  :key="item.reason"
                  class="drop-summary-item"
                >
                  {{ item.label }} {{ item.count }}
                </span>
              </div>
              <div
                v-if="timingAdjustmentItems.length > 0 || dynamicsAdjustmentItems.length > 0"
                class="drop-summary-list"
              >
                <span
                  v-for="item in timingAdjustmentItems"
                  :key="item.key"
                  class="drop-summary-item"
                >
                  {{ item.label }} {{ item.value }}
                </span>
                <span
                  v-for="item in dynamicsAdjustmentItems"
                  :key="item.key"
                  class="drop-summary-item"
                >
                  {{ item.label }} {{ item.value }}
                </span>
              </div>
            </div>

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

        <details class="advanced-box" :open="Boolean(store.comparisonResult.value)">
          <summary>版本对照（A/B 对比 · 可选）</summary>
          <div class="advanced-stack">
            <p class="muted" style="margin: 0; font-size: 12px">
              同时生成「经典基线」与「人声增强/动态」两版并自动对比评分，拿不准策略时可用于试听比较。
            </p>
            <button
              class="secondary btn-sm"
              type="button"
              :disabled="!store.canArrange.value || store.busy.value"
              @click="store.handleArrangeAB"
            >
              生成 A/B 对比版本
            </button>
            <div v-if="store.comparisonResult.value" class="ab-compare-box">
              <div class="pane-header">
                <strong>A/B 编曲对比结果</strong>
                <span class="pill pill-ok">胜出：{{ store.comparisonResult.value.winner }}</span>
              </div>
              <p class="muted" style="margin: 0; font-size: 12px">
                {{ store.comparisonResult.value.summary }}
              </p>
            </div>
          </div>
        </details>

        <details class="advanced-box">
          <summary>快捷键说明</summary>
          <dl class="inspector-dl" style="margin-block-start: var(--space-xs)">
            <div class="inspector-dl-row">
              <dt>草稿播放 / 从头</dt>
              <dd><kbd>Space</kbd> / <kbd>Shift+Space</kbd></dd>
            </div>
            <div class="inspector-dl-row">
              <dt>归零 / 回播放头</dt>
              <dd><kbd>Home</kbd> / <kbd>F</kbd></dd>
            </div>
            <div class="inspector-dl-row">
              <dt>移动音符</dt>
              <dd><kbd>↑</kbd> <kbd>↓</kbd> <kbd>←</kbd> <kbd>→</kbd></dd>
            </div>
            <div class="inspector-dl-row">
              <dt>升降一个八度</dt>
              <dd><kbd>Shift+↑</kbd> / <kbd>Shift+↓</kbd></dd>
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

.preset-item-btn.is-active {
  background: var(--color-paper-3);
  border-color: var(--color-accent);
}

.preset-title-row {
  inline-size: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-xs);
}

.field-label-text {
  font-size: 12px;
  color: var(--color-ink-2);
}

.style-picto-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2xs);
}

.style-picto {
  flex-shrink: 0;
}

.advanced-stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  margin-block-start: var(--space-xs);
}

.track-range-tag {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--color-muted);
  white-space: nowrap;
}

.ab-compare-box {
  display: flex;
  flex-direction: column;
  gap: var(--space-2xs);
  padding-block-start: var(--space-xs);
  border-block-start: var(--rule-hair) solid var(--color-rule);
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
