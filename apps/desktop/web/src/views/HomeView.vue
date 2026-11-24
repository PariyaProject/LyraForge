<script setup lang="ts">
import { ref } from "vue";
import StudioIcon from "../components/StudioIcon.vue";
import { arrangementTitle, isImeEnter, type LyraStore } from "../composables/useLyraStore";

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
          离线导入 MIDI 或音视频，经转谱与 Piano Roll 精修后，安全输出 21 键演奏方案。
        </p>
      </div>
      <div class="button-row">
        <button class="secondary" type="button" @click="store.setView('library')">
          <StudioIcon name="library" :size="15" />
          浏览本地曲库
        </button>
        <button class="secondary" type="button" @click="store.setView('transcribe')">
          <StudioIcon name="sparkles" :size="15" />
          转谱与编曲
        </button>
      </div>
    </header>

    <div class="home-search-bar" role="search" aria-label="快速检索曲库">
      <div class="field" style="flex: 1 1 280px">
        <label for="home-quick-search">快速查找本地曲目（回车直达曲库，兼容中文输入法）</label>
        <input
          id="home-quick-search"
          v-model="store.searchQuery.value"
          type="search"
          placeholder="输入歌名、艺人或标签，例如 千本樱 / 卡农…"
          @keydown="handleSearchKeydown"
        />
      </div>
      <button
        class="secondary"
        type="button"
        @click="store.refreshSongs().then(() => store.setView('library'))"
      >
        <StudioIcon name="search" :size="15" />
        在曲库中查找
      </button>
    </div>

    <div class="split-asymmetric">
      <div class="home-left-col">
        <div
          class="dropzone"
          :class="{ dragging }"
          @dragover="handleDragOver"
          @dragleave="handleDragLeave"
          @drop="handleDrop"
        >
          <StudioIcon name="upload" :size="24" />
          <div>
            <h2 style="font-size: 15px; margin-block-end: var(--space-2xs)">拖拽或导入本地媒体</h2>
            <p class="muted" style="margin: 0; font-size: 12px">
              支持 <code>.mid</code> / <code>.midi</code>、音频视频 <code>.mp3</code> / <code>.wav</code> /
              <code>.mp4</code> / <code>.m4s</code> 及 <code>.lyrapack</code> 分享包。
            </p>
          </div>
          <label class="file-picker-trigger" for="home-file-input">
            <StudioIcon name="upload" :size="14" />
            <span>选择本地文件</span>
            <input
              id="home-file-input"
              class="sr-only-input"
              type="file"
              accept=".mid,.midi,.wav,.mp3,.flac,.ogg,.oga,.opus,.m4a,.m4b,.aac,.wma,.aiff,.aif,.m4s,.mp4,.m4v,.mkv,.webm,.mov,.avi,.flv,.wmv,.ts,.m2ts,.mts,.3gp,.mpg,.mpeg,.vob,.ogv,.lyrapack,.zip"
              :disabled="store.busy.value"
              @change="handleQuickFileChange"
            />
          </label>
        </div>

        <div class="section-block">
          <div class="pane-header">
            <h2 class="subsection-heading">标准制作流程</h2>
            <span class="pill" :class="store.health.value?.windows_playback_available ? 'pill-ok' : 'pill-warn'">
              {{ store.health.value?.windows_playback_available ? "Windows 真机就绪" : "当前环境 Dry-Run 模拟" }}
            </span>
          </div>
          <ol class="workflow-steps">
            <li class="workflow-step-row">
              <span class="step-num">01</span>
              <span class="step-copy">
                <strong>导入或音视频转谱</strong>
                <span class="muted">标准 MIDI 准确率最高；复杂混音建议安装 Basic Pitch 或 dettato</span>
              </span>
              <button type="button" class="ghost btn-sm" @click="store.setView('transcribe')">
                打开
              </button>
            </li>
            <li class="workflow-step-row">
              <span class="step-num">02</span>
              <span class="step-copy">
                <strong>21 键编曲与 Piano Roll 精修</strong>
                <span class="muted">选择风物之诗琴 / 镜花之琴 / 老旧的诗琴并调节移调与错峰</span>
              </span>
              <button type="button" class="ghost btn-sm" @click="store.setView('studio')">
                打开
              </button>
            </li>
            <li class="workflow-step-row">
              <span class="step-num">03</span>
              <span class="step-copy">
                <strong>离线试听与授权演奏</strong>
                <span class="muted">两段确认门控，失焦或按 Esc 立即停止并释放所有按键</span>
              </span>
              <button type="button" class="ghost btn-sm" @click="store.setView('playback')">
                打开
              </button>
            </li>
          </ol>
        </div>
      </div>

      <div class="pane">
        <div class="pane-header">
          <h2>当前激活工程</h2>
          <span v-if="store.selectedSong.value" class="pill pill-ok">
            <StudioIcon name="check" :size="12" />
            已加载
          </span>
          <span v-else class="pill">未选择</span>
        </div>

        <template v-if="store.selectedSong.value">
          <div class="active-song-head">
            <h3 class="active-song-title">{{ store.selectedSong.value.title }}</h3>
            <div class="meta-row">
              <span>{{ store.selectedSong.value.artist || "未知作者" }}</span>
              <span>{{ store.arrangements.value.length }} 个编曲版本</span>
              <span>{{ store.profile.value?.display_name ?? store.selectedProfileId.value }}</span>
            </div>
          </div>

          <dl class="metric-strip">
            <div class="metric-cell">
              <dt>曲库总量</dt>
              <dd>{{ store.songs.value.length }} 首</dd>
            </div>
            <div class="metric-cell">
              <dt>当前事件数</dt>
              <dd>{{ store.arrDetail.value?.performance.events.length ?? 0 }} 音</dd>
            </div>
            <div class="metric-cell">
              <dt>演奏模式</dt>
              <dd>{{ store.health.value?.platform === "windows" ? store.playbackMode.value : "Dry-Run" }}</dd>
            </div>
          </dl>

          <div class="button-row">
            <button
              v-if="store.hasAudioSource.value"
              class="secondary"
              type="button"
              @click="store.setView('transcribe')"
            >
              <StudioIcon name="sparkles" :size="14" />
              音频转谱
            </button>
            <button class="secondary" type="button" @click="store.setView('studio')">
              <StudioIcon name="sliders" :size="14" />
              打开 Piano Roll 编曲
            </button>
            <button
              class="secondary"
              type="button"
              :disabled="!store.arrDetail.value"
              @click="store.setView('playback')"
            >
              <StudioIcon name="play" :size="14" />
              准备试听与演奏
            </button>
          </div>

          <div v-if="store.arrangements.value.length > 0" class="arr-quick-block">
            <div class="pane-header">
              <h3 class="subsection-heading">最近编曲版本</h3>
              <button class="ghost btn-sm" type="button" @click="store.setView('studio')">
                全部 {{ store.arrangements.value.length }} 版
              </button>
            </div>
            <ul class="line-list">
              <li
                v-for="arr in store.arrangements.value.slice(0, 3)"
                :key="arr.id"
                class="line-list-row arr-quick-row"
              >
                <div class="arr-quick-meta">
                  <strong class="truncate" style="font-size: 13px">{{ arrangementTitle(arr) }}</strong>
                  <div class="meta-row">
                    <span class="tabular">{{ arr.event_count }} 音</span>
                    <span class="tabular">可演奏 {{ Math.round(arr.playable_ratio * 100) }}%</span>
                  </div>
                </div>
                <button
                  type="button"
                  class="ghost btn-sm"
                  @click="store.selectArrangement(arr.id).then(() => store.setView('studio'))"
                >
                  编辑
                </button>
              </li>
            </ul>
          </div>
        </template>

        <div v-else class="empty-state">
          <StudioIcon name="music" :size="22" />
          <p style="margin: 0">当前曲库暂无曲目，请从左侧导入 MIDI 或音视频文件。</p>
        </div>
      </div>
    </div>

    <div class="section-block">
      <div class="pane-header">
        <h2>最近曲目</h2>
        <button class="ghost btn-sm" type="button" @click="store.setView('library')">
          查看全部（{{ store.songs.value.length }}）
        </button>
      </div>

      <ul v-if="store.recentSongs.value.length > 0" class="line-list">
        <li
          v-for="song in store.recentSongs.value"
          :key="song.id"
          class="line-list-row"
          :class="{ 'is-active-row': store.selectedSongId.value === song.id }"
        >
          <div class="recent-song-main">
            <div class="recent-song-title-row">
              <strong class="truncate" :title="song.title">{{ song.title }}</strong>
              <span v-if="store.selectedSongId.value === song.id" class="pill pill-accent">当前</span>
            </div>
            <div class="meta-row">
              <span class="truncate">{{ song.artist || "未署名艺人" }}</span>
              <span v-if="song.tags.length > 0">{{ song.tags.slice(0, 3).join(", ") }}</span>
            </div>
          </div>
          <div class="button-row" style="flex-shrink: 0">
            <button
              class="secondary btn-sm"
              type="button"
              @click="store.selectSong(song.id).then(() => store.setView('studio'))"
            >
              编曲
            </button>
            <button
              class="ghost btn-sm"
              type="button"
              @click="store.selectSong(song.id).then(() => store.setView('playback'))"
            >
              演奏
            </button>
          </div>
        </li>
      </ul>

      <div v-else class="empty-state">
        <p style="margin: 0">导入第一首曲目后，这里会列出最近的编曲工程。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.home-search-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  background: var(--color-paper-2);
  border: var(--rule-hair) solid var(--color-rule);
  border-radius: var(--radius-md);
}

.home-left-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  min-inline-size: 0;
}

.active-song-head {
  display: flex;
  flex-direction: column;
  gap: var(--space-2xs);
  min-inline-size: 0;
}

.active-song-title {
  font-size: 16px;
  color: var(--color-ink);
  overflow-wrap: break-word;
  min-inline-size: 0;
}

.workflow-steps {
  margin: 0;
  padding: 0;
  list-style: none;
  border-block-start: var(--rule-hair) solid var(--color-rule);
}

.workflow-step-row {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-xs) var(--space-2xs);
  border-block-end: var(--rule-hair) solid var(--color-rule);
  min-inline-size: 0;
}

.step-num {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-accent);
  font-weight: var(--weight-semi);
  flex-shrink: 0;
}

.step-copy {
  flex: 1;
  min-inline-size: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3xs);
}

.step-copy .muted {
  font-size: 12px;
  font-weight: var(--weight-regular);
}

.recent-song-main {
  flex: 1;
  min-inline-size: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3xs);
}

.recent-song-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  min-inline-size: 0;
}

.is-active-row {
  background: var(--color-accent-deep);
  padding-inline: var(--space-xs);
  box-shadow: inset 2px 0 0 var(--color-accent);
}

.arr-quick-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  padding-block-start: var(--space-sm);
  border-block-start: var(--rule-hair) solid var(--color-rule);
}

.arr-quick-row {
  padding-block: var(--space-2xs);
}

.arr-quick-meta {
  flex: 1;
  min-inline-size: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3xs);
}
</style>
