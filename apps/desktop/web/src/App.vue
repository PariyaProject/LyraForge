<script setup lang="ts">
import { computed, onMounted, ref, watch, type Component } from "vue";
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
const previewAudioEl = ref<HTMLAudioElement | null>(null);

const PRIMARY_NAV: Array<{ id: StudioViewId; label: string; icon: StudioIconName }> = [
  { id: "home", label: "首页", icon: "home" },
  { id: "library", label: "本地曲库", icon: "library" },
  { id: "transcribe", label: "音频转谱", icon: "sparkles" },
  { id: "studio", label: "编曲工作室", icon: "sliders" },
  { id: "playback", label: "试听与演奏", icon: "play" },
];

const SECONDARY_NAV: Array<{ id: StudioViewId; label: string; icon: StudioIconName }> = [
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

const isFlushView = computed(
  () => store.activeView.value === "studio" || store.activeView.value === "library",
);

const isPlaybackActive = computed(() => {
  const st = store.playbackStatus.value?.state;
  return st === "running" || st === "paused" || st === "waiting_focus";
});

const jobRunning = computed(() => {
  const st = store.activeJob.value?.status;
  return st === "running" || st === "queued";
});

function formatMs(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function syncAudioState(): void {
  const el = previewAudioEl.value;
  if (!el) return;
  const durMs = Number.isFinite(el.duration) ? el.duration * 1000 : store.previewDurationMs.value;
  store.updatePreviewPlayback(el.currentTime * 1000, durMs, !el.paused && !el.ended);
}

function togglePreviewPlay(): void {
  const el = previewAudioEl.value;
  if (!el) return;
  if (el.paused || el.ended) {
    void el.play().catch(() => {});
  } else {
    el.pause();
  }
}

function onScrubInput(event: Event): void {
  const target = event.target as HTMLInputElement;
  const ms = Number(target.value);
  const el = previewAudioEl.value;
  if (el && Number.isFinite(ms)) {
    el.currentTime = ms / 1000;
  }
  store.updatePreviewPlayback(ms, store.previewDurationMs.value, store.previewPlaying.value);
}

watch(
  () => store.previewSeekTargetMs.value,
  (targetMs) => {
    if (targetMs === null) return;
    const el = previewAudioEl.value;
    if (el) {
      el.currentTime = targetMs / 1000;
      syncAudioState();
    }
    store.previewSeekTargetMs.value = null;
  },
);

onMounted(() => {
  void store.initialize();
});
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">跳至主工作区</a>

    <aside class="studio-rail" aria-label="工作台侧边栏">
      <div class="rail-brand">
        <div class="brand-mark" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path
              d="M4.5 4v10.8c0 3 2.1 4.7 5.4 4.7H20v-2.8H10.2c-1.8 0-2.8-.9-2.8-2.6V4Z"
              fill="currentColor"
            />
            <path d="M9.6 6.8 19.6 4v2.3L9.6 9.1Z" fill="currentColor" opacity="0.9" />
            <rect x="10.2" y="10.8" width="2.2" height="5.2" rx="0.8" fill="currentColor" opacity="0.58" />
            <rect x="13.8" y="8.8" width="2.2" height="7.2" rx="0.8" fill="currentColor" />
            <rect x="17.4" y="7.2" width="2.2" height="8.8" rx="0.8" fill="currentColor" />
          </svg>
        </div>
        <div class="brand-copy">
          <span class="brand-title">LyraForge</span>
          <span class="brand-sub">乐器编曲工作台</span>
        </div>
      </div>

      <nav class="rail-nav" aria-label="主工作区导航">
        <button
          v-for="item in PRIMARY_NAV"
          :key="item.id"
          type="button"
          class="rail-item"
          :class="{ active: store.activeView.value === item.id }"
          :title="item.label"
          :aria-current="store.activeView.value === item.id ? 'page' : undefined"
          @click="store.setView(item.id)"
        >
          <StudioIcon :name="item.icon" :size="16" />
          <span class="rail-label">{{ item.label }}</span>
        </button>

        <div class="rail-divider" role="separator"></div>

        <button
          v-for="item in SECONDARY_NAV"
          :key="item.id"
          type="button"
          class="rail-item"
          :class="{ active: store.activeView.value === item.id }"
          :title="item.label"
          :aria-current="store.activeView.value === item.id ? 'page' : undefined"
          @click="store.setView(item.id)"
        >
          <StudioIcon :name="item.icon" :size="16" />
          <span class="rail-label">{{ item.label }}</span>
        </button>
      </nav>

      <div class="rail-footer">
        <button
          type="button"
          class="rail-about-btn"
          @click="aboutOpen = true"
        >
          <span>LyraForge {{ store.health.value?.version ?? "" }}</span>
          <StudioIcon name="info" :size="14" />
        </button>
        <div class="rail-env-note">
          <span>GPL-3.0</span>
          <span> / </span>
          <span>{{ store.health.value?.windows_playback_available ? "Windows" : "Dry-Run" }}</span>
        </div>
      </div>
    </aside>

    <header class="studio-topbar">
      <div class="topbar-context">
        <span class="ctx-crumb truncate" :title="store.selectedSong.value?.title ?? '未选择曲目'">
          <StudioIcon name="music" :size="14" />
          <span class="truncate">{{ store.selectedSong.value?.title ?? "未选择曲目" }}</span>
        </span>
        <template v-if="store.profile.value">
          <span class="ctx-sep" aria-hidden="true">/</span>
          <span class="ctx-crumb-muted truncate" :title="store.profile.value.display_name">
            {{ store.profile.value.display_name }}
          </span>
        </template>
        <template v-if="store.arrDetail.value">
          <span class="ctx-sep" aria-hidden="true">/</span>
          <span
            class="ctx-crumb-muted truncate"
            :title="arrangementTitle(store.arrDetail.value.arrangement)"
          >
            {{ arrangementTitle(store.arrDetail.value.arrangement) }}
          </span>
        </template>
      </div>

      <div class="topbar-status">
        <button
          v-if="jobRunning"
          type="button"
          class="pill pill-accent btn-sm"
          @click="store.setView('transcribe')"
        >
          <StudioIcon name="sparkles" :size="13" />
          转谱中 {{ Math.round((store.activeJob.value?.progress ?? 0) * 100) }}%
        </button>
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
        <button
          v-if="isPlaybackActive"
          class="danger btn-sm"
          type="button"
          @click="store.handleEmergencyStop"
        >
          <StudioIcon name="stop" :size="13" />
          紧急停止
        </button>
      </div>
    </header>

    <main
      id="main-content"
      class="studio-main"
      :class="{ 'studio-flush': isFlushView }"
      tabindex="-1"
    >
      <div
        v-if="store.errorMessage.value"
        class="banner-error"
        role="alert"
        :style="isFlushView ? { margin: 'var(--space-sm)' } : { marginBlockEnd: 'var(--space-md)' }"
      >
        <span>{{ store.errorMessage.value }}</span>
        <button
          type="button"
          class="ghost btn-sm"
          aria-label="关闭错误提示"
          @click="store.errorMessage.value = ''"
        >
          <StudioIcon name="x" :size="14" />
          关闭
        </button>
      </div>

      <div v-if="store.initializing.value" class="empty-state" style="margin: var(--space-lg)">
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
        <span
          class="transport-title truncate"
          :title="
            store.selectedSong.value && store.arrDetail.value
              ? `${store.selectedSong.value.title} — ${arrangementTitle(store.arrDetail.value.arrangement)}`
              : store.arrDetail.value
                ? arrangementTitle(store.arrDetail.value.arrangement)
                : '未选择编曲'
          "
        >
          {{
            store.selectedSong.value && store.arrDetail.value
              ? `${store.selectedSong.value.title} — ${arrangementTitle(store.arrDetail.value.arrangement)}`
              : store.arrDetail.value
                ? arrangementTitle(store.arrDetail.value.arrangement)
                : "未选择编曲"
          }}
        </span>
        <span
          class="pill"
          :class="isPlaybackActive ? 'pill-warn' : 'pill-ok'"
        >
          演奏状态：{{ store.playbackStatus.value?.state ?? "idle" }}
        </span>
      </div>

      <div class="transport-audio">
        <template v-if="store.previewUrl.value">
          <audio
            ref="previewAudioEl"
            controls
            :src="store.previewUrl.value"
            class="transport-audio-native"
            aria-label="全局编曲 WAV 试听播放器"
            @loadedmetadata="syncAudioState"
            @timeupdate="syncAudioState"
            @play="syncAudioState"
            @pause="syncAudioState"
            @ended="syncAudioState"
          />
          <div class="transport-player">
            <button
              type="button"
              class="secondary btn-sm"
              :aria-label="store.previewPlaying.value ? '暂停试听' : '播放试听'"
              @click="togglePreviewPlay"
            >
              <StudioIcon :name="store.previewPlaying.value ? 'pause' : 'play'" :size="14" />
            </button>
            <input
              type="range"
              class="transport-scrubber"
              aria-label="试听进度滑块"
              :min="0"
              :max="Math.max(1, store.previewDurationMs.value || store.arrDetail.value?.performance.duration_ms || 1000)"
              :value="store.previewCurrentMs.value"
              @input="onScrubInput"
            />
            <span class="transport-time">
              {{ formatMs(store.previewCurrentMs.value) }} /
              {{ formatMs(store.previewDurationMs.value || store.arrDetail.value?.performance.duration_ms || 0) }}
            </span>
          </div>
        </template>
        <span v-else class="muted" style="font-size: 12px">
          点击「快速试听」合成离线 WAV 音频并在所有视图间连续播放
        </span>
      </div>

      <div class="transport-controls">
        <button
          class="secondary"
          type="button"
          :aria-expanded="queueOpen"
          @click="queueOpen = !queueOpen"
        >
          <StudioIcon name="list-music" :size="14" />
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
          v-if="isPlaybackActive"
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
