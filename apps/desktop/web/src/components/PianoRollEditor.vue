<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { PerformanceEventItem, ProfileKeyDef } from "../api";
import StudioIcon from "./StudioIcon.vue";

const props = defineProps<{
  keys: ProfileKeyDef[];
  events: PerformanceEventItem[];
  saving?: boolean;
  playheadMs?: number;
  isPlaying?: boolean;
}>();

const emit = defineEmits<{
  save: [payload: { events: PerformanceEventItem[]; label: string }];
  seek: [ms: number];
}>();

const ROW_HEIGHT_PX = 26;
const BASE_PX_PER_MS = 0.08;
const KEY_COLUMN_PX = 112;

function cloneEvents(items: PerformanceEventItem[]): PerformanceEventItem[] {
  return items
    .map((e) => ({
      ...e,
      adjustments: e.adjustments ? [...e.adjustments] : [],
    }))
    .sort((a, b) => a.at_ms - b.at_ms || a.mapped_pitch - b.mapped_pitch || a.key_id.localeCompare(b.key_id));
}

const orderedKeys = computed(() =>
  [...props.keys].sort((a, b) => b.pitch - a.pitch),
);

const scrollEl = ref<HTMLElement | null>(null);
const workingEvents = ref<PerformanceEventItem[]>(cloneEvents(props.events));
const history = ref<PerformanceEventItem[][]>([cloneEvents(props.events)]);
const historyIndex = ref(0);
const selectedIndex = ref<number | null>(workingEvents.value.length > 0 ? 0 : null);
const newKeyId = ref("mid_1");
const newAtMs = ref(0);
const versionLabel = ref("Piano Roll 编辑版");

// DAW toolbar state
const zoomPct = ref(100);
const snapMs = ref(50);
const editorMode = ref<"select" | "add">("select");

// Context menu state
const contextMenu = ref<{ idx: number; x: number; y: number } | null>(null);

// Live drag preview state
const dragState = ref<{
  idx: number;
  startX: number;
  startY: number;
  origAtMs: number;
  origRowIdx: number;
  previewAtMs: number;
  previewRowIdx: number;
  moved: boolean;
} | null>(null);

function scrollToMedianPitch(): void {
  const el = scrollEl.value;
  if (!el || orderedKeys.value.length === 0 || workingEvents.value.length === 0) return;
  const rowMap = new Map<string, number>();
  orderedKeys.value.forEach((k, i) => rowMap.set(k.key_id, i));
  const rowIndices = workingEvents.value
    .map((e) => rowMap.get(e.key_id))
    .filter((idx): idx is number => idx !== undefined)
    .sort((a, b) => a - b);
  if (rowIndices.length === 0) return;
  const medianRow = rowIndices[Math.floor(rowIndices.length / 2)];
  const targetTop = Math.max(0, medianRow * ROW_HEIGHT_PX - el.clientHeight / 2 + ROW_HEIGHT_PX);
  el.scrollTop = targetTop;
}

watch(
  () => props.events,
  (next) => {
    const initial = cloneEvents(next);
    workingEvents.value = initial;
    history.value = [cloneEvents(initial)];
    historyIndex.value = 0;
    selectedIndex.value = initial.length > 0 ? 0 : null;
    contextMenu.value = null;
    void nextTick(scrollToMedianPitch);
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

const totalDurationMs = computed(() => {
  if (workingEvents.value.length === 0) return 2400;
  return Math.max(
    2400,
    ...workingEvents.value.map((e) => e.at_ms + Math.max(40, e.hold_ms)),
  );
});

const timelineWidthPx = computed(() =>
  Math.max(540, Math.min(4800, Math.ceil(totalDurationMs.value * pxPerMs.value) + 80)),
);

const playheadLeftPx = computed(() => {
  const ms = Math.max(0, props.playheadMs ?? 0);
  return Math.round(ms * pxPerMs.value);
});

const showPlayhead = computed(() => Boolean(props.isPlaying) || (props.playheadMs ?? 0) > 0);

const rulerTicks = computed(() => {
  const stepMs = zoomPct.value >= 160 ? 250 : 500;
  const maxMs = Math.ceil(totalDurationMs.value / stepMs) * stepMs;
  const ticks: Array<{ ms: number; label: string; leftPx: number; major: boolean }> = [];
  for (let ms = 0; ms <= maxMs; ms += stepMs) {
    const major = ms % 1000 === 0;
    let label = "";
    if (major) {
      label = `${ms / 1000}s`;
    } else if (zoomPct.value >= 125) {
      label = `${Number((ms / 1000).toFixed(2))}s`;
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
  workingEvents.value.forEach((ev, idx) => {
    const d = dragState.value;
    if (d && d.idx === idx) {
      const targetKey = orderedKeys.value[d.previewRowIdx] ?? orderedKeys.value[0];
      const kid = targetKey ? targetKey.key_id : ev.key_id;
      if (!map[kid]) map[kid] = [];
      map[kid].push({
        idx,
        ev: { ...ev, key_id: kid, at_ms: d.previewAtMs },
      });
      return;
    }
    if (!map[ev.key_id]) map[ev.key_id] = [];
    map[ev.key_id].push({ idx, ev });
  });
  return map;
});

const selectedEvent = computed(() => {
  const d = dragState.value;
  if (d) {
    const k = orderedKeys.value[d.previewRowIdx];
    const base = workingEvents.value[d.idx];
    if (base && k) {
      return { ...base, key_id: k.key_id, at_ms: d.previewAtMs };
    }
  }
  if (selectedIndex.value === null) return null;
  return workingEvents.value[selectedIndex.value] ?? null;
});

function commitChange(nextRaw: PerformanceEventItem[], selectItem?: PerformanceEventItem | null) {
  const sorted = cloneEvents(nextRaw);
  const sliced = history.value.slice(0, historyIndex.value + 1);
  sliced.push(cloneEvents(sorted));
  history.value = sliced;
  historyIndex.value = sliced.length - 1;
  workingEvents.value = sorted;
  if (selectItem) {
    const found = sorted.findIndex(
      (e) => e.at_ms === selectItem.at_ms && e.key_id === selectItem.key_id,
    );
    selectedIndex.value = found >= 0 ? found : sorted.length > 0 ? 0 : null;
  } else {
    selectedIndex.value = sorted.length > 0 ? Math.min(selectedIndex.value ?? 0, sorted.length - 1) : null;
  }
}

function undo() {
  if (!canUndo.value) return;
  historyIndex.value -= 1;
  workingEvents.value = cloneEvents(history.value[historyIndex.value]);
  selectedIndex.value = workingEvents.value.length > 0 ? 0 : null;
  contextMenu.value = null;
}

function redo() {
  if (!canRedo.value) return;
  historyIndex.value += 1;
  workingEvents.value = cloneEvents(history.value[historyIndex.value]);
  selectedIndex.value = workingEvents.value.length > 0 ? 0 : null;
  contextMenu.value = null;
}

function shiftNotePitch(idx: number, step: -1 | 1) {
  const ev = workingEvents.value[idx];
  if (!ev) return;
  const asc = [...props.keys].sort((a, b) => a.pitch - b.pitch);
  const pos = asc.findIndex((k) => k.key_id === ev.key_id);
  const nextPos = pos + step;
  if (pos < 0 || nextPos < 0 || nextPos >= asc.length) return;
  const targetKey = asc[nextPos];
  const updated: PerformanceEventItem = {
    ...ev,
    key_id: targetKey.key_id,
    mapped_pitch: targetKey.pitch,
  };
  const next = workingEvents.value.map((item, i) => (i === idx ? updated : item));
  commitChange(next, updated);
}

function shiftSelectedPitch(step: -1 | 1) {
  if (selectedIndex.value === null) return;
  shiftNotePitch(selectedIndex.value, step);
}

function nudgeSelectedTime(deltaMs: number) {
  if (selectedIndex.value === null) return;
  const ev = workingEvents.value[selectedIndex.value];
  if (!ev) return;
  const updated: PerformanceEventItem = {
    ...ev,
    at_ms: Math.max(0, ev.at_ms + deltaMs),
  };
  const next = workingEvents.value.map((item, idx) =>
    idx === selectedIndex.value ? updated : item,
  );
  commitChange(next, updated);
}

function duplicateNote(idx: number, offsetMs = 250) {
  const ev = workingEvents.value[idx];
  if (!ev) return;
  const copy: PerformanceEventItem = {
    ...ev,
    at_ms: Math.max(0, ev.at_ms + offsetMs),
    adjustments: ev.adjustments ? [...ev.adjustments] : [],
  };
  commitChange([...workingEvents.value, copy], copy);
}

function deleteAtIndex(idx: number) {
  if (workingEvents.value.length <= 1) return;
  const next = workingEvents.value.filter((_, i) => i !== idx);
  commitChange(next, null);
}

function deleteSelected() {
  if (selectedIndex.value === null || workingEvents.value.length <= 1) return;
  deleteAtIndex(selectedIndex.value);
}

function createNoteFor(key: ProfileKeyDef, atMs: number) {
  const created: PerformanceEventItem = {
    at_ms: Math.max(0, Math.round(atMs)),
    key_id: key.key_id,
    action: "tap",
    hold_ms: 40,
    source_pitch: key.pitch,
    mapped_pitch: key.pitch,
    source_track: 0,
    source_channel: 0,
    velocity: 96,
    adjustments: [],
  };
  commitChange([...workingEvents.value, created], created);
}

function addNote() {
  const key = props.keys.find((k) => k.key_id === newKeyId.value);
  if (!key) return;
  createNoteFor(key, Number(newAtMs.value) || 0);
}

function onLaneClick(key: ProfileKeyDef, event: MouseEvent, forceAdd = false) {
  contextMenu.value = null;
  if (!forceAdd && editorMode.value !== "add") return;
  const target = event.target as HTMLElement;
  if (target.closest(".pr-note")) return;
  const lane = event.currentTarget as HTMLElement;
  const rect = lane.getBoundingClientRect();
  const relX = Math.max(0, event.clientX - rect.left);
  const rawMs = relX / pxPerMs.value;
  createNoteFor(key, snapTime(rawMs));
}

function onRulerClick(event: MouseEvent) {
  const track = event.currentTarget as HTMLElement;
  const rect = track.getBoundingClientRect();
  const relX = Math.max(0, event.clientX - rect.left);
  const ms = Math.max(0, Math.round(relX / pxPerMs.value));
  emit("seek", ms);
}

function onNoteContextMenu(idx: number, event: MouseEvent) {
  event.preventDefault();
  selectedIndex.value = idx;
  const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
  const vh = typeof window !== "undefined" ? window.innerHeight : 720;
  contextMenu.value = {
    idx,
    x: Math.min(event.clientX, vw - 180),
    y: Math.min(event.clientY, vh - 160),
  };
}

function runContextAction(action: "up" | "down" | "dup" | "del") {
  const menu = contextMenu.value;
  contextMenu.value = null;
  if (!menu) return;
  if (action === "up") shiftNotePitch(menu.idx, 1);
  else if (action === "down") shiftNotePitch(menu.idx, -1);
  else if (action === "dup") duplicateNote(menu.idx, 250);
  else if (action === "del") deleteAtIndex(menu.idx);
}

function onWindowPointerMove(ev: PointerEvent) {
  const d = dragState.value;
  if (!d) return;
  const dx = ev.clientX - d.startX;
  const dy = ev.clientY - d.startY;
  if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
    d.moved = true;
  }
  const nextAtMs = snapTime(d.origAtMs + dx / pxPerMs.value);
  const rowDelta = Math.round(dy / ROW_HEIGHT_PX);
  const nextRow = Math.max(0, Math.min(orderedKeys.value.length - 1, d.origRowIdx + rowDelta));
  d.previewAtMs = nextAtMs;
  d.previewRowIdx = nextRow;
}

function stopDragListeners() {
  if (typeof window !== "undefined") {
    window.removeEventListener("pointermove", onWindowPointerMove);
    window.removeEventListener("pointerup", onWindowPointerUp);
  }
}

function onWindowPointerUp() {
  stopDragListeners();
  const d = dragState.value;
  dragState.value = null;
  if (!d || !d.moved) return;
  const ev = workingEvents.value[d.idx];
  const targetKey = orderedKeys.value[d.previewRowIdx];
  if (!ev || !targetKey) return;
  if (ev.at_ms === d.previewAtMs && ev.key_id === targetKey.key_id) return;
  const updated: PerformanceEventItem = {
    ...ev,
    at_ms: d.previewAtMs,
    key_id: targetKey.key_id,
    mapped_pitch: targetKey.pitch,
  };
  const next = workingEvents.value.map((item, i) => (i === d.idx ? updated : item));
  commitChange(next, updated);
}

function onNotePointerDown(idx: number, keyId: string, evItem: PerformanceEventItem, event: PointerEvent) {
  contextMenu.value = null;
  selectedIndex.value = idx;
  if (event.button !== 0) return;
  const rowIdx = Math.max(
    0,
    orderedKeys.value.findIndex((k) => k.key_id === keyId),
  );
  dragState.value = {
    idx,
    startX: event.clientX,
    startY: event.clientY,
    origAtMs: evItem.at_ms,
    origRowIdx: rowIdx,
    previewAtMs: evItem.at_ms,
    previewRowIdx: rowIdx,
    moved: false,
  };
  if (typeof window !== "undefined") {
    window.addEventListener("pointermove", onWindowPointerMove);
    window.addEventListener("pointerup", onWindowPointerUp);
  }
}

function onEditorKeydown(event: KeyboardEvent) {
  const tag = (event.target as HTMLElement | null)?.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
  if (event.key === "Escape" && contextMenu.value) {
    contextMenu.value = null;
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) redo();
    else undo();
    return;
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    shiftSelectedPitch(1);
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    shiftSelectedPitch(-1);
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    nudgeSelectedTime(-(snapMs.value || 50));
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    nudgeSelectedTime(snapMs.value || 50);
  } else if (event.key === "Delete" || event.key === "Backspace") {
    event.preventDefault();
    deleteSelected();
  }
}

function onGlobalClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null;
  if (contextMenu.value && !target?.closest(".pr-context-menu")) {
    contextMenu.value = null;
  }
}

function emitSave() {
  if (workingEvents.value.length === 0) return;
  emit("save", {
    events: cloneEvents(workingEvents.value),
    label: versionLabel.value.trim() || "Piano Roll 编辑版",
  });
}

onMounted(() => {
  void nextTick(scrollToMedianPitch);
  if (typeof window !== "undefined") {
    window.addEventListener("mousedown", onGlobalClick);
  }
});

onBeforeUnmount(() => {
  stopDragListeners();
  if (typeof window !== "undefined") {
    window.removeEventListener("mousedown", onGlobalClick);
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
            @click="zoomPct = Math.max(50, zoomPct - 25)"
          >
            <StudioIcon name="minus" :size="13" />
          </button>
          <span class="badge tabular">{{ zoomPct }}%</span>
          <button
            type="button"
            class="ghost btn-sm"
            aria-label="放大时间轴"
            @click="zoomPct = Math.min(250, zoomPct + 25)"
          >
            <StudioIcon name="plus" :size="13" />
          </button>
          <label for="pr-snap-select" class="muted" style="font-size: 12px">吸附</label>
          <select id="pr-snap-select" v-model.number="snapMs" class="pr-inline-select">
            <option :value="0">无吸附</option>
            <option :value="25">25ms</option>
            <option :value="50">50ms</option>
            <option :value="100">100ms</option>
            <option :value="250">250ms</option>
          </select>
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

    <div class="pr-add-bar">
      <div class="pr-toolbar-group">
        <template v-if="selectedEvent">
          <span class="hint-text">
            选中: {{ selectedEvent.key_id }} @ {{ selectedEvent.at_ms }} ms
          </span>
          <button type="button" class="secondary btn-sm" @click="shiftSelectedPitch(1)">
            高1音
          </button>
          <button type="button" class="secondary btn-sm" @click="shiftSelectedPitch(-1)">
            低1音
          </button>
          <button type="button" class="secondary btn-sm" @click="nudgeSelectedTime(-50)">
            -50ms
          </button>
          <button type="button" class="secondary btn-sm" @click="nudgeSelectedTime(50)">
            +50ms
          </button>
          <button
            type="button"
            class="danger btn-sm"
            :disabled="workingEvents.length <= 1"
            @click="deleteSelected"
          >
            <StudioIcon name="trash" :size="13" />
            删除音符
          </button>
        </template>
        <span v-else class="muted" style="font-size: 12px">
          点击音符选中并拖拽，右键打开快捷菜单，双击音轨或切换「点击添加」插入音符
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

    <div
      ref="scrollEl"
      class="pr-scroll"
      role="region"
      aria-label="MIDI Piano Roll 可视化编辑器"
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

        <div
          v-for="(k, rowIdx) in orderedKeys"
          :key="k.key_id"
          class="pr-row"
          :class="{ 'octave-break': isOctaveBreak(rowIdx) }"
        >
          <div
            class="pr-key-label"
            :class="`zone-${k.row}`"
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
            <button
              v-for="item in eventsByKey[k.key_id] ?? []"
              :key="`${item.idx}-${item.ev.key_id}-${item.ev.at_ms}`"
              type="button"
              class="pr-note"
              :class="{
                selected: selectedIndex === item.idx,
                dragging: dragState?.idx === item.idx && dragState?.moved,
                'is-adjusted': (item.ev.adjustments?.length ?? 0) > 0,
              }"
              :style="{
                left: `${Math.round(item.ev.at_ms * pxPerMs)}px`,
                width: `${Math.max(24, Math.round(Math.max(80, item.ev.hold_ms) * pxPerMs))}px`,
              }"
              :title="`${k.binding} (${k.key_id}) @ ${item.ev.at_ms} ms`"
              @pointerdown="onNotePointerDown(item.idx, k.key_id, item.ev, $event)"
              @contextmenu="onNoteContextMenu(item.idx, $event)"
            >
              {{ k.binding }}
            </button>
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
      <button type="button" role="menuitem" @click="runContextAction('dup')">
        向后复制 (+250ms)
      </button>
      <button
        type="button"
        role="menuitem"
        :disabled="workingEvents.length <= 1"
        @click="runContextAction('del')"
      >
        删除该音符
      </button>
    </div>
  </div>
</template>
