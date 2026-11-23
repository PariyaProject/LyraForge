<script setup lang="ts">
import { ref } from "vue";
import StudioIcon from "../components/StudioIcon.vue";
import { isImeEnter, type LyraStore } from "../composables/useLyraStore";

const props = defineProps<{
  store: LyraStore;
}>();

const dragging = ref(false);

function handleSearchKeydown(event: KeyboardEvent): void {
  if (!isImeEnter(event)) return;
  event.preventDefault();
  void props.store.refreshSongs().then(() => props.store.setView("library"));
}

function handleDragOver(event: DragEvent): void {
  event.preventDefault();
  dragging.value = true;
}

function handleDragLeave(): void {
  dragging.value = false;
}

async function handleDrop(event: DragEvent): Promise<void> {
  event.preventDefault();
  dragging.value = false;
  const file = event.dataTransfer?.files?.[0];
  if (file) {
    await props.store.importDroppedOrPickedFile(file);
  }
}

async function handleQuickFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) {
    await props.store.importDroppedOrPickedFile(file);
    input.value = "";
  }
}
</script>

<template>
  <section class="view-stack" aria-label="工作台首页">
    <header class="view-header">
      <div>
        <h1 class="view-title">LyraForge 编曲与演奏工作台</h1>
        <p class="view-subtitle">
          离线导入 MIDI / 音视频，自动化转谱、Piano Roll 精修并在确认后安全演奏。
        </p>
      </div>
      <div class="button-row">
        <button class="secondary" type="button" @click="store.setView('library')">
          <StudioIcon name="library" />
          浏览本地曲库
        </button>
        <button class="primary" type="button" @click="store.setView('transcribe')">
          <StudioIcon name="sparkles" />
          转谱与编曲
        </button>
      </div>
    </header>

    <div class="card" role="search" aria-label="快速检索曲库">
      <div class="row">
        <div class="field" style="flex: 1 1 260px">
          <label for="home-quick-search">快速查找本地曲目（支持回车直达曲库，兼容中文输入法）</label>
          <input
            id="home-quick-search"
            v-model="store.searchQuery.value"
            type="search"
            placeholder="输入歌名、艺人或关键词，例如 千本樱 / 卡农…"
            @keydown="handleSearchKeydown"
          />
        </div>
        <button
          class="primary"
          type="button"
          @click="store.refreshSongs().then(() => store.setView('library'))"
        >
          <StudioIcon name="search" />
          在曲库中查找
        </button>
      </div>
    </div>

    <div class="split-2">
      <div
        class="card dropzone"
        :class="{ dragging }"
        @dragover="handleDragOver"
        @dragleave="handleDragLeave"
        @drop="handleDrop"
      >
        <StudioIcon name="upload" :size="28" />
        <h2>拖拽或选择文件快速导入</h2>
        <p class="muted">
          支持 <code>.mid</code> / <code>.midi</code>、音频 <code>.mp3</code> / <code>.wav</code> /
          <code>.mp4</code> 及 <code>.lyrapack</code> 分享包。导入后自动进入对应工作区。
        </p>
        <div class="file-picker-wrap" style="inline-size: 100%">
          <label for="home-file-input" class="muted">本地文件：</label>
          <input
            id="home-file-input"
            type="file"
            accept=".mid,.midi,.mp3,.wav,.flac,.ogg,.m4a,.mp4,.mkv,.webm,.lyrapack,.zip"
            :disabled="store.busy.value"
            @change="handleQuickFileChange"
          />
        </div>
      </div>

      <div class="card">
        <div class="card-title-row">
          <h2>当前激活工作曲目</h2>
          <span v-if="store.selectedSong.value" class="pill pill-ok">
            <StudioIcon name="check" :size="13" />
            已加载
          </span>
          <span v-else class="pill">未选择</span>
        </div>

        <template v-if="store.selectedSong.value">
          <div>
            <strong style="font-size: 1.05rem">{{ store.selectedSong.value.title }}</strong>
            <p class="muted" style="margin-block: 4px 0">
              {{ store.selectedSong.value.artist || "未知作者" }} ·
              已有 {{ store.arrangements.value.length }} 个编曲版本 ·
              目标乐器 {{ store.profile.value?.display_name ?? store.selectedProfileId.value }}
            </p>
          </div>

          <div class="stats-grid">
            <div class="stat-card">
              <div class="label">曲库总量</div>
              <div class="value">{{ store.songs.value.length }} 首</div>
            </div>
            <div class="stat-card">
              <div class="label">当前事件数</div>
              <div class="value">{{ store.arrDetail.value?.performance.events.length ?? 0 }} 音</div>
            </div>
            <div class="stat-card">
              <div class="label">演奏模式</div>
              <div class="value">
                {{ store.health.value?.platform === "windows" ? store.playbackMode.value : "Dry-Run" }}
              </div>
            </div>
          </div>

          <div class="button-row">
            <button
              v-if="store.hasAudioSource.value"
              class="secondary"
              type="button"
              @click="store.setView('transcribe')"
            >
              <StudioIcon name="sparkles" />
              音频转谱
            </button>
            <button class="secondary" type="button" @click="store.setView('studio')">
              <StudioIcon name="sliders" />
              打开 Piano Roll 编曲
            </button>
            <button
              class="primary"
              type="button"
              :disabled="!store.arrDetail.value"
              @click="store.setView('playback')"
            >
              <StudioIcon name="play" />
              准备试听与演奏
            </button>
          </div>
        </template>

        <div v-else class="empty-state">
          <StudioIcon name="music" :size="24" />
          <p style="margin: 0">当前曲库暂无曲目，请从左侧拖入 MIDI/音视频，或前往曲库导入。</p>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title-row">
        <h2>最近曲目</h2>
        <button class="ghost" type="button" @click="store.setView('library')">
          查看全部（{{ store.songs.value.length }}）
        </button>
      </div>

      <div v-if="store.recentSongs.value.length > 0" class="track-grid">
        <div
          v-for="song in store.recentSongs.value"
          :key="song.id"
          class="track-card"
          :class="{ selected: store.selectedSongId.value === song.id }"
        >
          <div class="card-title-row">
            <strong class="truncate">{{ song.title }}</strong>
            <span v-if="store.selectedSongId.value === song.id" class="pill pill-ok">当前</span>
          </div>
          <span class="muted truncate">{{ song.artist || "未署名艺人" }}</span>
          <div class="button-row">
            <span v-for="tag in song.tags.slice(0, 3)" :key="tag" class="pill">{{ tag }}</span>
          </div>
          <div class="button-row" style="margin-block-start: auto">
            <button
              class="secondary"
              type="button"
              @click="store.selectSong(song.id).then(() => store.setView('studio'))"
            >
              编曲
            </button>
            <button
              class="ghost"
              type="button"
              @click="store.selectSong(song.id).then(() => store.setView('playback'))"
            >
              演奏
            </button>
          </div>
        </div>
      </div>

      <div v-else class="empty-state">
        <p style="margin: 0">导入第一首曲目后，这里会展示最近的编曲工程。</p>
      </div>
    </div>

    <div class="card">
      <div class="card-title-row">
        <h2>首次使用 3 步指南 & 能力范围</h2>
        <span class="pill pill-warn">
          {{ store.health.value?.windows_playback_available ? "Windows 实机待校准" : "当前环境仅 Dry-Run 模拟" }}
        </span>
      </div>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="label">1. 导入或转录</div>
          <p class="muted" style="margin: 4px 0 0">
            拖入标准 <code>.mid</code> 准确率最高；纯 Python 内置单音引擎适合独奏 WAV，复杂混音需另配 Basic Pitch / FFmpeg。
          </p>
        </div>
        <div class="stat-card">
          <div class="label">2. 编曲与精修</div>
          <p class="muted" style="margin: 4px 0 0">
            在编曲工作室选择风物之诗琴 / 镜花之琴，A/B 对比并用底部试听栏连续校验，在 Piano Roll 微调错音或八度。
          </p>
        </div>
        <div class="stat-card">
          <div class="label">3. 安全演奏门控</div>
          <p class="muted" style="margin: 4px 0 0">
            游戏内发送按键仅限 Windows 10/11 前台切至《原神》自由演奏界面时通过两段确认启动；切窗或按 Esc 立即松键。
          </p>
        </div>
      </div>
    </div>
  </section>
</template>
