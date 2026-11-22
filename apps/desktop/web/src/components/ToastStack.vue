<script setup lang="ts">
import StudioIcon from "./StudioIcon.vue";

export interface ToastItem {
  id: number;
  kind: "ok" | "error" | "info";
  text: string;
}

defineProps<{
  toasts: ToastItem[];
}>();

const emit = defineEmits<{
  dismiss: [id: number];
}>();
</script>

<template>
  <div v-if="toasts.length > 0" class="toast-stack" aria-live="polite">
    <div
      v-for="t in toasts"
      :key="t.id"
      class="toast-item"
      :class="t.kind"
      :role="t.kind === 'error' ? 'alert' : 'status'"
    >
      <StudioIcon :name="t.kind === 'error' ? 'alert' : 'check'" :size="16" />
      <span>{{ t.text }}</span>
      <button
        type="button"
        class="toast-close"
        aria-label="关闭通知"
        @click="emit('dismiss', t.id)"
      >
        ×
      </button>
    </div>
  </div>
</template>
