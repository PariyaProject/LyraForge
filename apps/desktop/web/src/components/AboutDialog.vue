<script setup lang="ts">
import StudioIcon from "./StudioIcon.vue";

defineProps<{ open: boolean; version?: string }>();
const emit = defineEmits<{ "update:open": [value: boolean] }>();

const THIRD_PARTY = [
  "PyWebView — BSD-3-Clause",
  "pythonnet — MIT",
  "FastAPI — MIT；Starlette / uvicorn — BSD-3-Clause",
  "mido — MIT；jsonschema — MIT",
  "Vue 3 / Vite — MIT",
  "可选工具：FFmpeg（LGPL/GPL 构建）、Basic Pitch（Apache-2.0）、dettato（Apache-2.0，部分辅助训练数据含非商用条款）、uv（Apache-2.0 / MIT）",
];
</script>

<template>
  <div v-if="open" class="about-backdrop" @click="emit('update:open', false)"></div>
  <div
    v-if="open"
    class="about-dialog"
    role="dialog"
    aria-modal="true"
    aria-label="关于 LyraForge 与第三方许可"
  >
    <header class="about-header">
      <h2>关于 LyraForge</h2>
      <button class="ghost" type="button" @click="emit('update:open', false)">
        <StudioIcon name="check" :size="14" />
        关闭
      </button>
    </header>

    <p style="margin: 0">
      版本 {{ version || "开发版" }} · <strong>GNU GPL-3.0</strong>
    </p>
    <p class="muted" style="margin: 0">
      本程序是自由软件，按 GPL-3.0 分发且不提供任何担保；完整许可文本见安装目录的 LICENSE，
      源码与问题反馈：github.com/PariyaProject/LyraForge
    </p>

    <h3 style="margin: 0; font-size: 0.95rem">第三方组件与许可</h3>
    <ul class="about-list">
      <li v-for="item in THIRD_PARTY" :key="item">{{ item }}</li>
    </ul>

    <p class="muted" style="margin: 0">
      本程序不包含游戏音频、贴图或存档，也不读取或修改游戏内存；游戏名称与商标归其权利人所有。
      可选引擎由用户自行安装，其许可与使用条款以各自项目为准。
    </p>
  </div>
</template>

<style scoped>
.about-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgb(0 0 0 / 0.45);
}

.about-dialog {
  position: fixed;
  inset-block-start: 50%;
  inset-inline-start: 50%;
  z-index: 51;
  display: flex;
  flex-direction: column;
  gap: 12px;
  inline-size: min(560px, 92vw);
  max-block-size: 82vh;
  padding: 20px;
  overflow-y: auto;
  background: var(--bg-panel);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  transform: translate(-50%, -50%);
  box-shadow: 0 20px 48px rgb(0 0 0 / 0.45);
}

.about-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.about-header h2 {
  margin: 0;
  font-size: 1.05rem;
}

.about-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding-inline-start: 1.2em;
  font-size: 0.84rem;
}
</style>
