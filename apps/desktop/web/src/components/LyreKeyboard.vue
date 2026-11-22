<script setup lang="ts">
import { computed } from "vue";
import type { ProfileKeyDef } from "../api";

const props = defineProps<{
  keys: ProfileKeyDef[];
  eventCounts: Record<string, number>;
}>();

const ROW_ORDER: Array<{ id: string; label: string }> = [
  { id: "high", label: "高音区" },
  { id: "mid", label: "中音区" },
  { id: "low", label: "低音区" },
];

const rows = computed(() =>
  ROW_ORDER.map((row) => ({
    ...row,
    items: props.keys
      .filter((k) => k.row === row.id)
      .sort((a, b) => (a.degree ?? a.pitch) - (b.degree ?? b.pitch)),
  })).filter((r) => r.items.length > 0),
);
</script>

<template>
  <div class="lyre-grid" aria-label="风物之诗琴 21 键映射预览">
    <div v-for="row in rows" :key="row.id" class="lyre-row">
      <span class="lyre-row-label">{{ row.label }}</span>
      <div
        v-for="k in row.items"
        :key="k.key_id"
        class="lyre-key"
        :class="{ active: (eventCounts[k.key_id] ?? 0) > 0 }"
      >
        <span class="bind">{{ k.binding }}</span>
        <span class="degree">{{ k.degree ?? "-" }}</span>
        <span class="count">
          {{ (eventCounts[k.key_id] ?? 0) > 0 ? `${eventCounts[k.key_id]} 音` : "—" }}
        </span>
      </div>
    </div>
  </div>
</template>
