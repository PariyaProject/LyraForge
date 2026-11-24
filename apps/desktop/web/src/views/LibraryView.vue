<script setup lang="ts">
import { ref } from "vue";
import StudioIcon from "../components/StudioIcon.vue";
import {
  arrangementTitle,
  isImeEnter,
  type LyraStore,
} from "../composables/useLyraStore";

const props = defineProps<{
  store: LyraStore;
}>();

const editingId = ref<string | null>(null);
const editingLabel = ref("");
const importDrawerOpen = ref(false);
const confirmDeleteArrId = ref<string | null>(null);

async function confirmDeleteArrangement(arrangementId: string): Promise<void> {
  confirmDeleteArrId.value = null;
  await props.store.handleDeleteArrangement(arrangementId);
}

function startRename(arrangementId: string, current: string): void {
  editingId.value = arrangementId;
  editingLabel.value = current;
}

async function saveRename(): Promise<void> {
  if (!editingId.value) return;
  await props.store.handleRenameArrangement(editingId.value, editingLabel.value);
  editingId.value = null;
}

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

function onRestoreFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  props.store.restoreFile.value = input.files?.[0] ?? null;
}
</script>

<template>
  <section class="library-shell" aria-label="本地曲库与资源管理">
    <header class="library-toolbar">
      <div class="library-toolbar-left">
        <h1 class="view-title" style="font-size: 16px">本地曲库</h1>
        <span class="pill tabular">{{ store.songs.value.length }} 首</span>

        <div class="library-filter-group" role="search" aria-label="筛选本地曲库">
          <input
            id="library-search"
            v-model="store.searchQuery.value"
            type="search"
            class="lib-input-search"
            aria-label="歌名或艺人关键词"
            placeholder="搜索歌名或艺人…"
            @keydown="onFilterKeydown"
          />
          <input
            id="library-tag-filter"
            v-model="store.filterTag.value"
            type="text"
            class="lib-input-tag"
            aria-label="按标签筛选"
            placeholder="标签筛选…"
            @keydown="onFilterKeydown"
          />
          <label class="checkbox-row" style="white-space: nowrap">
            <input
              v-model="store.filterFavoritesOnly.value"
              type="checkbox"
              @change="store.refreshSongs()"
            />
            仅收藏
          </label>
          <button class="secondary btn-sm" type="button" @click="store.refreshSongs()">
            <StudioIcon name="search" :size="14" />
            搜索
          </button>
        </div>
      </div>

      <div class="button-row">
        <button
          class="secondary btn-sm"
          type="button"
          :aria-expanded="importDrawerOpen"
          @click="importDrawerOpen = !importDrawerOpen"
        >
          <StudioIcon name="upload" :size="14" />
          导入 / 恢复
        </button>
        <button class="secondary btn-sm" type="button" @click="store.handleBackupZip">
          <StudioIcon name="download" :size="14" />
          备份曲库 (.zip)
        </button>
      </div>
    </header>

    <div v-show="importDrawerOpen" class="library-import-strip">
      <div class="import-col">
        <h2 class="subsection-heading">导入本地 MIDI / 音视频</h2>
        <div class="file-picker-wrap">
          <input
            id="library-media-file"
            type="file"
            aria-label="导入本地 MIDI 或音视频文件"
            accept=".mid,.midi,.wav,.mp3,.flac,.ogg,.oga,.opus,.m4a,.m4b,.aac,.wma,.aiff,.aif,.m4s,.mp4,.m4v,.mkv,.webm,.mov,.avi,.flv,.wmv,.ts,.m2ts,.mts,.3gp,.mpg,.mpeg,.vob,.ogv"
            @change="onUploadFileChange"
          />
        </div>
        <div class="row">
          <div class="field" style="flex: 1 1 110px">
            <label for="library-import-title">曲目标题（可选）</label>
            <input id="library-import-title" v-model="store.importTitle.value" type="text" />
          </div>
          <div class="field" style="flex: 1 1 110px">
            <label for="library-import-artist">艺人（可选）</label>
            <input id="library-import-artist" v-model="store.importArtist.value" type="text" />
          </div>
          <div class="field" style="flex: 1 1 110px">
            <label for="library-import-tags">标签（逗号分隔）</label>
            <input
              id="library-import-tags"
              v-model="store.importTags.value"
              type="text"
              placeholder="windsong, anime"
            />
          </div>
        </div>
        <div>
          <button
            class="primary btn-sm"
            type="button"
            :disabled="store.busy.value"
            @click="store.handleImport"
          >
            <StudioIcon name="upload" :size="14" />
            导入本地文件
          </button>
        </div>
      </div>

      <div class="import-col">
        <h2 class="subsection-heading">导入 .lyrapack 分享包</h2>
        <div class="file-picker-wrap">
          <input
            id="library-pack-file"
            type="file"
            aria-label="导入他人分享的 .lyrapack 曲谱包"
            accept=".lyrapack,.zip"
            @change="onPackFileChange"
          />
        </div>
        <p class="muted" style="margin: 0; font-size: 12px">
          分享包仅含编曲键位事件与许可声明，自动校验 SHA-256 与压缩路径安全。
        </p>
        <div>
          <button
            class="secondary btn-sm"
            type="button"
            :disabled="store.busy.value"
            @click="store.handleImportLyrapack"
          >
            导入 .lyrapack 分享包
          </button>
        </div>
      </div>

      <div class="import-col">
        <h2 class="subsection-heading">从全库备份恢复 (.zip)</h2>
        <div class="file-picker-wrap">
          <input
            id="library-restore-file"
            type="file"
            aria-label="从全库备份 ZIP 恢复曲库"
            accept=".zip"
            @change="onRestoreFileChange"
          />
        </div>
        <label class="checkbox-row" style="font-size: 12px">
          <input v-model="store.restoreConfirmed.value" type="checkbox" />
          确认替换当前本地曲库（系统密钥保管库保持独立不变）
        </label>
        <div>
          <button
            class="secondary btn-sm"
            type="button"
            :disabled="store.busy.value"
            @click="store.handleRestoreBackupZip"
          >
            恢复曲库备份 (.zip)
          </button>
        </div>
      </div>
    </div>

    <div class="library-split">
      <div class="library-table-pane table-wrap" tabindex="0" role="region" aria-label="曲目清单">
        <table v-if="store.songs.value.length > 0" class="data-table">
          <thead>
            <tr>
              <th>曲目名称</th>
              <th>标签</th>
              <th>版本</th>
              <th style="text-align: end">快捷操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="song in store.songs.value"
              :key="song.id"
              :class="{ selected: store.selectedSongId.value === song.id }"
              @click="store.selectSong(song.id)"
            >
              <td class="td-title">
                <div class="td-title-stack">
                  <strong class="truncate" :title="song.title">{{ song.title }}</strong>
                  <span class="muted truncate" style="font-size: 12px">
                    {{ song.artist || "未署名艺人" }}
                  </span>
                </div>
              </td>
              <td>
                <div v-if="song.tags.length > 0" class="button-row">
                  <span v-for="tag in song.tags.slice(0, 2)" :key="tag" class="pill">{{ tag }}</span>
                </div>
                <span v-else class="muted" style="font-size: 12px">无标签</span>
              </td>
              <td class="tabular">{{ song.arrangement_count ?? 0 }}</td>
              <td style="text-align: end" @click.stop>
                <div class="button-row" style="justify-content: flex-end; flex-wrap: nowrap">
                  <button
                    type="button"
                    class="secondary btn-sm"
                    @click="store.selectSong(song.id).then(() => store.setView('studio'))"
                  >
                    编曲
                  </button>
                  <button
                    type="button"
                    class="ghost btn-sm"
                    @click="store.selectSong(song.id).then(() => store.setView('playback'))"
                  >
                    演奏
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-else class="empty-state" style="margin: var(--space-md)">
          <StudioIcon name="music" :size="22" />
          <p style="margin: 0">未匹配到符合条件的本地曲目。</p>
          <button
            type="button"
            class="secondary btn-sm"
            @click="importDrawerOpen = true"
          >
            导入本地文件
          </button>
        </div>
      </div>

      <aside class="library-inspector" aria-label="曲目详情与版本管理">
        <template v-if="store.selectedSong.value">
          <div class="inspector-head">
            <div class="inspector-title-wrap">
              <h2 class="inspector-title">{{ store.selectedSong.value.title }}</h2>
              <div class="meta-row">
                <span>{{ store.selectedSong.value.artist || "未署名艺人" }}</span>
                <code>{{ store.selectedSong.value.id.slice(0, 8) }}</code>
              </div>
            </div>
            <div class="button-row">
              <button
                v-if="store.hasAudioSource.value"
                class="secondary btn-sm"
                type="button"
                @click="store.setView('transcribe')"
              >
                音频转谱
              </button>
              <button class="primary btn-sm" type="button" @click="store.setView('studio')">
                <StudioIcon name="sliders" :size="14" />
                进入编曲工作室
              </button>
            </div>
          </div>

          <div class="section-block">
            <h3 class="subsection-heading">媒体来源 ({{ store.songSources.value.length }})</h3>
            <ul v-if="store.songSources.value.length > 0" class="line-list">
              <li v-for="src in store.songSources.value" :key="src.id" class="line-list-row">
                <span class="pill">{{ src.kind.toUpperCase() }}</span>
                <span class="truncate" style="flex: 1; font-size: 13px" :title="src.original_name || src.id">
                  {{ src.original_name || src.id }}
                </span>
              </li>
            </ul>
            <p v-else class="muted" style="margin: 0; font-size: 12px">当前曲目尚无关联来源记录。</p>
          </div>

          <div class="section-block">
            <h3 class="subsection-heading">历史转谱记录 ({{ store.songTranscriptions.value.length }})</h3>
            <ul v-if="store.songTranscriptions.value.length > 0" class="line-list">
              <li v-for="tr in store.songTranscriptions.value" :key="tr.id" class="line-list-row">
                <span class="pill" :class="tr.status === 'completed' ? 'pill-ok' : ''">
                  {{ tr.engine }}
                </span>
                <div class="meta-row">
                  <span>{{ tr.status }}</span>
                  <span>{{ tr.note_count }} 音符</span>
                </div>
              </li>
            </ul>
            <p v-else class="muted" style="margin: 0; font-size: 12px">
              暂无音频转谱记录（纯 MIDI 来源可直接进入编曲）。
            </p>
          </div>

          <div class="section-block">
            <h3 class="subsection-heading">已保存编曲版本 ({{ store.arrangements.value.length }})</h3>
            <ul v-if="store.arrangements.value.length > 0" class="line-list">
              <li
                v-for="(arr, index) in store.arrangements.value"
                :key="arr.id"
                class="arr-row"
                :class="{ selected: store.selectedArrId.value === arr.id }"
              >
                <div class="arr-row-head">
                  <strong class="truncate" :title="arrangementTitle(arr)">
                    <span class="arr-idx">#{{ store.arrangements.value.length - index }}</span>
                    {{ arrangementTitle(arr) }}
                  </strong>
                  <div class="button-row" style="flex-shrink: 0">
                    <span v-if="arr.is_favorite" class="pill pill-warn">
                      <StudioIcon name="star" :size="12" />
                      已收藏
                    </span>
                    <span class="pill tabular">{{ arr.event_count }} 音符</span>
                  </div>
                </div>

                <div class="meta-row">
                  <span>可演奏 {{ Math.round(arr.playable_ratio * 100) }}%</span>
                  <span>{{ arr.speed }}x</span>
                  <span>{{ arr.profile_id }}</span>
                  <span v-if="arr.created_at">
                    {{ new Date(arr.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) }}
                  </span>
                </div>

                <div v-if="editingId === arr.id" class="row" style="margin-block-start: var(--space-xs)">
                  <input
                    v-model="editingLabel"
                    type="text"
                    placeholder="输入版本名称"
                    style="flex: 1 1 160px"
                    @keyup.enter="saveRename"
                  />
                  <button class="primary btn-sm" type="button" @click="saveRename">保存</button>
                  <button class="ghost btn-sm" type="button" @click="editingId = null">取消</button>
                </div>

                <div class="button-row" style="margin-block-start: var(--space-xs)">
                  <button
                    class="ghost btn-sm"
                    type="button"
                    @click="startRename(arr.id, arrangementTitle(arr))"
                  >
                    <StudioIcon name="edit" :size="13" />
                    重命名
                  </button>
                  <button
                    class="secondary btn-sm"
                    type="button"
                    @click="store.selectArrangement(arr.id).then(() => store.setView('studio'))"
                  >
                    在 Piano Roll 打开
                  </button>
                  <button
                    class="ghost btn-sm"
                    type="button"
                    @click="store.selectArrangement(arr.id).then(() => store.setView('playback'))"
                  >
                    试听 / 演奏
                  </button>
                  <button
                    v-if="confirmDeleteArrId !== arr.id"
                    class="ghost btn-sm"
                    type="button"
                    aria-label="删除编曲版本"
                    :disabled="store.busy.value"
                    @click="confirmDeleteArrId = arr.id"
                  >
                    <StudioIcon name="trash" :size="13" />
                    删除
                  </button>
                  <template v-else>
                    <button
                      class="danger btn-sm"
                      type="button"
                      :disabled="store.busy.value"
                      @click="confirmDeleteArrangement(arr.id)"
                    >
                      确认删除
                    </button>
                    <button
                      class="ghost btn-sm"
                      type="button"
                      @click="confirmDeleteArrId = null"
                    >
                      取消
                    </button>
                  </template>
                </div>
              </li>
            </ul>
            <p v-else class="muted" style="margin: 0; font-size: 12px">
              该曲目尚未生成编曲版本，请进入编曲工作室生成。
            </p>
          </div>
        </template>

        <div v-else class="empty-state">
          <StudioIcon name="music" :size="22" />
          <p style="margin: 0">从左侧曲库列表选择一首曲目，即可在此管理媒体来源与编曲版本。</p>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.library-shell {
  block-size: 100%;
  display: flex;
  flex-direction: column;
  min-block-size: 0;
  min-inline-size: 0;
  overflow: hidden;
}

.library-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-xs) var(--space-sm);
  padding: var(--space-xs) var(--space-md);
  background: var(--color-paper-2);
  border-block-end: var(--rule-hair) solid var(--color-rule);
  flex-shrink: 0;
}

.library-toolbar-left {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-sm);
  min-inline-size: 0;
}

.library-filter-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-xs);
  min-inline-size: 0;
}

.lib-input-search {
  inline-size: 180px !important;
}

.lib-input-tag {
  inline-size: 130px !important;
}

.library-import-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-md);
  padding: var(--space-sm) var(--space-md);
  background: var(--color-paper-2);
  border-block-end: var(--rule-hair) solid var(--color-rule-strong);
  flex-shrink: 0;
}

.import-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  min-inline-size: 0;
}

.import-col + .import-col {
  padding-inline-start: var(--space-md);
  border-inline-start: var(--rule-hair) solid var(--color-rule);
}

.library-split {
  flex: 1 1 auto;
  min-block-size: 0;
  min-inline-size: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 440px);
}

.library-table-pane {
  border-inline-end: var(--rule-hair) solid var(--color-rule);
  min-inline-size: 0;
  min-block-size: 0;
}

.td-title {
  max-inline-size: 320px;
}

.td-title-stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-3xs);
  min-inline-size: 0;
}

.library-inspector {
  background: var(--color-paper-2);
  padding: var(--space-md);
  overflow-y: auto;
  min-inline-size: 0;
  min-block-size: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  scrollbar-color: var(--sb-thumb) var(--sb-track);
  scrollbar-width: auto;
}

.inspector-head {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  min-inline-size: 0;
}

.inspector-title-wrap {
  min-inline-size: 0;
}

.inspector-title {
  margin: 0 0 var(--space-2xs);
  font-size: 16px;
  overflow-wrap: break-word;
  min-inline-size: 0;
}

.arr-row {
  padding: var(--space-sm) var(--space-xs);
  border-block-end: var(--rule-hair) solid var(--color-rule);
  display: flex;
  flex-direction: column;
  gap: var(--space-2xs);
  min-inline-size: 0;
}

.arr-row:first-child {
  border-block-start: var(--rule-hair) solid var(--color-rule);
}

.arr-row.selected {
  background: var(--color-accent-deep);
  box-shadow: inset 3px 0 0 var(--color-accent);
}

.arr-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-xs);
  min-inline-size: 0;
}

.arr-idx {
  font-family: var(--font-mono);
  color: var(--color-muted);
  margin-inline-end: var(--space-2xs);
}

@media (max-width: 960px) {
  .library-import-strip {
    grid-template-columns: minmax(0, 1fr);
  }

  .import-col + .import-col {
    padding-inline-start: 0;
    padding-block-start: var(--space-sm);
    border-inline-start: 0;
    border-block-start: var(--rule-hair) solid var(--color-rule);
  }

  .library-split {
    grid-template-columns: minmax(0, 1fr);
    overflow-y: auto;
  }

  .library-table-pane {
    border-inline-end: 0;
    border-block-end: var(--rule-hair) solid var(--color-rule);
    max-block-size: 320px;
  }
}
</style>
