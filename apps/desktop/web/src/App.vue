<script setup lang="ts">
import { onMounted, ref, type Component } from "vue";
import { LyraForgeApi } from "./api";
import AboutDialog from "./components/AboutDialog.vue";
import QueueDrawer from "./components/QueueDrawer.vue";
import StudioIcon, { type StudioIconName } from "./components/StudioIcon.vue";
import ToastStack from "./components/ToastStack.vue";
import { createLyraStore, arrangementTitle, type StudioViewId } from "./composables/useLyraStore";
import HomeView from "./views/HomeView.vue";
import LibraryView from "./views/LibraryView.vue";
import PlaybackView from "./views/PlaybackView.vue";
import SettingsView from "./views/SettingsView.vue";
import StudioView from "./views/StudioView.vue";
import TranscribeView from "./views/TranscribeView.vue";

const props = defineProps<{
  api?: LyraForgeApi;
  client?: LyraForgeApi;
}>();

const store = createLyraStore(props.api ?? props.client ?? new LyraForgeApi());
const queueOpen = ref(false);
const aboutOpen = ref(false);

const NAV_ITEMS: Array<{ id: StudioViewId; label: string; icon: StudioIconName }> = [
  { id: "home", label: "首页", icon: "home" },
  { id: "library", label: "本地曲库", icon: "library" },
  { id: "transcribe", label: "音频转谱", icon: "sparkles" },
  { id: "studio", label: "编曲工作室", icon: "sliders" },
  { id: "playback", label: "试听与演奏", icon: "play" },
  { id: "settings", label: "设置", icon: "settings" },
];

const VIEW_COMPONENTS: Record<StudioViewId, Component> = {
  home: HomeView,
  library: LibraryView,
  transcribe: TranscribeView,
  studio: StudioView,
  playback: PlaybackView,
  settings: SettingsView,
};

onMounted(() => {
  void store.initialize();
});
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">跳至主工作区</a>

    <aside class="studio-rail" aria-label="工作台侧边栏">
      <div class="rail-brand">
        <div class="brand-mark" aria-hidden="true">LF</div>
        <div class="brand-copy">
          <span class="brand-title">LyraForge</span>
          <span class="brand-sub">MIDI / 音频 → 游戏乐器曲谱</span>
        </div>
      </div>

      <nav class="rail-nav" aria-label="主工作区导航">
        <button
          v-for="item in NAV_ITEMS"
          :key="item.id"
          type="button"
          class="rail-item"
          :class="{ active: store.activeView.value === item.id }"
          :aria-current="store.activeView.value === item.id ? 'page' : undefined"
          @click="store.setView(item.id)"
        >
          <StudioIcon :name="item.icon" :size="17" />
          <span class="rail-label">{{ item.label }}</span>
        </button>
      </nav>

      <div class="rail-footer">
        <button
          type="button"
          style="
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            gap: 2px;
            padding: 0;
            color: inherit;
            text-align: start;
            cursor: pointer;
            background: none;
            border: 0;
          "
          @click="aboutOpen = true"
        >
          <strong>LyraForge {{ store.health.value?.version ?? "" }}</strong>
          <span>GPL-3.0 · 关于与第三方许可</span>
        </button>
        <span>{{ store.health.value?.windows_playback_available ? "Windows" : "DRY-RUN" }}</span>
      </div>
    </aside>

    <header class="studio-topbar">
      <div class="topbar-context">
        <span class="pill">
          <StudioIcon name="music" :size="13" />
          {{ store.selectedSong.value?.title ?? "未选择曲目" }}
        </span>
        <span v-if="store.profile.value" class="pill">
          {{ store.profile.value.display_name }}
        </span>
        <span v-if="store.arrDetail.value" class="pill">
          {{ arrangementTitle(store.arrDetail.value.arrangement) }}
        </span>
      </div>

      <div class="topbar-status">
        <span
          class="pill"
          :class="store.health.value?.windows_playback_available ? 'pill-ok' : 'pill-warn'"
        >
          {{
            store.health.value?.windows_playback_available
              ? "Windows 就绪"
              : store.health.value?.platform === "darwin"
                ? "macOS DryRun 模拟模式"
                : "DryRun 模拟模式"
          }}
        </span>
        <span v-if="store.health.value?.platform" class="pill">
          {{ store.health.value.platform }}
        </span>
        <button
          v-if="
            store.playbackStatus.value?.state === 'running' ||
            store.playbackStatus.value?.state === 'paused'
          "
          class="danger"
          type="button"
          style="min-block-size: 30px; padding: 3px 10px"
          @click="store.handleEmergencyStop"
        >
          <StudioIcon name="stop" :size="13" />
          紧急停止
        </button>
      </div>
    </header>

    <main id="main-content" class="studio-main" tabindex="-1">
      <div v-if="store.errorMessage.value" class="banner-error" role="alert" style="margin-block-end: 14px">
        <span>{{ store.errorMessage.value }}</span>
        <button
          type="button"
          class="toast-close"
          aria-label="关闭错误提示"
          @click="store.errorMessage.value = ''"
        >
          关闭
        </button>
      </div>

      <div v-if="store.initializing.value" class="empty-state">
        <p style="margin: 0">正在连接本地 LyraForge 引擎并加载曲库…</p>
      </div>

      <component
        :is="VIEW_COMPONENTS[store.activeView.value]"
        v-else
        :store="store"
      />
    </main>

    <footer class="studio-transport" aria-label="全局试听与演奏控制栏">
      <div class="transport-meta">
        <span class="pill">
          <StudioIcon name="music" :size="13" />
          {{ store.arrDetail.value ? arrangementTitle(store.arrDetail.value.arrangement) : "未选择编曲" }}
        </span>
        <span
          class="pill"
          :class="
            store.playbackStatus.value?.state === 'running' ||
            store.playbackStatus.value?.state === 'paused'
              ? 'pill-warn'
              : 'pill-ok'
          "
        >
          演奏状态：{{ store.playbackStatus.value?.state ?? "idle" }}
        </span>
      </div>

      <div class="transport-audio">
        <audio
          v-if="store.previewUrl.value"
          controls
          :src="store.previewUrl.value"
          aria-label="全局编曲 WAV 试听播放器"
        />
        <span v-else class="muted">
          点击“试听”即可在所有视图间连续播放离线 WAV 合成音频
        </span>
      </div>

      <div class="transport-controls">
        <button class="secondary" type="button" @click="queueOpen = !queueOpen">
          <StudioIcon name="music" :size="14" />
          队列 {{ store.queue.value.items.length }}
        </button>
        <button
          class="secondary"
          type="button"
          :disabled="!store.selectedArrId.value || store.busy.value"
          @click="store.handlePreview"
        >
          <StudioIcon name="play" :size="14" />
          {{ store.previewUrl.value ? "刷新试听" : "快速试听" }}
        </button>
        <button
          v-if="store.playbackStatus.value?.state === 'running'"
          class="secondary"
          type="button"
          @click="store.handlePause"
        >
          暂停演奏
        </button>
        <button
          v-if="store.playbackStatus.value?.state === 'paused'"
          class="primary"
          type="button"
          @click="store.handleResume"
        >
          继续演奏
        </button>
        <button
          v-if="
            store.playbackStatus.value?.state === 'running' ||
            store.playbackStatus.value?.state === 'paused'
          "
          class="danger"
          type="button"
          @click="store.handleEmergencyStop"
        >
          <StudioIcon name="stop" :size="14" />
          紧急停止
        </button>
      </div>
    </footer>

    <ToastStack :toasts="store.toasts.value" @dismiss="store.dismissToast" />
    <QueueDrawer v-model:open="queueOpen" :store="store" />
    <AboutDialog
      v-model:open="aboutOpen"
      :version="store.health.value?.version"
    />
  </div>
</template>
