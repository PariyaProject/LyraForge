<script setup lang="ts">
import StudioIcon from "./StudioIcon.vue";
import type { LyraStore } from "../composables/useLyraStore";

const props = defineProps<{ store: LyraStore; open: boolean }>();
const emit = defineEmits<{ "update:open": [value: boolean] }>();

async function selectItem(arrangementId: string): Promise<void> {
  await props.store.selectArrangement(arrangementId);
  emit("update:open", false);
}
</script>

<template>
  <div v-if="open" class="queue-backdrop" @click="emit('update:open', false)"></div>
  <aside v-if="open" class="queue-drawer" aria-label="播放队列">
    <header class="queue-drawer-header">
      <h2>播放队列</h2>
      <button class="ghost" type="button" @click="emit('update:open', false)">
        <StudioIcon name="check" :size="14" />
        关闭
      </button>
    </header>

    <p class="muted" style="margin: 0">
      {{ store.queue.value.items.length }} 首
      <template v-if="store.queue.value.items.length > 0">
        · 当前第 {{ store.queue.value.index + 1 }} 首
      </template>
    </p>

    <ol v-if="store.queue.value.items.length > 0" class="queue-list">
      <li
        v-for="(item, index) in store.queue.value.items"
        :key="item.arrangement_id"
        :class="{ current: index === store.queue.value.index }"
        @click="selectItem(item.arrangement_id)"
      >
        <span class="queue-index">{{ index + 1 }}</span>
        <span class="queue-label">{{ item.label }}</span>
        <span v-if="index === store.queue.value.index" class="pill pill-ok">当前</span>
      </li>
    </ol>
    <p v-else class="muted" style="margin: 0">
      队列为空：在编曲工作室点击「加入播放队列」。
    </p>

    <div class="queue-actions">
      <button class="secondary" type="button" @click="store.handleQueueStep(-1)">
        上一首
      </button>
      <button class="secondary" type="button" @click="store.handleQueueStep(1)">
        下一首
      </button>
      <button class="ghost" type="button" @click="store.handleClearQueue">
        清空
      </button>
    </div>
  </aside>
</template>

<style scoped>
.queue-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: rgb(0 0 0 / 0.35);
}

.queue-drawer {
  position: fixed;
  inset-block: 0;
  inset-inline-end: 0;
  z-index: 41;
  display: flex;
  flex-direction: column;
  gap: 12px;
  inline-size: min(360px, 92vw);
  padding: 16px;
  overflow-y: auto;
  background: var(--bg-panel);
  border-inline-start: 1px solid var(--border-subtle);
  box-shadow: -8px 0 24px rgb(0 0 0 / 0.25);
}

.queue-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.queue-drawer-header h2 {
  margin: 0;
  font-size: 1rem;
}

.queue-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.queue-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  cursor: pointer;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
}

.queue-list li.current {
  border-color: var(--accent-primary);
}

.queue-index {
  inline-size: 18px;
  text-align: end;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.queue-label {
  flex: 1;
  min-inline-size: 0;
  overflow-wrap: anywhere;
}

.queue-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-block-start: auto;
}
</style>
