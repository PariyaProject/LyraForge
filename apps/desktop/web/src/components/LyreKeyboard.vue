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

const maxCount = computed(() =>
  Math.max(1, ...props.keys.map((k) => props.eventCounts[k.key_id] ?? 0)),
);

const rows = computed(() =>
  ROW_ORDER.map((row) => ({
    ...row,
    items: props.keys
      .filter((k) => k.row === row.id)
      .sort((a, b) => (a.degree ?? a.pitch) - (b.degree ?? b.pitch)),
  })).filter((r) => r.items.length > 0),
);

function keyIntensityStyle(keyId: string): Record<string, string> {
  const count = props.eventCounts[keyId] ?? 0;
  if (count <= 0) return {};
  const ratio = Math.min(1, count / maxCount.value);
  const alpha = (0.12 + ratio * 0.24).toFixed(2);
  return { background: `rgba(56, 189, 248, ${alpha})` };
}
</script>

<template>
  <div class="lyre-grid" role="region" aria-label="21 键映射与音符密度分布">
    <div v-for="row in rows" :key="row.id" class="lyre-row">
      <span class="lyre-row-label">{{ row.label }}</span>
      <div
        v-for="k in row.items"
        :key="k.key_id"
        class="lyre-key"
        :class="{ active: (eventCounts[k.key_id] ?? 0) > 0 }"
        :style="keyIntensityStyle(k.key_id)"
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
