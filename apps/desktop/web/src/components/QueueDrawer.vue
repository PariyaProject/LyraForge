<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import StudioIcon from "./StudioIcon.vue";
import type { LyraStore } from "../composables/useLyraStore";

const props = defineProps<{ store: LyraStore; open: boolean }>();
const emit = defineEmits<{ "update:open": [value: boolean] }>();

async function selectItem(arrangementId: string): Promise<void> {
  await props.store.selectArrangement(arrangementId);
  emit("update:open", false);
}

function onWindowKeydown(event: KeyboardEvent): void {
  if (props.open && event.key === "Escape") {
    emit("update:open", false);
  }
}

onMounted(() => {
  if (typeof window !== "undefined") {
    window.addEventListener("keydown", onWindowKeydown);
  }
});

onBeforeUnmount(() => {
  if (typeof window !== "undefined") {
    window.removeEventListener("keydown", onWindowKeydown);
  }
});
</script>

<template>
  <div v-if="open" class="queue-backdrop" @click="emit('update:open', false)"></div>
  <aside
    v-if="open"
    class="queue-drawer"
    role="dialog"
    aria-modal="true"
    aria-label="播放队列"
  >
    <header class="queue-drawer-header">
      <div>
        <h2>播放队列</h2>
        <div class="meta-row">
          <span>{{ store.queue.value.items.length }} 首曲目</span>
          <span v-if="store.queue.value.items.length > 0">
            第 {{ store.queue.value.index + 1 }} 首
          </span>
        </div>
      </div>
      <button
        class="ghost btn-sm"
        type="button"
        aria-label="关闭队列"
        @click="emit('update:open', false)"
      >
        <StudioIcon name="x" :size="15" />
        关闭
      </button>
    </header>

    <ol v-if="store.queue.value.items.length > 0" class="queue-list">
      <li
        v-for="(item, index) in store.queue.value.items"
        :key="item.arrangement_id"
      >
        <button
          type="button"
          class="queue-row-btn"
          :class="{ current: index === store.queue.value.index }"
          @click="selectItem(item.arrangement_id)"
        >
          <span class="queue-index">{{ index + 1 }}</span>
          <span class="queue-label">{{ item.label }}</span>
          <span v-if="index === store.queue.value.index" class="pill pill-accent">当前</span>
        </button>
      </li>
    </ol>
    <div v-else class="empty-state">
      <StudioIcon name="list-music" :size="20" />
      <p style="margin: 0">
        队列为空，可在编曲工作室点击「加入播放队列」。
      </p>
    </div>

    <div class="queue-actions">
      <button class="secondary" type="button" @click="store.handleQueueStep(-1)">
        <StudioIcon name="skip-back" :size="14" />
        上一首
      </button>
      <button class="secondary" type="button" @click="store.handleQueueStep(1)">
        下一首
        <StudioIcon name="skip-forward" :size="14" />
      </button>
      <button
        class="ghost"
        type="button"
        style="margin-inline-start: auto"
        @click="store.handleClearQueue"
      >
        <StudioIcon name="trash" :size="14" />
        清空
      </button>
    </div>
  </aside>
</template>

<style scoped>
.queue-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-drawer);
  background: var(--color-backdrop);
}

.queue-drawer {
  position: fixed;
  inset-block: 0;
  inset-inline-end: 0;
  z-index: calc(var(--z-drawer) + 1);
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  inline-size: min(360px, 92vw);
  padding: var(--space-md);
  overflow-y: auto;
  background: var(--color-paper-2);
  border-inline-start: var(--rule-hair) solid var(--color-rule-strong);
  box-shadow: var(--shadow-overlay);
}

.queue-drawer-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-xs);
  padding-block-end: var(--space-sm);
  border-block-end: var(--rule-hair) solid var(--color-rule);
}

.queue-drawer-header h2 {
  margin: 0;
  font-size: 16px;
}

.queue-list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
  border-block-start: var(--rule-hair) solid var(--color-rule);
}

.queue-list li {
  border-block-end: var(--rule-hair) solid var(--color-rule);
}

.queue-row-btn {
  inline-size: 100%;
  justify-content: flex-start;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-xs) var(--space-xs);
  background: transparent;
  border: 0;
  border-radius: 0;
  text-align: start;
}

@media (hover: hover) {
  .queue-row-btn:hover:not(:disabled) {
    background: var(--color-paper-3);
  }
}

.queue-row-btn.current {
  background: var(--color-accent-deep);
  box-shadow: inset 3px 0 0 var(--color-accent);
}

.queue-index {
  inline-size: 20px;
  text-align: end;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-muted);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.queue-label {
  flex: 1;
  min-inline-size: 0;
  overflow-wrap: anywhere;
  white-space: normal;
  font-weight: var(--weight-medium);
}

.queue-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs);
  margin-block-start: auto;
  padding-block-start: var(--space-sm);
  border-block-start: var(--rule-hair) solid var(--color-rule);
}
</style>
