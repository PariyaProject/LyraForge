<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { PerformanceEventItem, PreviewTimbre, ProfileKeyDef, SongTrackInfo } from "../api";
import { buildTrackColorMap, trackColorClass } from "../utils/trackColors";
import { formatAdjustmentLabel, localizeTrackName } from "../utils/trackNames";
import {
  auditionMidiNote,
  preloadPreviewSamples,
  resolvePreviewTimbre,
  startDraftSequencer,
  type DraftSequencer,
} from "../utils/webAudioPreview";
import StudioIcon from "./StudioIcon.vue";

export interface LivePreviewSummary {
  baseCount: number;
  nextCount: number;
  baseScore: number | null;
  nextScore: number | null;
  alreadyExists: boolean;
  existingLabel?: string | null;
  loading?: boolean;
}

const props = withDefaults(
  defineProps<{
    keys: ProfileKeyDef[];
    events: PerformanceEventItem[];
    saving?: boolean;
    playheadMs?: number;
    isPlaying?: boolean;
    arrangementId?: string | null;
    tracks?: SongTrackInfo[];
    melodyTrack?: number | null;
    fixedVelocityPreview?: boolean;
    profileId?: string | null;
    previewTimbre?: PreviewTimbre;
    shortcutsActive?: boolean;
    previewEvents?: PerformanceEventItem[] | null;
    previewSummary?: LivePreviewSummary | null;
  }>(),
  {
    shortcutsActive: true,
    previewEvents: null,
    previewSummary: null,
  },
);

const emit = defineEmits<{
  save: [payload: { events: PerformanceEventItem[]; label: string }];
  seek: [ms: number];
  "update:previewTimbre": [timbre: PreviewTimbre];
  applyPreview: [];
  discardPreview: [];
}>();

const ROW_HEIGHT_PX = 26;
const BASE_PX_PER_MS = 0.08;
const KEY_COLUMN_PX = 112;
const MIN_ZOOM_PCT = 25;
const MAX_ZOOM_PCT = 250;

function cloneEvents(items: PerformanceEventItem[]): PerformanceEventItem[] {
  return items
    .map((e) => ({
      ...e,
      adjustments: e.adjustments ? [...e.adjustments] : [],
    }))
    .sort(
      (a, b) =>
        a.at_ms - b.at_ms ||
        a.mapped_pitch - b.mapped_pitch ||
        a.key_id.localeCompare(b.key_id),
    );
}

const orderedKeys = computed(() => [...props.keys].sort((a, b) => b.pitch - a.pitch));
const rowIndexByKeyId = computed(() => {
  const map = new Map<string, number>();
  orderedKeys.value.forEach((k, idx) => map.set(k.key_id, idx));
  return map;
});

const scrollEl = ref<HTMLElement | null>(null);
const rowsWrapEl = ref<HTMLElement | null>(null);

const workingEvents = ref<PerformanceEventItem[]>(cloneEvents(props.events));
const history = ref<PerformanceEventItem[][]>([cloneEvents(props.events)]);
const historyIndex = ref(0);
const selectedIndices = ref<Set<number>>(
  new Set(workingEvents.value.length > 0 ? [0] : []),
);
// null = all tracks audible; a Set lists currently enabled track indices for multi-track audition
const audibleTracks = ref<Set<number> | null>(null);
const previewDisplayMode = ref<"diff" | "after">("diff");

function isTrackAudible(trackIndex: number): boolean {
  return audibleTracks.value === null || audibleTracks.value.has(trackIndex);
}

watch(
  () => props.previewEvents,
  (next) => {
    if (!next) {
      previewDisplayMode.value = "diff";
    }
  },
);

const newKeyId = ref("mid_1");
const newAtMs = ref(0);
const versionLabel = ref("Piano Roll 编辑版");

// DAW toolbar state
const zoomPct = ref(100);
const snapMs = ref(50);
const editorMode = ref<"select" | "add">("select");
const followPlayhead = ref(true);

// Web Audio draft sequencer & lyric-style smart follow state
const internalTimbre = ref<PreviewTimbre>(props.previewTimbre ?? "auto");
watch(
  () => props.previewTimbre,
  (val) => {
    if (val !== undefined) internalTimbre.value = val;
  },
);
const activeTimbre = computed(() => props.previewTimbre ?? internalTimbre.value);
const resolvedTimbre = computed(() => resolvePreviewTimbre(props.profileId, activeTimbre.value));
watch(resolvedTimbre, (next) => {
  void preloadPreviewSamples(next);
});
function onTimbreSelectChange(event: Event): void {
  const next = (event.target as HTMLSelectElement).value as PreviewTimbre;
  internalTimbre.value = next;
  emit("update:previewTimbre", next);
}

const draftPlaying = ref(false);
const draftPlayheadMs = ref(0);
const followDetached = ref(false);
const playheadDirection = ref<"left" | "right" | "visible">("visible");
let activeSequencer: DraftSequencer | null = null;
let isProgrammaticScroll = false;
let lastProgrammaticScrollLeft: number | null = null;
let programmaticScrollTimer: number | null = null;

// Context menu state
const contextMenu = ref<{ idx: number; x: number; y: number } | null>(null);

// Live multi-note drag preview state
const dragState = ref<{
  anchorIdx: number;
  indices: number[];
  origByIdx: Record<number, { atMs: number; rowIdx: number }>;
  startX: number;
  startY: number;
  deltaAtMs: number;
  deltaRow: number;
  moved: boolean;
  lastAuditionRow: number;
} | null>(null);

// Marquee box selection state
const marqueeState = ref<{
  startX: number;
  startY: number;
  currX: number;
  currY: number;
  additive: boolean;
  baseSelected: Set<number>;
  moved: boolean;
} | null>(null);

let suppressNextLaneClick = false;
let lastArrangementId: string | null | undefined = props.arrangementId;

function stopDraftPlayback(): void {
  if (activeSequencer) {
    activeSequencer.stop();
    activeSequencer = null;
  }
  draftPlaying.value = false;
}

function getAudibleDraftEvents(): PerformanceEventItem[] {
  const sourceEvents = props.previewEvents ?? workingEvents.value;
  if (audibleTracks.value === null) {
    return sourceEvents;
  }
  return sourceEvents.filter((ev) => isTrackAudible(ev.source_track ?? 0));
}

function formatClockTime(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function updatePlayheadDirection(): void {
  const el = scrollEl.value;
  if (!el || el.clientWidth <= 0) {
    playheadDirection.value = "visible";
    return;
  }
  const laneViewWidth = Math.max(80, el.clientWidth - KEY_COLUMN_PX);
  const px = activePlayheadMs.value * pxPerMs.value;
  if (px < el.scrollLeft + 16) {
    playheadDirection.value = "left";
  } else if (px > el.scrollLeft + laneViewWidth - 48) {
    playheadDirection.value = "right";
  } else {
    playheadDirection.value = "visible";
  }
}

function setProgrammaticScrollLeft(targetLeft: number): void {
  const el = scrollEl.value;
  if (!el) return;
  const clampedLeft = Math.max(0, Math.round(targetLeft));
  if (programmaticScrollTimer !== null && typeof window !== "undefined") {
    window.clearTimeout(programmaticScrollTimer);
  }
  isProgrammaticScroll = true;
  lastProgrammaticScrollLeft = clampedLeft;
  el.scrollLeft = clampedLeft;
  updatePlayheadDirection();
  if (typeof window !== "undefined") {
    programmaticScrollTimer = window.setTimeout(() => {
      isProgrammaticScroll = false;
      lastProgrammaticScrollLeft = null;
      programmaticScrollTimer = null;
    }, 40);
  } else {
    isProgrammaticScroll = false;
    lastProgrammaticScrollLeft = null;
  }
}

function scrollPlayheadIntoView(ratio = 0.3): void {
  const el = scrollEl.value;
  if (!el) return;
  const laneViewWidth = Math.max(120, el.clientWidth - KEY_COLUMN_PX);
  const targetLeft = Math.max(
    0,
    Math.round(activePlayheadMs.value * pxPerMs.value - laneViewWidth * ratio),
  );
  setProgrammaticScrollLeft(targetLeft);
}

function returnToPlayhead(): void {
  followPlayhead.value = true;
  followDetached.value = false;
  scrollPlayheadIntoView(0.3);
}

function detachFollowIfPlaying(): void {
  if ((draftPlaying.value || props.isPlaying) && followPlayhead.value) {
    followDetached.value = true;
  }
}

function onTimelineScroll(): void {
  updatePlayheadDirection();
  const el = scrollEl.value;
  if (
    isProgrammaticScroll &&
    el &&
    lastProgrammaticScrollLeft !== null &&
    Math.abs(el.scrollLeft - lastProgrammaticScrollLeft) <= 2
  ) {
    return;
  }
  detachFollowIfPlaying();
}

function onScrollPointerDown(event: PointerEvent): void {
  if (!draftPlaying.value && !props.isPlaying) return;
  const el = scrollEl.value;
  if (!el || !followPlayhead.value) return;
  const rect = el.getBoundingClientRect();
  const onScrollbarArea =
    event.target === el ||
    event.clientY > rect.top + el.clientHeight ||
    event.clientX > rect.left + el.clientWidth;
  if (onScrollbarArea) {
    detachFollowIfPlaying();
  }
}

function startDraftFrom(startMs: number): void {
  if (workingEvents.value.length === 0) return;
  stopDraftPlayback();
  const clampedStart = Math.max(0, Math.min(startMs, totalDurationMs.value));
  draftPlaying.value = true;
  draftPlayheadMs.value = clampedStart;
  followDetached.value = false;
  updatePlayheadDirection();
  activeSequencer = startDraftSequencer(
    getAudibleDraftEvents,
    clampedStart,
    {
      onTick: (posMs) => {
        draftPlayheadMs.value = posMs;
      },
      onEnded: () => {
        activeSequencer = null;
        draftPlaying.value = false;
        draftPlayheadMs.value = 0;
        followDetached.value = false;
        updatePlayheadDirection();
      },
    },
    {
      getFixedVelocity: () => Boolean(props.fixedVelocityPreview),
      getTimbre: () => resolvedTimbre.value,
      getTotalDurationMs: () => totalDurationMs.value,
    },
  );
}

function toggleDraftPlayback(): void {
  if (draftPlaying.value) {
    stopDraftPlayback();
    return;
  }
  if (workingEvents.value.length === 0) return;
  const maxDur = totalDurationMs.value;
  let startMs = 0;
  if (draftPlayheadMs.value > 0 && draftPlayheadMs.value < maxDur - 200) {
    startMs = draftPlayheadMs.value;
  } else if ((props.playheadMs ?? 0) > 0 && (props.playheadMs ?? 0) < maxDur - 200) {
    startMs = props.playheadMs ?? 0;
  }
  startDraftFrom(startMs);
}

function restartDraftPlayback(): void {
  if (workingEvents.value.length === 0) return;
  setProgrammaticScrollLeft(0);
  startDraftFrom(0);
}

function rewindDraftPlayhead(): void {
  draftPlayheadMs.value = 0;
  followDetached.value = false;
  if (draftPlaying.value && activeSequencer) {
    activeSequencer.seek(0);
  }
  scrollPlayheadIntoView(0);
}

function scrollToMedianPitch(): void {
  const el = scrollEl.value;
  if (!el || orderedKeys.value.length === 0 || workingEvents.value.length === 0) return;
  const rowIndices = workingEvents.value
    .map((e) => rowIndexByKeyId.value.get(e.key_id))
    .filter((idx): idx is number => idx !== undefined)
    .sort((a, b) => a - b);
  if (rowIndices.length === 0) return;
  const medianRow = rowIndices[Math.floor(rowIndices.length / 2)];
  const targetTop = Math.max(0, medianRow * ROW_HEIGHT_PX - el.clientHeight / 2 + ROW_HEIGHT_PX);
  el.scrollTop = targetTop;
}

watch(
  () => [props.events, props.arrangementId] as const,
  ([next, arrId]) => {
    stopDraftPlayback();
    const switchedArrangement = arrId !== undefined && arrId !== lastArrangementId;
    if (switchedArrangement) {
      draftPlayheadMs.value = 0;
      followDetached.value = false;
    }
    const prevScrollLeft = scrollEl.value?.scrollLeft ?? 0;
    const prevScrollTop = scrollEl.value?.scrollTop ?? 0;
    lastArrangementId = arrId;

    const initial = cloneEvents(next);
    workingEvents.value = initial;
    history.value = [cloneEvents(initial)];
    historyIndex.value = 0;
    selectedIndices.value = new Set(initial.length > 0 ? [0] : []);
    contextMenu.value = null;

    if (audibleTracks.value !== null) {
      const validIds = new Set<number>([
        ...initial.map((e) => e.source_track ?? 0),
        ...(props.tracks ?? []).filter((t) => !t.is_percussion).map((t) => t.index),
      ]);
      const kept = new Set([...audibleTracks.value].filter((id) => validIds.has(id)));
      audibleTracks.value = kept.size === 0 && audibleTracks.value.size > 0 ? null : kept;
    }

    void nextTick(() => {
      const el = scrollEl.value;
      if (!el) return;
      if (switchedArrangement) {
        setProgrammaticScrollLeft(0);
        scrollToMedianPitch();
      } else if (prevScrollLeft === 0 && prevScrollTop === 0) {
        scrollToMedianPitch();
      } else {
        const maxLeft = Math.max(0, timelineWidthPx.value + KEY_COLUMN_PX - el.clientWidth);
        el.scrollLeft = Math.min(prevScrollLeft, maxLeft);
        el.scrollTop = prevScrollTop;
      }
      updatePlayheadDirection();
    });
  },
);

watch(
  () => props.isPlaying,
  (playing) => {
    if (playing && draftPlaying.value) {
      stopDraftPlayback();
    }
  },
);

watch(
  orderedKeys,
  (rows) => {
    if (rows.length > 0 && !rows.some((k) => k.key_id === newKeyId.value)) {
      newKeyId.value = rows[Math.floor(rows.length / 2)].key_id;
    }
  },
  { immediate: true },
);

const canUndo = computed(() => historyIndex.value > 0);
const canRedo = computed(() => historyIndex.value < history.value.length - 1);
const isDirty = computed(() => historyIndex.value > 0);
const pxPerMs = computed(() => BASE_PX_PER_MS * (zoomPct.value / 100));
const minNoteWidthPx = computed(() => (zoomPct.value <= 50 ? 8 : zoomPct.value <= 75 ? 14 : 22));

const totalDurationMs = computed(() => {
  const candidates = [...workingEvents.value, ...(props.previewEvents ?? [])];
  if (candidates.length === 0) return 2400;
  return Math.max(
    2400,
    ...candidates.map((e) => e.at_ms + Math.max(40, e.hold_ms)),
  );
});

const timelineWidthPx = computed(() =>
  Math.max(540, Math.ceil(totalDurationMs.value * pxPerMs.value) + 120),
);

const activePlayheadMs = computed(() => {
  if (draftPlaying.value || draftPlayheadMs.value > 0) {
    return draftPlayheadMs.value;
  }
  return Math.max(0, props.playheadMs ?? 0);
});

const playheadLeftPx = computed(() => Math.round(activePlayheadMs.value * pxPerMs.value));

const showPlayhead = computed(
  () =>
    draftPlaying.value ||
    draftPlayheadMs.value > 0 ||
    Boolean(props.isPlaying) ||
    (props.playheadMs ?? 0) > 0,
);

watch(followPlayhead, (on) => {
  if (on) {
    followDetached.value = false;
    if (draftPlaying.value || props.isPlaying) {
      scrollPlayheadIntoView(0.3);
    }
  }
});

watch(activePlayheadMs, (ms) => {
  updatePlayheadDirection();
  if ((!draftPlaying.value && !props.isPlaying) || !followPlayhead.value || followDetached.value) {
    return;
  }
  const el = scrollEl.value;
  if (!el || el.clientWidth <= 0) return;
  const laneViewWidth = Math.max(80, el.clientWidth - KEY_COLUMN_PX);
  const px = ms * pxPerMs.value;
  if (px > el.scrollLeft + laneViewWidth - 48 || px < el.scrollLeft + 16) {
    scrollPlayheadIntoView(0.3);
  }
});

function formatRulerTime(ms: number): string {
  const sec = ms / 1000;
  if (sec >= 60) {
    const mins = Math.floor(sec / 60);
    const remSec = Number((sec - mins * 60).toFixed(2));
    const whole = Math.floor(remSec);
    const frac = Math.round((remSec - whole) * 100);
    const secStr = String(whole).padStart(2, "0");
    return frac > 0 ? `${mins}:${secStr}.${String(frac).replace(/0$/, "")}` : `${mins}:${secStr}`;
  }
  return `${Number(sec.toFixed(2))}s`;
}

const rulerTicks = computed(() => {
  const stepMs =
    zoomPct.value >= 160
      ? 250
      : zoomPct.value >= 75
        ? 500
        : zoomPct.value >= 40
          ? 1000
          : 2000;
  const majorEveryMs = stepMs >= 2000 ? 10000 : stepMs >= 1000 ? 5000 : 1000;
  const maxMs = Math.ceil(totalDurationMs.value / stepMs) * stepMs;
  const ticks: Array<{ ms: number; label: string; leftPx: number; major: boolean }> = [];
  for (let ms = 0; ms <= maxMs; ms += stepMs) {
    const major = ms % majorEveryMs === 0;
    let label = "";
    if (major || (zoomPct.value >= 125 && ms % 500 === 0)) {
      label = formatRulerTime(ms);
    }
    ticks.push({
      ms,
      label,
      leftPx: Math.round(ms * pxPerMs.value),
      major,
    });
  }
  return ticks;
});

const snapBackgroundSize = computed(() => {
  const step = Math.max(12, Math.round((snapMs.value || 50) * pxPerMs.value));
  return `${step}px 100%`;
});

// Multi-track coloring & legend
const eventCountsByTrack = computed(() => {
  const counts = new Map<number, number>();
  for (const ev of workingEvents.value) {
    const t = ev.source_track ?? 0;
    counts.set(t, (counts.get(t) ?? 0) + 1);
  }
  return counts;
});

const eventTrackIds = computed(() => Array.from(eventCountsByTrack.value.keys()));

const trackColorMap = computed(() =>
  buildTrackColorMap(props.tracks ?? [], props.melodyTrack ?? null, eventTrackIds.value),
);

function trackSlotFor(ev: PerformanceEventItem): number {
  return trackColorMap.value.get(ev.source_track ?? 0) ?? 0;
}

const legendTracks = computed(() => {
  const tracksByIdx = new Map<number, SongTrackInfo>();
  for (const t of props.tracks ?? []) {
    if (!t.is_percussion) tracksByIdx.set(t.index, t);
  }
  const allIds = Array.from(
    new Set([...tracksByIdx.keys(), ...eventCountsByTrack.value.keys()]),
  ).sort((a, b) => a - b);

  return allIds.map((idx) => {
    const info = tracksByIdx.get(idx);
    const slot = trackColorMap.value.get(idx) ?? 0;
    const rawName = info?.name ?? "";
    const displayName = localizeTrackName(rawName, idx, false);
    return {
      index: idx,
      rawName,
      name: displayName,
      count: eventCountsByTrack.value.get(idx) ?? 0,
      isMelody: props.melodyTrack !== null && props.melodyTrack !== undefined && props.melodyTrack === idx,
      colorClass: trackColorClass(slot),
    };
  });
});

const trackDisplayNameMap = computed(() => {
  const map = new Map<number, string>();
  for (const tr of legendTracks.value) {
    map.set(tr.index, tr.name);
  }
  return map;
});

function formatNoteTooltip(keyDef: ProfileKeyDef, ev: PerformanceEventItem): string {
  const trIdx = ev.source_track ?? 0;
  const trName = trackDisplayNameMap.value.get(trIdx) ?? `音轨 ${trIdx + 1}`;
  const base = `${keyDef.binding} (${keyDef.key_id}) @ ${ev.at_ms} ms · ${trName}`;
  const adj = ev.adjustments?.length
    ? ` · ${ev.adjustments.map(formatAdjustmentLabel).join("、")}`
    : "";
  return `${base}${adj}`;
}

const allKnownTrackIndices = computed(() => legendTracks.value.map((t) => t.index));
const allTracksAudible = computed(
  () =>
    audibleTracks.value === null ||
    (allKnownTrackIndices.value.length > 0 &&
      allKnownTrackIndices.value.every((idx) => audibleTracks.value?.has(idx))),
);

function isTrackSoloed(trackIndex: number): boolean {
  return (
    audibleTracks.value !== null &&
    audibleTracks.value.size === 1 &&
    audibleTracks.value.has(trackIndex)
  );
}

function enableAllTracks(): void {
  audibleTracks.value = null;
}

function toggleTrackAudible(trackIndex: number): void {
  const known = allKnownTrackIndices.value;
  const current = new Set<number>(audibleTracks.value ?? known);
  if (current.has(trackIndex)) {
    current.delete(trackIndex);
  } else {
    current.add(trackIndex);
  }
  if (known.length > 0 && known.every((idx) => current.has(idx))) {
    audibleTracks.value = null;
  } else {
    audibleTracks.value = current;
  }
}

function soloTrack(trackIndex: number): void {
  if (isTrackSoloed(trackIndex)) {
    audibleTracks.value = null;
    return;
  }
  audibleTracks.value = new Set([trackIndex]);
}

const primaryTargetTrack = computed(() => {
  if (props.melodyTrack !== null && props.melodyTrack !== undefined) return props.melodyTrack;
  if (audibleTracks.value && audibleTracks.value.size === 1) {
    return [...audibleTracks.value][0];
  }
  return 0;
});

const previewDiff = computed(() => {
  const preview = props.previewEvents;
  if (!preview) return null;
  const eventKey = (ev: PerformanceEventItem) =>
    `${ev.at_ms}|${ev.key_id}|${ev.source_track ?? 0}`;
  const prevCounts = new Map<string, number>();
  for (const ev of preview) {
    const k = eventKey(ev);
    prevCounts.set(k, (prevCounts.get(k) ?? 0) + 1);
  }
  const baseRem = new Map(prevCounts);
  const removedBaseIndices = new Set<number>();
  workingEvents.value.forEach((ev, idx) => {
    const k = eventKey(ev);
    const cnt = baseRem.get(k) ?? 0;
    if (cnt > 0) {
      baseRem.set(k, cnt - 1);
    } else {
      removedBaseIndices.add(idx);
    }
  });

  const baseCounts = new Map<string, number>();
  for (const ev of workingEvents.value) {
    const k = eventKey(ev);
    baseCounts.set(k, (baseCounts.get(k) ?? 0) + 1);
  }
  const previewRem = new Map(baseCounts);
  const addedPreviewEvents: PerformanceEventItem[] = [];
  for (const ev of preview) {
    const k = eventKey(ev);
    const cnt = previewRem.get(k) ?? 0;
    if (cnt > 0) {
      previewRem.set(k, cnt - 1);
    } else {
      addedPreviewEvents.push(ev);
    }
  }
  return {
    removedBaseIndices,
    addedPreviewEvents,
    removedCount: removedBaseIndices.size,
    addedCount: addedPreviewEvents.length,
  };
});

const addedGhostsByKey = computed(() => {
  const map: Record<string, PerformanceEventItem[]> = {};
  const diff = previewDiff.value;
  if (!diff) return map;
  for (const ev of diff.addedPreviewEvents) {
    if (!map[ev.key_id]) map[ev.key_id] = [];
    map[ev.key_id].push(ev);
  }
  return map;
});

const showLegend = computed(
  () => legendTracks.value.length > 1 || (props.tracks?.length ?? 0) > 1,
);

const marqueeRect = computed(() => {
  const m = marqueeState.value;
  if (!m || !m.moved) return null;
  return {
    left: Math.min(m.startX, m.currX),
    top: Math.min(m.startY, m.currY),
    width: Math.max(2, Math.abs(m.currX - m.startX)),
    height: Math.max(2, Math.abs(m.currY - m.startY)),
  };
});

function noteWidthPx(ev: PerformanceEventItem): number {
  return Math.max(
    minNoteWidthPx.value,
    Math.round(Math.max(80, ev.hold_ms) * pxPerMs.value),
  );
}

function snapTime(ms: number): number {
  const clamped = Math.max(0, ms);
  if (snapMs.value <= 0) return Math.round(clamped);
  return Math.max(0, Math.round(clamped / snapMs.value) * snapMs.value);
}

function isOctaveBreak(idx: number): boolean {
  const cur = orderedKeys.value[idx];
  const nxt = orderedKeys.value[idx + 1];
  return Boolean(cur && nxt && cur.row !== nxt.row);
}

const eventsByKey = computed(() => {
  const map: Record<string, Array<{ idx: number; ev: PerformanceEventItem }>> = {};
  const d = dragState.value;
  workingEvents.value.forEach((ev, idx) => {
    const orig = d ? d.origByIdx[idx] : undefined;
    if (d && orig) {
      const targetKey = orderedKeys.value[orig.rowIdx + d.deltaRow] ?? orderedKeys.value[0];
      const kid = targetKey ? targetKey.key_id : ev.key_id;
      if (!map[kid]) map[kid] = [];
      map[kid].push({
        idx,
        ev: {
          ...ev,
          key_id: kid,
          at_ms: Math.max(0, orig.atMs + d.deltaAtMs),
        },
      });
      return;
    }
    if (!map[ev.key_id]) map[ev.key_id] = [];
    map[ev.key_id].push({ idx, ev });
  });
  return map;
});

const selectedEvent = computed(() => {
  if (selectedIndices.value.size !== 1) return null;
  const onlyIdx = [...selectedIndices.value][0];
  const d = dragState.value;
  const orig = d ? d.origByIdx[onlyIdx] : undefined;
  const base = workingEvents.value[onlyIdx];
  if (!base) return null;
  if (d && orig) {
    const k = orderedKeys.value[orig.rowIdx + d.deltaRow];
    if (k) {
      return {
        ...base,
        key_id: k.key_id,
        at_ms: Math.max(0, orig.atMs + d.deltaAtMs),
      };
    }
  }
  return base;
});

function setSingleSelection(idx: number | null): void {
  selectedIndices.value = idx === null ? new Set() : new Set([idx]);
}

function auditionEvent(ev: PerformanceEventItem): void {
  const vel = props.fixedVelocityPreview ? 96 : (ev.velocity ?? 92);
  auditionMidiNote(ev.mapped_pitch, vel, ev.hold_ms, undefined, resolvedTimbre.value);
}

function auditionKey(key: ProfileKeyDef): void {
  auditionMidiNote(key.pitch, 96, 260, undefined, resolvedTimbre.value);
}

function commitChange(
  nextRaw: PerformanceEventItem[],
  selectTargets: PerformanceEventItem[],
  fallbackIdx = 0,
): void {
  const targetSet = new Set(selectTargets);
  const tagged = nextRaw.map((item) => ({
    ev: {
      ...item,
      adjustments: item.adjustments ? [...item.adjustments] : [],
    },
    keepSelected: targetSet.has(item),
  }));
  tagged.sort(
    (a, b) =>
      a.ev.at_ms - b.ev.at_ms ||
      a.ev.mapped_pitch - b.ev.mapped_pitch ||
      a.ev.key_id.localeCompare(b.ev.key_id),
  );
  const sorted = tagged.map((t) => t.ev);
  const sliced = history.value.slice(0, historyIndex.value + 1);
  sliced.push(cloneEvents(sorted));
  history.value = sliced;
  historyIndex.value = sliced.length - 1;
  workingEvents.value = sorted;

  const nextSelected = new Set<number>();
  tagged.forEach((t, i) => {
    if (t.keepSelected) nextSelected.add(i);
  });
  if (nextSelected.size === 0 && sorted.length > 0) {
    nextSelected.add(Math.max(0, Math.min(fallbackIdx, sorted.length - 1)));
  }
  selectedIndices.value = nextSelected;
}

function undo(): void {
  if (!canUndo.value) return;
  historyIndex.value -= 1;
  workingEvents.value = cloneEvents(history.value[historyIndex.value]);
  setSingleSelection(workingEvents.value.length > 0 ? 0 : null);
  contextMenu.value = null;
}

function redo(): void {
  if (!canRedo.value) return;
  historyIndex.value += 1;
  workingEvents.value = cloneEvents(history.value[historyIndex.value]);
  setSingleSelection(workingEvents.value.length > 0 ? 0 : null);
  contextMenu.value = null;
}

function discardChanges(): void {
  if (!isDirty.value) return;
  stopDraftPlayback();
  const base = cloneEvents(props.events);
  workingEvents.value = base;
  history.value = [cloneEvents(base)];
  historyIndex.value = 0;
  setSingleSelection(base.length > 0 ? 0 : null);
  contextMenu.value = null;
}

function shiftIndicesPitch(indices: number[], step: -1 | 1): void {
  if (indices.length === 0) return;
  const asc = [...props.keys].sort((a, b) => a.pitch - b.pitch);
  if (asc.length === 0) return;
  const idxSet = new Set(indices);
  const updatedTargets: PerformanceEventItem[] = [];
  let changed = false;

  const next = workingEvents.value.map((item, i) => {
    if (!idxSet.has(i)) return item;
    const pos = asc.findIndex((k) => k.key_id === item.key_id);
    const nextPos = pos + step;
    if (pos < 0 || nextPos < 0 || nextPos >= asc.length) {
      updatedTargets.push(item);
      return item;
    }
    const targetKey = asc[nextPos];
    changed = true;
    const updated: PerformanceEventItem = {
      ...item,
      key_id: targetKey.key_id,
      mapped_pitch: targetKey.pitch,
    };
    updatedTargets.push(updated);
    return updated;
  });

  if (!changed) return;
  if (updatedTargets.length > 0) {
    auditionEvent(updatedTargets[0]);
  }
  commitChange(next, updatedTargets);
}

function shiftSelectedPitch(step: -1 | 1): void {
  shiftIndicesPitch([...selectedIndices.value], step);
}

function shiftIndicesOctave(indices: number[], octDir: -1 | 1): void {
  if (indices.length === 0) return;
  const keyByPitch = new Map<number, ProfileKeyDef>();
  for (const k of props.keys) {
    keyByPitch.set(k.pitch, k);
  }
  const idxSet = new Set(indices);
  const updatedTargets: PerformanceEventItem[] = [];
  let changed = false;

  const next = workingEvents.value.map((item, i) => {
    if (!idxSet.has(i)) return item;
    const targetKey = keyByPitch.get(item.mapped_pitch + octDir * 12);
    if (!targetKey) {
      updatedTargets.push(item);
      return item;
    }
    changed = true;
    const adj = item.adjustments ? [...item.adjustments] : [];
    if (!adj.includes("octave_folded")) adj.push("octave_folded");
    const updated: PerformanceEventItem = {
      ...item,
      key_id: targetKey.key_id,
      mapped_pitch: targetKey.pitch,
      adjustments: adj,
    };
    updatedTargets.push(updated);
    return updated;
  });

  if (!changed) return;
  if (updatedTargets.length > 0) {
    auditionEvent(updatedTargets[0]);
  }
  commitChange(next, updatedTargets);
}

function shiftSelectedOctave(octDir: -1 | 1): void {
  shiftIndicesOctave([...selectedIndices.value], octDir);
}

function isAccompEvent(ev: PerformanceEventItem): boolean {
  const trackIdx = ev.source_track ?? 0;
  if (props.melodyTrack !== null && props.melodyTrack !== undefined) {
    return trackIdx !== props.melodyTrack;
  }
  return trackIdx !== 0;
}

const selectedAccompanimentCount = computed(() => {
  let count = 0;
  for (const idx of selectedIndices.value) {
    const ev = workingEvents.value[idx];
    if (ev && isAccompEvent(ev)) count += 1;
  }
  return count;
});

function thinSelectedAccompaniment(): void {
  const accSelected = [...selectedIndices.value]
    .filter((i) => {
      const ev = workingEvents.value[i];
      return ev !== undefined && isAccompEvent(ev);
    })
    .sort((a, b) => {
      const ea = workingEvents.value[a];
      const eb = workingEvents.value[b];
      return ea.at_ms - eb.at_ms || ea.mapped_pitch - eb.mapped_pitch;
    });
  if (accSelected.length === 0) return;

  const dropSet = new Set<number>();
  let lastKeptMs = -1000;
  for (const idx of accSelected) {
    const ev = workingEvents.value[idx];
    if (ev.at_ms - lastKeptMs < 380) {
      dropSet.add(idx);
    } else {
      lastKeptMs = ev.at_ms;
    }
  }
  if (dropSet.size === 0 || workingEvents.value.length - dropSet.size < 1) return;

  const keepSelected: PerformanceEventItem[] = [];
  const next: PerformanceEventItem[] = [];
  workingEvents.value.forEach((ev, idx) => {
    if (dropSet.has(idx)) return;
    next.push(ev);
    if (selectedIndices.value.has(idx)) {
      keepSelected.push(ev);
    }
  });
  commitChange(next, keepSelected);
}

function clearSelectedAccompaniment(): void {
  const dropSet = new Set<number>();
  for (const idx of selectedIndices.value) {
    const ev = workingEvents.value[idx];
    if (ev && isAccompEvent(ev)) {
      dropSet.add(idx);
    }
  }
  if (dropSet.size === 0 || workingEvents.value.length - dropSet.size < 1) return;

  const keepSelected: PerformanceEventItem[] = [];
  const next: PerformanceEventItem[] = [];
  workingEvents.value.forEach((ev, idx) => {
    if (dropSet.has(idx)) return;
    next.push(ev);
    if (selectedIndices.value.has(idx)) {
      keepSelected.push(ev);
    }
  });
  commitChange(next, keepSelected);
}

function nudgeSelectedTime(deltaMs: number): void {
  const indices = [...selectedIndices.value];
  if (indices.length === 0) return;
  const idxSet = new Set(indices);
  const updatedTargets: PerformanceEventItem[] = [];

  const next = workingEvents.value.map((item, idx) => {
    if (!idxSet.has(idx)) return item;
    const updated: PerformanceEventItem = {
      ...item,
      at_ms: Math.max(0, item.at_ms + deltaMs),
    };
    updatedTargets.push(updated);
    return updated;
  });
  commitChange(next, updatedTargets);
}

function onInlineTimeChange(event: Event): void {
  if (selectedIndices.value.size !== 1) return;
  const onlyIdx = [...selectedIndices.value][0];
  const cur = workingEvents.value[onlyIdx];
  if (!cur) return;
  const parsed = Number((event.target as HTMLInputElement).value);
  if (!Number.isFinite(parsed)) return;
  const nextMs = Math.max(0, Math.round(parsed));
  if (nextMs === cur.at_ms) return;
  const updated: PerformanceEventItem = { ...cur, at_ms: nextMs };
  const next = workingEvents.value.map((item, idx) => (idx === onlyIdx ? updated : item));
  commitChange(next, [updated]);
}

function duplicateIndices(indices: number[], offsetMs = 250): void {
  if (indices.length === 0) return;
  const copies: PerformanceEventItem[] = [];
  for (const idx of indices) {
    const ev = workingEvents.value[idx];
    if (!ev) continue;
    copies.push({
      ...ev,
      at_ms: Math.max(0, ev.at_ms + offsetMs),
      adjustments: ev.adjustments ? [...ev.adjustments] : [],
    });
  }
  if (copies.length === 0) return;
  auditionEvent(copies[0]);
  commitChange([...workingEvents.value, ...copies], copies);
}

function duplicateSelected(offsetMs?: number): void {
  const step = offsetMs ?? (snapMs.value > 0 ? snapMs.value : 250);
  duplicateIndices([...selectedIndices.value], step);
}

function deleteIndices(indices: number[]): void {
  if (indices.length === 0) return;
  const sortedIdx = [...new Set(indices)].sort((a, b) => a - b);
  const removeSet = new Set(sortedIdx);
  // Keep at least one note in the arrangement editor
  if (workingEvents.value.length - removeSet.size < 1) return;
  const next = workingEvents.value.filter((_, i) => !removeSet.has(i));
  commitChange(next, [], sortedIdx[0] ?? 0);
}

function deleteSelected(): void {
  deleteIndices([...selectedIndices.value]);
}

const canDeleteSelection = computed(
  () =>
    selectedIndices.value.size > 0 &&
    workingEvents.value.length - selectedIndices.value.size >= 1,
);

function selectAllVisible(): void {
  const next = new Set<number>();
  workingEvents.value.forEach((ev, idx) => {
    if (isTrackAudible(ev.source_track ?? 0)) {
      next.add(idx);
    }
  });
  selectedIndices.value = next;
}

function createNoteFor(key: ProfileKeyDef, atMs: number): void {
  const targetTrack = primaryTargetTrack.value;
  const created: PerformanceEventItem = {
    at_ms: Math.max(0, Math.round(atMs)),
    key_id: key.key_id,
    action: "tap",
    hold_ms: 40,
    source_pitch: key.pitch,
    mapped_pitch: key.pitch,
    source_track: targetTrack,
    source_channel: 0,
    velocity: 96,
    adjustments: [],
  };
  auditionEvent(created);
  commitChange([...workingEvents.value, created], [created]);
}

function addNote(): void {
  const key = props.keys.find((k) => k.key_id === newKeyId.value);
  if (!key) return;
  createNoteFor(key, Number(newAtMs.value) || 0);
}

function onLaneClick(key: ProfileKeyDef, event: MouseEvent, forceAdd = false): void {
  contextMenu.value = null;
  if (suppressNextLaneClick) {
    suppressNextLaneClick = false;
    return;
  }
  if (!forceAdd && editorMode.value !== "add") return;
  const target = event.target as HTMLElement;
  if (target.closest(".pr-note")) return;
  const lane = event.currentTarget as HTMLElement;
  const rect = lane.getBoundingClientRect();
  const relX = Math.max(0, event.clientX - rect.left);
  const rawMs = relX / pxPerMs.value;
  createNoteFor(key, snapTime(rawMs));
}

function onRulerClick(event: MouseEvent): void {
  const track = event.currentTarget as HTMLElement;
  const rect = track.getBoundingClientRect();
  const relX = Math.max(0, event.clientX - rect.left);
  const ms = Math.max(0, Math.min(totalDurationMs.value, Math.round(relX / pxPerMs.value)));
  draftPlayheadMs.value = ms;
  followDetached.value = false;
  if (draftPlaying.value && activeSequencer) {
    activeSequencer.seek(ms);
  }
  updatePlayheadDirection();
  emit("seek", ms);
}

function fitAllTimeline(): void {
  const el = scrollEl.value;
  const availablePx = Math.max(320, (el?.clientWidth ?? 900) - KEY_COLUMN_PX - 120);
  const rawPct = Math.round((availablePx / (Math.max(2400, totalDurationMs.value) * BASE_PX_PER_MS)) * 100);
  zoomPct.value = Math.max(MIN_ZOOM_PCT, Math.min(MAX_ZOOM_PCT, rawPct));
  if (el) el.scrollLeft = 0;
}

function onScrollWheel(event: WheelEvent): void {
  const el = scrollEl.value;
  if (!el) return;
  if (event.ctrlKey || event.metaKey) {
    event.preventDefault();
    const rect = el.getBoundingClientRect();
    const pointerLaneX = Math.max(0, event.clientX - rect.left + el.scrollLeft - KEY_COLUMN_PX);
    const cursorMs = pointerLaneX / pxPerMs.value;
    const step = event.deltaY < 0 ? 25 : -25;
    const nextZoom = Math.max(MIN_ZOOM_PCT, Math.min(MAX_ZOOM_PCT, zoomPct.value + step));
    if (nextZoom === zoomPct.value) return;
    zoomPct.value = nextZoom;
    void nextTick(() => {
      const nextPxPerMs = BASE_PX_PER_MS * (nextZoom / 100);
      const viewportOffset = Math.max(0, event.clientX - rect.left - KEY_COLUMN_PX);
      el.scrollLeft = Math.max(0, Math.round(cursorMs * nextPxPerMs - viewportOffset));
    });
    return;
  }
  if (event.shiftKey) {
    event.preventDefault();
    detachFollowIfPlaying();
    el.scrollLeft += event.deltaY || event.deltaX;
  } else if (Math.abs(event.deltaX) > 0) {
    detachFollowIfPlaying();
  }
}

function onNoteContextMenu(idx: number, event: MouseEvent): void {
  event.preventDefault();
  if (!selectedIndices.value.has(idx)) {
    setSingleSelection(idx);
  }
  const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
  const vh = typeof window !== "undefined" ? window.innerHeight : 720;
  contextMenu.value = {
    idx,
    x: Math.min(event.clientX, vw - 180),
    y: Math.min(event.clientY, vh - 160),
  };
}

function runContextAction(action: "up" | "down" | "oct_up" | "oct_down" | "dup" | "del"): void {
  const menu = contextMenu.value;
  contextMenu.value = null;
  if (!menu) return;
  const targets = selectedIndices.value.has(menu.idx) ? [...selectedIndices.value] : [menu.idx];
  if (action === "up") shiftIndicesPitch(targets, 1);
  else if (action === "down") shiftIndicesPitch(targets, -1);
  else if (action === "oct_up") shiftIndicesOctave(targets, 1);
  else if (action === "oct_down") shiftIndicesOctave(targets, -1);
  else if (action === "dup") duplicateIndices(targets, 250);
  else if (action === "del") deleteIndices(targets);
}

// Multi-note drag handlers
function onWindowDragMove(ev: PointerEvent): void {
  const d = dragState.value;
  if (!d) return;
  const dx = ev.clientX - d.startX;
  const dy = ev.clientY - d.startY;
  if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
    d.moved = true;
  }
  const anchorOrig = d.origByIdx[d.anchorIdx];
  if (!anchorOrig) return;
  const snappedAnchorAt = snapTime(anchorOrig.atMs + dx / pxPerMs.value);
  let minAtMs = Infinity;
  let minRow = Infinity;
  let maxRow = -Infinity;
  for (const idx of d.indices) {
    const o = d.origByIdx[idx];
    if (!o) continue;
    minAtMs = Math.min(minAtMs, o.atMs);
    minRow = Math.min(minRow, o.rowIdx);
    maxRow = Math.max(maxRow, o.rowIdx);
  }
  const minDeltaAtMs = -minAtMs;
  const nextDeltaAtMs = Math.max(minDeltaAtMs, snappedAnchorAt - anchorOrig.atMs);
  const rawDeltaRow = Math.round(dy / ROW_HEIGHT_PX);
  const maxIdx = Math.max(0, orderedKeys.value.length - 1);
  const clampedDeltaRow = Math.max(-minRow, Math.min(maxIdx - maxRow, rawDeltaRow));

  d.deltaAtMs = nextDeltaAtMs;
  d.deltaRow = clampedDeltaRow;

  const anchorRow = anchorOrig.rowIdx + clampedDeltaRow;
  if (anchorRow !== d.lastAuditionRow) {
    d.lastAuditionRow = anchorRow;
    const k = orderedKeys.value[anchorRow];
    if (k) auditionKey(k);
  }
}

function stopDragListeners(): void {
  if (typeof window !== "undefined") {
    window.removeEventListener("pointermove", onWindowDragMove);
    window.removeEventListener("pointerup", onWindowDragUp);
  }
}

function onWindowDragUp(): void {
  stopDragListeners();
  const d = dragState.value;
  dragState.value = null;
  if (!d || !d.moved || (d.deltaAtMs === 0 && d.deltaRow === 0)) return;
  const idxSet = new Set(d.indices);
  const targets: PerformanceEventItem[] = [];
  let changed = false;

  const next = workingEvents.value.map((item, i) => {
    if (!idxSet.has(i)) return item;
    const orig = d.origByIdx[i];
    if (!orig) return item;
    const targetKey = orderedKeys.value[orig.rowIdx + d.deltaRow];
    if (!targetKey) {
      targets.push(item);
      return item;
    }
    const nextAtMs = Math.max(0, orig.atMs + d.deltaAtMs);
    if (item.at_ms !== nextAtMs || item.key_id !== targetKey.key_id) {
      changed = true;
    }
    const updated: PerformanceEventItem = {
      ...item,
      at_ms: nextAtMs,
      key_id: targetKey.key_id,
      mapped_pitch: targetKey.pitch,
    };
    targets.push(updated);
    return updated;
  });

  if (changed) {
    commitChange(next, targets);
  }
}

function isNoteDragging(idx: number): boolean {
  const d = dragState.value;
  return Boolean(d && d.moved && d.origByIdx[idx]);
}

function onNotePointerDown(
  idx: number,
  _keyId: string,
  evItem: PerformanceEventItem,
  event: PointerEvent,
): void {
  event.stopPropagation();
  contextMenu.value = null;
  const isToggle = event.shiftKey || event.ctrlKey || event.metaKey;

  if (isToggle) {
    const nextSet = new Set(selectedIndices.value);
    if (nextSet.has(idx)) {
      nextSet.delete(idx);
    } else {
      nextSet.add(idx);
      auditionEvent(evItem);
    }
    selectedIndices.value = nextSet;
    if (!nextSet.has(idx)) return;
  } else {
    if (!selectedIndices.value.has(idx)) {
      setSingleSelection(idx);
    }
    auditionEvent(evItem);
  }

  if (event.button !== 0) return;

  const dragIndices = [...selectedIndices.value];
  const origByIdx: Record<number, { atMs: number; rowIdx: number }> = {};
  for (const selIdx of dragIndices) {
    const item = workingEvents.value[selIdx];
    if (!item) continue;
    const rIdx = Math.max(0, rowIndexByKeyId.value.get(item.key_id) ?? 0);
    origByIdx[selIdx] = { atMs: item.at_ms, rowIdx: rIdx };
  }
  const anchorOrig = origByIdx[idx];
  if (!anchorOrig) return;

  dragState.value = {
    anchorIdx: idx,
    indices: Object.keys(origByIdx).map(Number),
    origByIdx,
    startX: event.clientX,
    startY: event.clientY,
    deltaAtMs: 0,
    deltaRow: 0,
    moved: false,
    lastAuditionRow: anchorOrig.rowIdx,
  };
  if (typeof window !== "undefined") {
    window.addEventListener("pointermove", onWindowDragMove);
    window.addEventListener("pointerup", onWindowDragUp);
  }
}

// Marquee box selection handlers
function updateMarqueeSelection(): void {
  const m = marqueeState.value;
  if (!m || !m.moved) return;
  const left = Math.min(m.startX, m.currX);
  const right = Math.max(m.startX, m.currX);
  const top = Math.min(m.startY, m.currY);
  const bottom = Math.max(m.startY, m.currY);

  const nextSet = m.additive ? new Set(m.baseSelected) : new Set<number>();
  workingEvents.value.forEach((ev, idx) => {
    if (!isTrackAudible(ev.source_track ?? 0)) {
      return;
    }
    const rowIdx = rowIndexByKeyId.value.get(ev.key_id);
    if (rowIdx === undefined) return;
    const x0 = Math.round(ev.at_ms * pxPerMs.value);
    const x1 = x0 + noteWidthPx(ev);
    const y0 = rowIdx * ROW_HEIGHT_PX;
    const y1 = y0 + ROW_HEIGHT_PX;
    if (x1 >= left && x0 <= right && y1 >= top && y0 <= bottom) {
      nextSet.add(idx);
    }
  });
  selectedIndices.value = nextSet;
}

function onWindowMarqueeMove(ev: PointerEvent): void {
  const m = marqueeState.value;
  const wrap = rowsWrapEl.value;
  if (!m || !wrap) return;
  const rect = wrap.getBoundingClientRect();
  m.currX = Math.max(0, ev.clientX - rect.left - KEY_COLUMN_PX);
  m.currY = Math.max(0, ev.clientY - rect.top);
  if (Math.abs(m.currX - m.startX) > 4 || Math.abs(m.currY - m.startY) > 4) {
    m.moved = true;
    updateMarqueeSelection();
  }
}

function stopMarqueeListeners(): void {
  if (typeof window !== "undefined") {
    window.removeEventListener("pointermove", onWindowMarqueeMove);
    window.removeEventListener("pointerup", onWindowMarqueeUp);
  }
}

function onWindowMarqueeUp(): void {
  stopMarqueeListeners();
  const m = marqueeState.value;
  marqueeState.value = null;
  if (!m) return;
  if (m.moved) {
    suppressNextLaneClick = true;
    window.setTimeout(() => {
      suppressNextLaneClick = false;
    }, 0);
  } else if (!m.additive) {
    selectedIndices.value = new Set();
  }
}

function onRowsPointerDown(event: PointerEvent): void {
  if (editorMode.value !== "select" || event.button !== 0) return;
  const target = event.target as HTMLElement | null;
  if (!target || target.closest(".pr-note") || target.closest(".pr-key-label")) return;
  const wrap = rowsWrapEl.value;
  if (!wrap) return;
  contextMenu.value = null;
  const rect = wrap.getBoundingClientRect();
  const laneX = Math.max(0, event.clientX - rect.left - KEY_COLUMN_PX);
  const laneY = Math.max(0, event.clientY - rect.top);
  marqueeState.value = {
    startX: laneX,
    startY: laneY,
    currX: laneX,
    currY: laneY,
    additive: event.shiftKey || event.ctrlKey || event.metaKey,
    baseSelected: new Set(selectedIndices.value),
    moved: false,
  };
  if (typeof window !== "undefined") {
    window.addEventListener("pointermove", onWindowMarqueeMove);
    window.addEventListener("pointerup", onWindowMarqueeUp);
  }
}

function onEditorKeydown(event: KeyboardEvent): void {
  const tag = (event.target as HTMLElement | null)?.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  if (event.key === "Escape") {
    if (contextMenu.value) {
      contextMenu.value = null;
      return;
    }
    if (draftPlaying.value) {
      stopDraftPlayback();
      return;
    }
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) redo();
    else undo();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
    event.preventDefault();
    redo();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
    event.preventDefault();
    selectAllVisible();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "d") {
    event.preventDefault();
    duplicateSelected();
    return;
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    if (event.shiftKey) shiftSelectedOctave(1);
    else shiftSelectedPitch(1);
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    if (event.shiftKey) shiftSelectedOctave(-1);
    else shiftSelectedPitch(-1);
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    nudgeSelectedTime(-(event.shiftKey ? 10 : snapMs.value || 50));
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    nudgeSelectedTime(event.shiftKey ? 10 : snapMs.value || 50);
  } else if (event.key === "Delete" || event.key === "Backspace") {
    event.preventDefault();
    deleteSelected();
  }
}

function onGlobalClick(event: MouseEvent): void {
  const target = event.target as HTMLElement | null;
  if (contextMenu.value && !target?.closest(".pr-context-menu")) {
    contextMenu.value = null;
  }
}

function emitSave(): void {
  if (workingEvents.value.length === 0) return;
  emit("save", {
    events: cloneEvents(workingEvents.value),
    label: versionLabel.value.trim() || "Piano Roll 编辑版",
  });
}

function onWindowShortcutKeydown(event: KeyboardEvent): void {
  if (props.shortcutsActive === false || event.defaultPrevented) return;
  if (typeof document !== "undefined" && document.querySelector("dialog[open]")) return;
  const target = event.target as HTMLElement | null;
  const tag = target?.tagName;
  if (
    tag === "INPUT" ||
    tag === "SELECT" ||
    tag === "TEXTAREA" ||
    target?.isContentEditable
  ) {
    return;
  }
  if (event.code === "Space") {
    event.preventDefault();
    if (event.shiftKey) {
      restartDraftPlayback();
    } else {
      toggleDraftPlayback();
    }
    return;
  }
  if (event.key === "Home") {
    event.preventDefault();
    rewindDraftPlayhead();
    return;
  }
  if (
    (event.code === "KeyF" || event.key.toLowerCase() === "f") &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey &&
    !event.shiftKey
  ) {
    event.preventDefault();
    returnToPlayhead();
  }
}

onMounted(() => {
  void nextTick(scrollToMedianPitch);
  void preloadPreviewSamples(resolvedTimbre.value);
  if (typeof window !== "undefined") {
    window.addEventListener("mousedown", onGlobalClick);
    window.addEventListener("keydown", onWindowShortcutKeydown);
  }
});

onBeforeUnmount(() => {
  stopDraftPlayback();
  stopDragListeners();
  stopMarqueeListeners();
  if (programmaticScrollTimer !== null && typeof window !== "undefined") {
    window.clearTimeout(programmaticScrollTimer);
    programmaticScrollTimer = null;
  }
  isProgrammaticScroll = false;
  lastProgrammaticScrollLeft = null;
  if (typeof window !== "undefined") {
    window.removeEventListener("mousedown", onGlobalClick);
    window.removeEventListener("keydown", onWindowShortcutKeydown);
  }
});
</script>

<template>
  <div class="piano-roll-editor" tabindex="0" @keydown="onEditorKeydown">
    <div class="pr-toolbar">
      <div class="pr-toolbar-group">
        <strong style="font-size: 13px">MIDI Piano Roll 可视化编辑器</strong>
        <button type="button" class="secondary btn-sm" :disabled="!canUndo" @click="undo">
          <StudioIcon name="undo" :size="13" />
          撤销
        </button>
        <button type="button" class="secondary btn-sm" :disabled="!canRedo" @click="redo">
          <StudioIcon name="redo" :size="13" />
          重做
        </button>
        <button
          type="button"
          class="ghost btn-sm"
          :disabled="!isDirty"
          @click="discardChanges"
        >
          <StudioIcon name="x" :size="13" />
          放弃修改
        </button>
        <button
          id="pr-draft-toggle"
          type="button"
          class="secondary btn-sm"
          :class="{ 'active-pill': draftPlaying }"
          :disabled="workingEvents.length === 0"
          title="快捷键 Space：在当前位置播放或暂停草稿（支持实时编辑与独奏音轨）"
          @click="toggleDraftPlayback"
        >
          <StudioIcon :name="draftPlaying ? 'stop' : 'play'" :size="13" />
          {{ draftPlaying ? "暂停草稿" : draftPlayheadMs > 0 ? "继续草稿" : "试听草稿" }}
        </button>
        <button
          id="pr-draft-restart"
          type="button"
          class="ghost btn-sm"
          :disabled="workingEvents.length === 0"
          title="快捷键 Shift+Space：从 0:00 从头试听草稿"
          @click="restartDraftPlayback"
        >
          从头播
        </button>
        <span class="hint-text tabular" aria-label="草稿播放时间">
          {{ formatClockTime(activePlayheadMs) }} / {{ formatClockTime(totalDurationMs) }}
        </span>
        <select
          id="pr-timbre-select"
          :value="activeTimbre"
          aria-label="试听音色"
          class="pr-inline-select"
          title="切换草稿与离线 WAV 试听音色"
          @change="onTimbreSelectChange"
        >
          <option value="auto">音色：跟随乐器</option>
          <option value="piano">真钢琴 · Steinway（谐律键琴）</option>
          <option value="lyre">真竖琴（风物之诗琴）</option>
          <option value="zither">真古筝（镜花之琴）</option>
          <option value="vintage">复古木弦（老旧的诗琴）</option>
        </select>
        <span class="badge" :class="isDirty ? 'pill-warn' : 'pill-ok'">
          {{ isDirty ? "有未保存修改" : "已同步" }}
        </span>
        <span class="badge tabular">{{ workingEvents.length }} 音符</span>
      </div>

      <div class="pr-toolbar-group">
        <div class="segmented" role="group" aria-label="画布操作模式">
          <button
            type="button"
            :class="{ active: editorMode === 'select' }"
            @click="editorMode = 'select'"
          >
            选择/拖动
          </button>
          <button
            type="button"
            :class="{ active: editorMode === 'add' }"
            @click="editorMode = 'add'"
          >
            点击添加
          </button>
        </div>

        <div class="pr-toolbar-group" aria-label="缩放与吸附">
          <button
            type="button"
            class="ghost btn-sm"
            aria-label="缩小时间轴"
            @click="zoomPct = Math.max(MIN_ZOOM_PCT, zoomPct - 25)"
          >
            <StudioIcon name="minus" :size="13" />
          </button>
          <span class="badge tabular">{{ zoomPct }}%</span>
          <button
            type="button"
            class="ghost btn-sm"
            aria-label="放大时间轴"
            @click="zoomPct = Math.min(MAX_ZOOM_PCT, zoomPct + 25)"
          >
            <StudioIcon name="plus" :size="13" />
          </button>
          <button
            type="button"
            class="ghost btn-sm"
            title="缩放到全曲适配视口宽度"
            @click="fitAllTimeline"
          >
            适应全曲
          </button>
          <label for="pr-snap-select" class="muted" style="font-size: 12px">吸附</label>
          <select id="pr-snap-select" v-model.number="snapMs" class="pr-inline-select">
            <option :value="0">无吸附</option>
            <option :value="25">25ms</option>
            <option :value="50">50ms</option>
            <option :value="100">100ms</option>
            <option :value="250">250ms</option>
          </select>
          <label class="pr-follow-toggle" title="试听时自动滚动跟随播放头">
            <input v-model="followPlayhead" type="checkbox" />
            跟随
          </label>
        </div>
      </div>

      <div class="pr-toolbar-group">
        <label for="pr-version-label" class="muted" style="font-size: 12px">版本</label>
        <input
          id="pr-version-label"
          v-model="versionLabel"
          type="text"
          class="pr-inline-label"
          placeholder="版本名称"
        />
        <button
          type="button"
          :class="isDirty ? 'primary btn-sm' : 'secondary btn-sm'"
          :disabled="saving || workingEvents.length === 0"
          @click="emitSave"
        >
          <StudioIcon name="check" :size="13" />
          保存为新版本
        </button>
      </div>
    </div>

    <div v-if="showLegend" class="pr-legend" role="group" aria-label="按音轨区分颜色与多选试听">
      <span class="pr-legend-label">试听音轨（可多选）：</span>
      <button
        type="button"
        class="pr-legend-btn"
        :class="{ 'is-active': allTracksAudible }"
        @click="enableAllTracks"
      >
        全部开启 ({{ workingEvents.length }})
      </button>
      <div v-for="tr in legendTracks" :key="tr.index" class="pr-track-chip">
        <button
          type="button"
          class="pr-legend-btn"
          :class="{ 'is-active': isTrackAudible(tr.index) }"
          :title="tr.rawName ? `原轨名：${tr.rawName}（点击勾选/取消此轨参与试听）` : '点击勾选/取消此轨参与试听'"
          @click="toggleTrackAudible(tr.index)"
        >
          <span class="pr-check-mark" aria-hidden="true">{{ isTrackAudible(tr.index) ? "✓" : "" }}</span>
          <span class="track-dot" :class="tr.colorClass" />
          <span>
            {{ tr.name }}<template v-if="tr.isMelody"> (主旋律)</template> ({{ tr.count }})
          </span>
        </button>
        <button
          type="button"
          class="pr-solo-btn"
          :class="{ 'is-active': isTrackSoloed(tr.index) }"
          :title="`仅独奏 ${tr.name}`"
          @click="soloTrack(tr.index)"
        >
          独奏
        </button>
      </div>
    </div>

    <div v-if="previewSummary && previewDiff" class="pr-preview-bar" role="status">
      <div class="pr-preview-stats">
        <strong>参数实时预览（未保存）</strong>
        <span class="badge tabular">
          {{ previewSummary.baseCount }} → {{ previewSummary.nextCount }} 音
        </span>
        <span v-if="previewDiff.removedCount > 0" class="badge pill-warn tabular">
          删减 -{{ previewDiff.removedCount }}
        </span>
        <span v-if="previewDiff.addedCount > 0" class="badge pill-ok tabular">
          新增/移位 +{{ previewDiff.addedCount }}
        </span>
        <span v-if="previewSummary.nextScore !== null" class="muted tabular">
          评分 {{ previewSummary.baseScore !== null ? previewSummary.baseScore.toFixed(1) : "-" }} →
          {{ previewSummary.nextScore.toFixed(1) }}
        </span>
        <span class="badge" :class="previewSummary.alreadyExists ? '' : 'pill-accent'">
          {{
            previewSummary.loading
              ? "计算中…"
              : previewSummary.alreadyExists
                ? `匹配已有版本${previewSummary.existingLabel ? `（${previewSummary.existingLabel}）` : ""}`
                : "将新建独立版本"
          }}
        </span>
      </div>
      <div class="pr-preview-actions">
        <button
          type="button"
          class="ghost btn-sm"
          @click="previewDisplayMode = previewDisplayMode === 'diff' ? 'after' : 'diff'"
        >
          {{ previewDisplayMode === "diff" ? "仅看改后谱面" : "显示删减/新增对比" }}
        </button>
        <button
          type="button"
          class="primary btn-sm"
          :disabled="saving || previewSummary.loading"
          @click="emit('applyPreview')"
        >
          应用并生成版本
        </button>
        <button type="button" class="ghost btn-sm" @click="emit('discardPreview')">
          还原当前参数
        </button>
      </div>
    </div>

    <div class="pr-add-bar">
      <div class="pr-toolbar-group">
        <template v-if="selectedIndices.size > 0">
          <span v-if="selectedEvent" class="hint-text">
            选中: {{ selectedEvent.key_id }} @ {{ selectedEvent.at_ms }} ms
          </span>
          <span v-else class="hint-text">已选 {{ selectedIndices.size }} 个音符</span>
          <label v-if="selectedEvent" class="pr-inline-time" for="pr-edit-time">
            <span>时间</span>
            <input
              id="pr-edit-time"
              type="number"
              min="0"
              step="10"
              :value="selectedEvent.at_ms"
              @change="onInlineTimeChange"
            />
          </label>
          <button type="button" class="secondary btn-sm" @click="shiftSelectedPitch(1)">
            高1音
          </button>
          <button type="button" class="secondary btn-sm" @click="shiftSelectedPitch(-1)">
            低1音
          </button>
          <button type="button" class="secondary btn-sm" @click="shiftSelectedOctave(1)">
            +1八度
          </button>
          <button type="button" class="secondary btn-sm" @click="shiftSelectedOctave(-1)">
            -1八度
          </button>
          <button
            v-if="selectedAccompanimentCount > 0"
            type="button"
            class="secondary btn-sm"
            title="仅对当前框选区域内的伴奏每 380 ms 保留一个锚点"
            @click="thinSelectedAccompaniment"
          >
            伴奏瘦身
          </button>
          <button
            v-if="selectedAccompanimentCount > 0"
            type="button"
            class="secondary btn-sm"
            title="仅清除当前框选区域内的伴奏音符"
            @click="clearSelectedAccompaniment"
          >
            清伴奏
          </button>
          <button type="button" class="secondary btn-sm" @click="nudgeSelectedTime(-50)">
            -50ms
          </button>
          <button type="button" class="secondary btn-sm" @click="nudgeSelectedTime(50)">
            +50ms
          </button>
          <button type="button" class="secondary btn-sm" @click="duplicateSelected()">
            <StudioIcon name="copy" :size="13" />
            复制
          </button>
          <button
            type="button"
            class="danger btn-sm"
            :disabled="!canDeleteSelection"
            @click="deleteSelected"
          >
            <StudioIcon name="trash" :size="13" />
            删除音符
          </button>
        </template>
        <span v-else class="muted" style="font-size: 12px">
          空白处拖拽框选，Shift/Ctrl 加选，Ctrl+A 全选，Ctrl+D 复制，Space 试听草稿，Ctrl+滚轮缩放
        </span>
      </div>

      <div class="pr-toolbar-group">
        <div class="field-inline">
          <label for="pr-new-key">键位</label>
          <select id="pr-new-key" v-model="newKeyId" class="pr-inline-select">
            <option v-for="k in orderedKeys" :key="k.key_id" :value="k.key_id">
              {{ k.binding }} ({{ k.key_id }})
            </option>
          </select>
        </div>
        <div class="field-inline">
          <label for="pr-new-time">时间 ms</label>
          <input
            id="pr-new-time"
            v-model.number="newAtMs"
            type="number"
            min="0"
            step="50"
            class="pr-inline-number"
          />
        </div>
        <button type="button" class="secondary btn-sm" @click="addNote">
          <StudioIcon name="plus" :size="13" />
          添加音符
        </button>
      </div>
    </div>

    <div class="pr-viewport-wrap">
      <button
        v-if="(draftPlaying || isPlaying) && followDetached"
        id="pr-return-playhead-btn"
        type="button"
        class="primary btn-sm pr-return-playhead-btn"
        title="快捷键 F：回到当前播放点并恢复自动跟随"
        @click="returnToPlayhead"
      >
        <template v-if="playheadDirection === 'left'">
          ← 回到播放点 ({{ formatClockTime(activePlayheadMs) }})
        </template>
        <template v-else-if="playheadDirection === 'right'">
          回到播放点 ({{ formatClockTime(activePlayheadMs) }}) →
        </template>
        <template v-else>
          回到播放点 ({{ formatClockTime(activePlayheadMs) }})
        </template>
      </button>

      <div
        ref="scrollEl"
        class="pr-scroll"
        role="region"
        aria-label="MIDI Piano Roll 可视化编辑器"
        @pointerdown="onScrollPointerDown"
        @scroll="onTimelineScroll"
        @wheel="onScrollWheel"
      >
        <div class="pr-canvas" :style="{ width: `${timelineWidthPx + KEY_COLUMN_PX}px` }">
        <div class="pr-ruler" title="点击时间标尺定位试听播放头">
          <div class="pr-ruler-corner">键位 / 时间</div>
          <div class="pr-ruler-track" @click="onRulerClick">
            <span
              v-for="tick in rulerTicks"
              :key="tick.ms"
              class="pr-tick"
              :class="{ 'is-minor': !tick.major }"
              :style="{ left: `${tick.leftPx}px` }"
            >
              {{ tick.label }}
            </span>
            <div
              v-if="showPlayhead"
              class="pr-playhead"
              :style="{ left: `${playheadLeftPx}px` }"
            />
          </div>
        </div>

        <div ref="rowsWrapEl" class="pr-rows-wrap" @pointerdown="onRowsPointerDown">
          <div
            v-if="marqueeRect"
            class="pr-marquee"
            :style="{
              left: `${marqueeRect.left + KEY_COLUMN_PX}px`,
              top: `${marqueeRect.top}px`,
              width: `${marqueeRect.width}px`,
              height: `${marqueeRect.height}px`,
            }"
          />
          <div
            v-for="(k, rowIdx) in orderedKeys"
            :key="k.key_id"
            class="pr-row"
            :class="{ 'octave-break': isOctaveBreak(rowIdx) }"
          >
            <div
              class="pr-key-label"
              :class="`zone-${k.row}`"
              :title="`点击试听 ${k.binding} (${k.key_id})`"
              @click="auditionKey(k)"
            >
              <span class="pr-key-bind">{{ k.binding }}</span>
              <span class="pr-key-id">{{ k.key_id }}</span>
            </div>
            <div
              class="pr-lane"
              :style="{ backgroundSize: snapBackgroundSize }"
              @click="onLaneClick(k, $event, false)"
              @dblclick="onLaneClick(k, $event, true)"
            >
              <div
                v-if="showPlayhead"
                class="pr-playhead"
                :style="{ left: `${playheadLeftPx}px` }"
              />
              <template v-for="item in eventsByKey[k.key_id] ?? []" :key="`${item.idx}-${item.ev.key_id}-${item.ev.at_ms}`">
                <button
                  v-if="!(previewDiff && previewDisplayMode === 'after' && previewDiff.removedBaseIndices.has(item.idx))"
                  type="button"
                  class="pr-note"
                  :class="[
                    trackColorClass(trackSlotFor(item.ev)),
                    {
                      selected: selectedIndices.has(item.idx),
                      dragging: isNoteDragging(item.idx),
                      'is-adjusted': (item.ev.adjustments?.length ?? 0) > 0,
                      'is-dimmed': !isTrackAudible(item.ev.source_track ?? 0),
                      'is-ghost-removed':
                        Boolean(previewDiff) &&
                        previewDisplayMode === 'diff' &&
                        previewDiff!.removedBaseIndices.has(item.idx),
                    },
                  ]"
                  :style="{
                    left: `${Math.round(item.ev.at_ms * pxPerMs)}px`,
                    width: `${noteWidthPx(item.ev)}px`,
                  }"
                  :title="formatNoteTooltip(k, item.ev)"
                  @pointerdown="onNotePointerDown(item.idx, k.key_id, item.ev, $event)"
                  @contextmenu="onNoteContextMenu(item.idx, $event)"
                >
                  {{ k.binding }}
                </button>
              </template>
              <span
                v-for="(ghost, gIdx) in addedGhostsByKey[k.key_id] ?? []"
                :key="`ghost-${gIdx}-${ghost.key_id}-${ghost.at_ms}`"
                class="pr-note-ghost-added"
                :class="{ 'is-dimmed': !isTrackAudible(ghost.source_track ?? 0) }"
                :style="{
                  left: `${Math.round(ghost.at_ms * pxPerMs)}px`,
                  width: `${noteWidthPx(ghost)}px`,
                }"
                :title="`预览新增/移位：${k.binding} @ ${ghost.at_ms} ms`"
              >
                {{ k.binding }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
    </div>

    <div
      v-if="contextMenu"
      class="pr-context-menu"
      role="menu"
      aria-label="音符快捷操作"
      :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
    >
      <button type="button" role="menuitem" @click="runContextAction('up')">
        上移一个琴键
      </button>
      <button type="button" role="menuitem" @click="runContextAction('down')">
        下移一个琴键
      </button>
      <button type="button" role="menuitem" @click="runContextAction('oct_up')">
        移高一个八度 (+12)
      </button>
      <button type="button" role="menuitem" @click="runContextAction('oct_down')">
        移低一个八度 (-12)
      </button>
      <button type="button" role="menuitem" @click="runContextAction('dup')">
        向后复制 (+250ms)
      </button>
      <button
        type="button"
        role="menuitem"
        :disabled="!canDeleteSelection"
        @click="runContextAction('del')"
      >
        删除该音符
      </button>
    </div>
  </div>
</template>
