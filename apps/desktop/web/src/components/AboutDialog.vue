<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import StudioIcon from "./StudioIcon.vue";

const props = defineProps<{ open: boolean; version?: string }>();
const emit = defineEmits<{ "update:open": [value: boolean] }>();

const dialogRef = ref<HTMLDialogElement | null>(null);
const fallbackVisible = ref(false);
let pressedOutside = false;

const THIRD_PARTY: Array<{ name: string; license: string }> = [
  { name: "PyWebView", license: "BSD-3-Clause" },
  { name: "pythonnet", license: "MIT" },
  { name: "FastAPI / Starlette / uvicorn", license: "MIT / BSD-3-Clause" },
  { name: "mido / jsonschema", license: "MIT" },
  { name: "Vue 3 / Vite", license: "MIT" },
  {
    name: "试听原声乐器采样 (VCSL)",
    license:
      "CC0-1.0 (Public Domain, github.com/sgossner/VCSL — Steinway B 钢琴、音乐会竖琴与拨弦采样)",
  },
  {
    name: "可选外部引擎与引导工具",
    license:
      "FFmpeg (LGPL/GPL 构建), Basic Pitch (Apache-2.0), dettato (Apache-2.0, 部分辅助训练数据含非商用条款), uv (Apache-2.0 / MIT)",
  },
];

function syncDialog(isOpen: boolean): void {
  const el = dialogRef.value;
  if (!el) return;
  if (isOpen) {
    if (typeof el.showModal === "function") {
      if (!el.open) el.showModal();
    } else {
      fallbackVisible.value = true;
    }
  } else {
    fallbackVisible.value = false;
    if (typeof el.close === "function" && el.open) {
      el.close();
    }
  }
}

watch(
  () => props.open,
  (val) => syncDialog(val),
);

function requestClose(): void {
  emit("update:open", false);
}

function onNativeClose(): void {
  if (props.open) {
    emit("update:open", false);
  }
}

function isOutsideDialog(e: PointerEvent, el: HTMLDialogElement): boolean {
  const rect = el.getBoundingClientRect();
  return (
    e.clientX < rect.left ||
    e.clientX > rect.right ||
    e.clientY < rect.top ||
    e.clientY > rect.bottom
  );
}

function onDialogPointerDown(e: PointerEvent): void {
  const el = dialogRef.value;
  if (!el || "closedBy" in el) return;
  pressedOutside = isOutsideDialog(e, el);
}

function onDialogPointerUp(e: PointerEvent): void {
  const el = dialogRef.value;
  if (!el || "closedBy" in el) return;
  if (pressedOutside && isOutsideDialog(e, el)) {
    requestClose();
  }
  pressedOutside = false;
}

onMounted(() => {
  if (props.open) syncDialog(true);
});

onBeforeUnmount(() => {
  const el = dialogRef.value;
  if (el && typeof el.close === "function" && el.open) {
    el.close();
  }
});
</script>

<template>
  <dialog
    ref="dialogRef"
    class="about-dialog"
    closedby="any"
    aria-labelledby="about-dialog-title"
    :open="fallbackVisible ? true : undefined"
    @close="onNativeClose"
    @pointerdown="onDialogPointerDown"
    @pointerup="onDialogPointerUp"
  >
    <div class="about-shell">
      <header class="about-header">
        <div>
          <h2 id="about-dialog-title">关于 LyraForge</h2>
          <div class="meta-row">
            <span>版本 {{ version || "开发版" }}</span>
            <span>GNU GPL-3.0</span>
          </div>
        </div>
        <button class="ghost btn-sm" type="button" autofocus @click="requestClose">
          <StudioIcon name="x" :size="15" />
          关闭
        </button>
      </header>

      <p class="muted" style="margin: 0">
        本程序为自由软件，按 GNU GPL-3.0 协议分发且不提供担保。完整许可文本见安装目录的
        <code>LICENSE</code>，源码与问题反馈地址：<code>github.com/PariyaProject/LyraForge</code>
      </p>

      <div class="about-section">
        <h3>第三方组件与许可</h3>
        <dl class="about-dl">
          <div v-for="item in THIRD_PARTY" :key="item.name" class="about-dl-row">
            <dt>{{ item.name }}</dt>
            <dd>{{ item.license }}</dd>
          </div>
        </dl>
      </div>

      <p class="muted" style="margin: 0">
        本程序不包含游戏音频、贴图或存档，也不读取或修改游戏内存。游戏名称与商标归其权利人所有，可选引擎的许可与条款以各自项目为准。
      </p>
    </div>
  </dialog>
</template>

<style scoped>
.about-dialog {
  padding: 0;
  border: var(--rule-hair) solid var(--color-rule-strong);
  border-radius: var(--radius-md);
  background: var(--color-paper-2);
  color: var(--color-ink);
  inline-size: min(560px, 92vw);
  max-block-size: min(82dvh, 640px);
  overflow-y: auto;
}

.about-dialog:modal {
  position: fixed;
  inset: 0;
  margin: auto;
  overscroll-behavior: contain;
}

.about-dialog::backdrop {
  background: var(--color-backdrop);
  overflow: hidden;
  overscroll-behavior: contain;
}

.about-shell {
  padding: var(--space-lg);
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.about-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-sm);
  padding-block-end: var(--space-sm);
  border-block-end: var(--rule-hair) solid var(--color-rule);
}

.about-header h2 {
  margin: 0;
  font-size: 16px;
  text-wrap: balance;
}

.about-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.about-section h3 {
  margin: 0;
  font-size: 13px;
  color: var(--color-ink-2);
}

.about-dl {
  margin: 0;
  border-block-start: var(--rule-hair) solid var(--color-rule);
}

.about-dl-row {
  display: grid;
  grid-template-columns: minmax(140px, 0.9fr) minmax(0, 1.4fr);
  gap: var(--space-sm);
  padding-block: var(--space-xs);
  border-block-end: var(--rule-hair) solid var(--color-rule);
  font-size: 12px;
}

.about-dl-row dt {
  font-weight: var(--weight-medium);
  color: var(--color-ink);
}

.about-dl-row dd {
  margin: 0;
  color: var(--color-muted);
}
</style>
