<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { PerformanceEventItem, ProfileKeyDef } from "../api";

const props = defineProps<{
  keys: ProfileKeyDef[];
  events: PerformanceEventItem[];
  saving?: boolean;
}>();

const emit = defineEmits<{
  save: [payload: { events: PerformanceEventItem[]; label: string }];
}>();

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

const workingEvents = ref<PerformanceEventItem[]>(cloneEvents(props.events));
const history = ref<PerformanceEventItem[][]>([cloneEvents(props.events)]);
const historyIndex = ref(0);
const selectedIndex = ref<number | null>(workingEvents.value.length > 0 ? 0 : null);
const newKeyId = ref("mid_1");
const newAtMs = ref(0);
const versionLabel = ref("Piano Roll 编辑版");

watch(
  () => props.events,
  (next) => {
    const initial = cloneEvents(next);
    workingEvents.value = initial;
    history.value = [cloneEvents(initial)];
    historyIndex.value = 0;
    selectedIndex.value = initial.length > 0 ? 0 : null;
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

const totalDurationMs = computed(() => {
  if (workingEvents.value.length === 0) return 2000;
  return Math.max(
    2000,
    ...workingEvents.value.map((e) => e.at_ms + Math.max(40, e.hold_ms)),
  );
});

const pxPerMs = 0.08;
const timelineWidthPx = computed(() =>
  Math.max(540, Math.min(2800, Math.ceil(totalDurationMs.value * pxPerMs) + 60)),
);

const eventsByKey = computed(() => {
  const map: Record<string, Array<{ idx: number; ev: PerformanceEventItem }>> = {};
  workingEvents.value.forEach((ev, idx) => {
    if (!map[ev.key_id]) map[ev.key_id] = [];
    map[ev.key_id].push({ idx, ev });
  });
  return map;
});

const selectedEvent = computed(() => {
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
}

function redo() {
  if (!canRedo.value) return;
  historyIndex.value += 1;
  workingEvents.value = cloneEvents(history.value[historyIndex.value]);
  selectedIndex.value = workingEvents.value.length > 0 ? 0 : null;
}

function shiftSelectedPitch(step: -1 | 1) {
  if (selectedIndex.value === null) return;
  const ev = workingEvents.value[selectedIndex.value];
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
  const next = workingEvents.value.map((item, idx) =>
    idx === selectedIndex.value ? updated : item,
  );
  commitChange(next, updated);
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

function deleteSelected() {
  if (selectedIndex.value === null || workingEvents.value.length <= 1) return;
  const next = workingEvents.value.filter((_, idx) => idx !== selectedIndex.value);
  commitChange(next, null);
}

function addNote() {
  const key = props.keys.find((k) => k.key_id === newKeyId.value);
  if (!key) return;
  const atMs = Math.max(0, Math.round(Number(newAtMs.value) || 0));
  const created: PerformanceEventItem = {
    at_ms: atMs,
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

function emitSave() {
  if (workingEvents.value.length === 0) return;
  emit("save", {
    events: cloneEvents(workingEvents.value),
    label: versionLabel.value.trim() || "Piano Roll 编辑版",
  });
}
</script>

<template>
  <div class="piano-roll-editor">
    <div class="pr-toolbar">
      <div class="button-row">
        <button type="button" class="btn-secondary" :disabled="!canUndo" @click="undo">
          撤销
        </button>
        <button type="button" class="btn-secondary" :disabled="!canRedo" @click="redo">
          重做
        </button>
        <span class="badge">
          {{ isDirty ? "有未保存修改" : "已同步" }} · {{ workingEvents.length }} 音符
        </span>
      </div>

      <div class="button-row" v-if="selectedEvent">
        <span class="hint-text">
          选中: {{ selectedEvent.key_id }} @ {{ selectedEvent.at_ms }} ms
        </span>
        <button type="button" class="btn-secondary" @click="shiftSelectedPitch(1)">
          高1音
        </button>
        <button type="button" class="btn-secondary" @click="shiftSelectedPitch(-1)">
          低1音
        </button>
        <button type="button" class="btn-secondary" @click="nudgeSelectedTime(-50)">
          -50ms
        </button>
        <button type="button" class="btn-secondary" @click="nudgeSelectedTime(50)">
          +50ms
        </button>
        <button
          type="button"
          class="btn-danger"
          :disabled="workingEvents.length <= 1"
          @click="deleteSelected"
        >
          删除音符
        </button>
      </div>
    </div>

    <div class="pr-add-bar">
      <div class="field-inline">
        <label for="pr-new-key">键位</label>
        <select id="pr-new-key" v-model="newKeyId">
          <option v-for="k in orderedKeys" :key="k.key_id" :value="k.key_id">
            {{ k.binding }} ({{ k.key_id }})
          </option>
        </select>
      </div>
      <div class="field-inline">
        <label for="pr-new-time">时间 (ms)</label>
        <input id="pr-new-time" v-model.number="newAtMs" type="number" min="0" step="50" />
      </div>
      <button type="button" class="btn-secondary" @click="addNote">添加音符</button>
      <div class="field-inline pr-label-field">
        <label for="pr-version-label">版本名称</label>
        <input id="pr-version-label" v-model="versionLabel" type="text" maxlength="60" />
      </div>
      <button
        type="button"
        class="btn-primary"
        :disabled="saving || workingEvents.length === 0"
        @click="emitSave"
      >
        {{ saving ? "保存中..." : "保存为新版本" }}
      </button>
    </div>

    <div class="pr-scroll" role="region" aria-label="MIDI Piano Roll 可视化编辑器">
      <div class="pr-canvas" :style="{ width: `${timelineWidthPx + 96}px` }">
        <div v-for="k in orderedKeys" :key="k.key_id" class="pr-row">
          <span class="pr-key-label">{{ k.binding }} · {{ k.key_id }}</span>
          <div class="pr-lane">
            <button
              v-for="item in eventsByKey[k.key_id] ?? []"
              :key="`${item.idx}-${item.ev.at_ms}`"
              type="button"
              class="pr-note"
              :class="{ selected: selectedIndex === item.idx }"
              :style="{
                left: `${Math.round(item.ev.at_ms * pxPerMs)}px`,
                width: `${Math.max(14, Math.round(item.ev.hold_ms * pxPerMs))}px`,
              }"
              :title="`${k.binding} @ ${item.ev.at_ms}ms (${item.ev.hold_ms}ms)`"
              @click="selectedIndex = item.idx"
            >
              {{ k.binding }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
