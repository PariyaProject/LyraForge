<script setup lang="ts">
import StudioIcon from "../components/StudioIcon.vue";
import { isImeEnter, type LyraStore } from "../composables/useLyraStore";

const props = defineProps<{
  store: LyraStore;
}>();

function onFilterKeydown(event: KeyboardEvent): void {
  if (!isImeEnter(event)) return;
  event.preventDefault();
  void props.store.refreshSongs();
}

function onUploadFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  props.store.uploadFile.value = input.files?.[0] ?? null;
}

function onPackFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  props.store.packFile.value = input.files?.[0] ?? null;
}
</script>

<template>
  <section class="view-stack" aria-label="本地曲库与资源管理">
    <header class="view-header">
      <div>
        <h1 class="view-title">本地曲库与工程归档</h1>
        <p class="view-subtitle">
          本地 SQLite 曲库检索、多版本工程切换、<code>.lyrapack</code> 分享包与全量备份。
        </p>
      </div>
      <div class="button-row">
        <button class="secondary" type="button" @click="store.handleBackupZip">
          <StudioIcon name="download" />
          备份曲库 (.zip)
        </button>
      </div>
    </header>

    <div class="split-library">
      <div class="view-stack" style="gap: var(--space-3)">
        <div class="card" role="search" aria-label="筛选本地曲库">
          <h2>搜索与筛选</h2>
          <div class="field">
            <label for="library-search">歌名 / 艺人关键词</label>
            <input
              id="library-search"
              v-model="store.searchQuery.value"
              type="search"
              placeholder="搜索曲名或艺人…"
              @keydown="onFilterKeydown"
            />
          </div>
          <div class="field">
            <label for="library-tag-filter">按标签筛选</label>
            <input
              id="library-tag-filter"
              v-model="store.filterTag.value"
              type="text"
              placeholder="如：demo / anime / fingerstyle"
              @keydown="onFilterKeydown"
            />
          </div>
          <label class="checkbox-row">
            <input
              v-model="store.filterFavoritesOnly.value"
              type="checkbox"
              @change="store.refreshSongs()"
            />
            仅显示包含收藏版本的曲目
          </label>
          <div class="button-row">
            <button class="primary" type="button" @click="store.refreshSongs()">
              <StudioIcon name="search" />
              搜索
            </button>
          </div>
        </div>

        <div class="card">
          <div class="card-title-row">
            <h2>曲目列表</h2>
            <span class="pill">{{ store.songs.value.length }} 首</span>
          </div>
          <ul v-if="store.songs.value.length > 0" class="song-list" aria-label="曲目清单">
            <li v-for="song in store.songs.value" :key="song.id">
              <button
                type="button"
                class="song-item"
                :class="{ selected: store.selectedSongId.value === song.id }"
                @click="store.selectSong(song.id)"
              >
                <div class="card-title-row" style="inline-size: 100%">
                  <strong class="truncate">{{ song.title }}</strong>
                  <span v-if="store.selectedSongId.value === song.id" class="pill pill-ok">
                    当前
                  </span>
                </div>
                <span class="muted truncate">{{ song.artist || "未署名艺人" }}</span>
                <div v-if="song.tags.length > 0" class="button-row">
                  <span v-for="tag in song.tags" :key="tag" class="pill">{{ tag }}</span>
                </div>
              </button>
            </li>
          </ul>
          <div v-else class="empty-state">
            <p style="margin: 0">未匹配到符合条件的本地曲目。</p>
          </div>
        </div>

        <details class="advanced-box" open>
          <summary>导入本地媒体与 .lyrapack 分享包</summary>
          <div class="view-stack" style="margin-block-start: var(--space-3); gap: var(--space-3)">
            <div class="field">
              <label for="library-media-file">导入本地 MIDI 或音视频文件</label>
              <div class="file-picker-wrap">
                <input
                  id="library-media-file"
                  type="file"
                  accept=".mid,.midi,.mp3,.wav,.flac,.ogg,.m4a,.mp4,.mkv,.webm"
                  @change="onUploadFileChange"
                />
              </div>
            </div>
            <div class="row">
              <div class="field" style="flex: 1 1 120px">
                <label for="library-import-title">曲目标题（可选）</label>
                <input id="library-import-title" v-model="store.importTitle.value" type="text" />
              </div>
              <div class="field" style="flex: 1 1 120px">
                <label for="library-import-artist">艺人 / 作者（可选）</label>
                <input id="library-import-artist" v-model="store.importArtist.value" type="text" />
              </div>
            </div>
            <div class="field">
              <label for="library-import-tags">标签（逗号分隔）</label>
              <input
                id="library-import-tags"
                v-model="store.importTags.value"
                type="text"
                placeholder="例如：windsong, acoustic"
              />
            </div>
            <button
              class="primary"
              type="button"
              :disabled="store.busy.value"
              @click="store.handleImport"
            >
              <StudioIcon name="upload" />
              导入本地文件
            </button>

            <hr style="border: 0; border-block-start: 1px solid var(--border-subtle); inline-size: 100%" />

            <div class="field">
              <label for="library-pack-file">导入他人分享的 .lyrapack 曲谱包</label>
              <div class="file-picker-wrap">
                <input
                  id="library-pack-file"
                  type="file"
                  accept=".lyrapack,.zip"
                  @change="onPackFileChange"
                />
              </div>
            </div>
            <button
              class="secondary"
              type="button"
              :disabled="store.busy.value"
              @click="store.handleImportLyrapack"
            >
              导入 .lyrapack 分享包
            </button>
          </div>
        </details>
      </div>

      <div class="card">
        <template v-if="store.selectedSong.value">
          <div class="card-title-row">
            <div>
              <h2>{{ store.selectedSong.value.title }}</h2>
              <p class="muted" style="margin: 2px 0 0">
                {{ store.selectedSong.value.artist || "未署名艺人" }} · ID:
                <code>{{ store.selectedSong.value.id }}</code>
              </p>
            </div>
            <div class="button-row">
              <button
                v-if="store.hasAudioSource.value"
                class="secondary"
                type="button"
                @click="store.setView('transcribe')"
              >
                音频转谱
              </button>
              <button class="primary" type="button" @click="store.setView('studio')">
                <StudioIcon name="sliders" />
                进入编曲工作室
              </button>
            </div>
          </div>

          <h3>媒体来源 ({{ store.songSources.value.length }})</h3>
          <div v-if="store.songSources.value.length > 0" class="stats-grid">
            <div v-for="src in store.songSources.value" :key="src.id" class="stat-card">
              <div class="label">{{ src.kind.toUpperCase() }} 来源</div>
              <div class="value truncate" style="font-size: 0.92rem">
                {{ src.original_name || src.id }}
              </div>
            </div>
          </div>
          <p v-else class="muted">当前曲目尚无关联来源记录。</p>

          <h3>历史转谱记录 ({{ store.songTranscriptions.value.length }})</h3>
          <div v-if="store.songTranscriptions.value.length > 0" class="button-row">
            <span
              v-for="tr in store.songTranscriptions.value"
              :key="tr.id"
              class="pill"
              :class="tr.status === 'completed' ? 'pill-ok' : ''"
            >
              {{ tr.engine }} · {{ tr.status }} · {{ tr.note_count }} 音符
            </span>
          </div>
          <p v-else class="muted">暂无音频转谱记录（若为纯 MIDI 来源可直接编曲）。</p>

          <h3>已保存编曲版本 ({{ store.arrangements.value.length }})</h3>
          <div v-if="store.arrangements.value.length > 0" class="view-stack" style="gap: 8px">
            <div
              v-for="arr in store.arrangements.value"
              :key="arr.id"
              class="track-card"
              :class="{ selected: store.selectedArrId.value === arr.id }"
            >
              <div class="card-title-row">
                <strong>{{ arr.label || arr.style }}</strong>
                <div class="button-row">
                  <span v-if="arr.is_favorite" class="pill pill-warn">
                    <StudioIcon name="star" :size="12" />
                    已收藏
                  </span>
                  <span class="pill">{{ arr.event_count }} 音符</span>
                </div>
              </div>
              <div class="button-row">
                <button
                  class="secondary"
                  type="button"
                  @click="store.selectArrangement(arr.id).then(() => store.setView('studio'))"
                >
                  在 Piano Roll 打开
                </button>
                <button
                  class="ghost"
                  type="button"
                  @click="store.selectArrangement(arr.id).then(() => store.setView('playback'))"
                >
                  试听 / 演奏
                </button>
              </div>
            </div>
          </div>
          <div v-else class="empty-state">
            <p style="margin: 0">暂无改编版本，请先生成版本或运行 AI 智能编曲。</p>
            <button class="primary" type="button" @click="store.setView('studio')">
              前往生成版本
            </button>
          </div>
        </template>

        <div v-else class="empty-state">
          <StudioIcon name="library" :size="26" />
          <p style="margin: 0">请在左侧曲目列表中选择一首曲目，或导入新的 MIDI / 音视频 / 分享包。</p>
        </div>
      </div>
    </div>
  </section>
</template>
