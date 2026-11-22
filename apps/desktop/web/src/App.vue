<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  LyraForgeApi,
  type AgentRunResult,
  type ArrangementDetailResponse,
  type ArrangementRecord,
  type ComparisonResult,
  type HealthResponse,
  type PerformanceEventItem,
  type PlaybackPrepareResponse,
  type PlaybackStatusResponse,
  type ProfileDetail,
  type ProfileSummary,
  type SongSummary,
  type SourceRecord,
  type TranscriberInfo,
  type TranscriptionJob,
  type TranscriptionRecord,
} from "./api";
import LyreKeyboard from "./components/LyreKeyboard.vue";
import PianoRollEditor from "./components/PianoRollEditor.vue";

const props = defineProps<{
  client?: LyraForgeApi;
}>();

const api = props.client ?? new LyraForgeApi();

const health = ref<HealthResponse | null>(null);
const profiles = ref<ProfileSummary[]>([]);
const selectedProfileId = ref("genshin.windsong_lyre.v1");
const profile = ref<ProfileDetail | null>(null);
const transcribers = ref<TranscriberInfo[]>([]);
const songs = ref<SongSummary[]>([]);
const searchQuery = ref("");
const filterTag = ref("");
const filterFavoritesOnly = ref(false);
const selectedSongId = ref<string | null>(null);
const songSources = ref<SourceRecord[]>([]);
const songTranscriptions = ref<TranscriptionRecord[]>([]);
const arrangements = ref<ArrangementRecord[]>([]);
const selectedArrId = ref<string>("");
const arrDetail = ref<ArrangementDetailResponse | null>(null);
const comparisonResult = ref<ComparisonResult | null>(null);

// Import form
const uploadFile = ref<File | null>(null);
const importTitle = ref("");
const importArtist = ref("");
const importTags = ref("");
const packFile = ref<File | null>(null);
const packRightsConfirmed = ref(false);

// Transcribe form
const selectedEngineId = ref("builtin-mono");
const activeJob = ref<TranscriptionJob | null>(null);

// Arrange form
const style = ref<"melody" | "balanced" | "rich">("balanced");
const speed = ref(1.0);
const transposeInput = ref("auto");
const arpeggiateMs = ref(0);

// Preview audio
const previewUrl = ref<string | null>(null);

// Playback
const playbackMode = ref<"dry-run" | "windows">("dry-run");
const realtime = ref(true);
const prepared = ref<PlaybackPrepareResponse | null>(null);
const playbackStatus = ref<PlaybackStatusResponse | null>(null);

// Settings
const allowedTitlesSetting = ref("Genshin Impact, 原神");
const llmEnabledSetting = ref(false);
const llmBaseUrlSetting = ref("");
const llmModelSetting = ref("");
const llmApiKeySetting = ref("");

// Agent
const agentPrompt = ref("");
const agentAllowNetwork = ref(false);
const agentResult = ref<AgentRunResult | null>(null);

// Feedback
const busy = ref(false);
const statusMessage = ref("");
const errorMessage = ref("");

let pollTimer: number | null = null;
let jobPollTimer: number | null = null;

const hasMidiSource = computed(() => songSources.value.some((s) => s.kind === "midi"));
const hasAudioSource = computed(() => songSources.value.some((s) => s.kind === "audio"));
const canArrange = computed(
  () => hasMidiSource.value || songTranscriptions.value.some((t) => t.status === "completed"),
);
const selectedEngineInfo = computed(
  () => transcribers.value.find((t) => t.id === selectedEngineId.value) ?? null,
);

const eventCounts = computed<Record<string, number>>(() => {
  const counts: Record<string, number> = {};
  for (const ev of arrDetail.value?.performance.events ?? []) {
    counts[ev.key_id] = (counts[ev.key_id] ?? 0) + 1;
  }
  return counts;
});

function clearPreviewUrl(): void {
  if (previewUrl.value && previewUrl.value.startsWith("blob:")) {
    URL.revokeObjectURL(previewUrl.value);
  }
  previewUrl.value = null;
}

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

function stopJobPolling(): void {
  if (jobPollTimer !== null) {
    window.clearInterval(jobPollTimer);
    jobPollTimer = null;
  }
}

async function refreshSongs(): Promise<void> {
  const opts =
    filterTag.value.trim() || filterFavoritesOnly.value
      ? { tag: filterTag.value.trim(), favoritesOnly: filterFavoritesOnly.value }
      : undefined;
  const res = opts ? await api.listSongs(searchQuery.value, opts) : await api.listSongs(searchQuery.value);
  songs.value = res.songs;
  if (!selectedSongId.value && songs.value.length > 0) {
    await selectSong(songs.value[0].id);
  }
}

async function selectSong(songId: string): Promise<void> {
  selectedSongId.value = songId;
  prepared.value = null;
  comparisonResult.value = null;
  clearPreviewUrl();
  const detail = await api.getSong(songId);
  songSources.value = detail.sources ?? [];
  songTranscriptions.value = detail.transcriptions ?? [];
  arrangements.value = detail.arrangements;
  if (detail.arrangements.length > 0) {
    await selectArrangement(detail.arrangements[0].id);
  } else {
    selectedArrId.value = "";
    arrDetail.value = null;
  }
}

async function selectArrangement(arrangementId: string): Promise<void> {
  selectedArrId.value = arrangementId;
  prepared.value = null;
  clearPreviewUrl();
  if (!arrangementId) {
    arrDetail.value = null;
    return;
  }
  const detail = await api.getArrangement(arrangementId);
  arrDetail.value = detail;
  if (detail.arrangement.profile_id && profile.value?.id !== detail.arrangement.profile_id) {
    selectedProfileId.value = detail.arrangement.profile_id;
    profile.value = await api.getProfile(detail.arrangement.profile_id);
  }
}

async function handleProfileChange(): Promise<void> {
  errorMessage.value = "";
  try {
    profile.value = await api.getProfile(selectedProfileId.value);
  } catch (err) {
    errorMessage.value = (err as Error).message;
  }
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  uploadFile.value = input.files?.[0] ?? null;
}

async function handleImport(): Promise<void> {
  if (!uploadFile.value) {
    errorMessage.value = "请先选择一个 .mid/.midi 或音视频文件";
    return;
  }
  busy.value = true;
  errorMessage.value = "";
  try {
    const res = await api.importMedia(
      uploadFile.value,
      importTitle.value,
      importArtist.value,
      importTags.value,
    );
    importTitle.value = "";
    importArtist.value = "";
    importTags.value = "";
    await refreshSongs();
    await selectSong(res.song.id);
    statusMessage.value = `已导入曲目：${res.song.title}`;
  } catch (err) {
    errorMessage.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

async function handleStartTranscribe(): Promise<void> {
  if (!selectedSongId.value) return;
  busy.value = true;
  errorMessage.value = "";
  try {
    const { job } = await api.submitTranscribeJob(selectedSongId.value, selectedEngineId.value);
    activeJob.value = job;
    statusMessage.value = `已提交音频转谱任务 (${job.engine_id})`;
    stopJobPolling();
    jobPollTimer = window.setInterval(async () => {
      if (!activeJob.value) {
        stopJobPolling();
        return;
      }
      try {
        const res = await api.getJob(activeJob.value.id);
        activeJob.value = res.job;
        if (res.job.status === "completed") {
          stopJobPolling();
          if (selectedSongId.value) {
            await selectSong(selectedSongId.value);
          }
          statusMessage.value = `音频转谱完成，共保留 ${res.job.transcription?.note_count ?? 0} 个音符`;
        } else if (res.job.status === "cancelled" || res.job.status === "failed") {
          stopJobPolling();
          if (res.job.error) {
            errorMessage.value = res.job.error.message;
          } else {
            statusMessage.value = "音频转谱已取消";
          }
        }
      } catch {
        stopJobPolling();
      }
    }, 150);
  } catch (err) {
    errorMessage.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

async function handleCancelTranscribe(): Promise<void> {
  if (!activeJob.value) return;
  try {
    const res = await api.cancelJob(activeJob.value.id);
    activeJob.value = res.job;
    stopJobPolling();
    statusMessage.value = "已请求取消音频转谱";
  } catch (err) {
    errorMessage.value = (err as Error).message;
  }
}

async function handleArrange(): Promise<void> {
  if (!selectedSongId.value) return;
  const parsedTranspose =
    transposeInput.value.trim() === "auto" || transposeInput.value.trim() === ""
      ? null
      : Number(transposeInput.value);
  if (parsedTranspose !== null && !Number.isInteger(parsedTranspose)) {
    errorMessage.value = "移调请输入 auto 或整数半音";
    return;
  }
  busy.value = true;
  errorMessage.value = "";
  try {
    const res = await api.arrangeSong({
      song_id: selectedSongId.value,
      instrument_profile_id: selectedProfileId.value,
      style: style.value,
      speed: speed.value,
      transpose: parsedTranspose,
      arpeggiate_ms: Math.max(0, Math.min(60, Math.round(Number(arpeggiateMs.value) || 0))),
      prefer_melody_track: true,
    });
    comparisonResult.value = null;
    await refreshSongs();
    await selectSong(selectedSongId.value);
    await selectArrangement(res.arrangement.id);
    statusMessage.value = `已生成 ${res.arrangement.style} 版本（${res.arrangement.event_count} 个音符）`;
  } catch (err) {
    errorMessage.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

async function handleArrangeAB(): Promise<void> {
  if (!selectedSongId.value) return;
  const parsedTranspose =
    transposeInput.value.trim() === "auto" || transposeInput.value.trim() === ""
      ? null
      : Number(transposeInput.value);
  if (parsedTranspose !== null && !Number.isInteger(parsedTranspose)) {
    errorMessage.value = "移调请输入 auto 或整数半音";
    return;
  }
  busy.value = true;
  errorMessage.value = "";
  try {
    const res = await api.arrangeAB({
      song_id: selectedSongId.value,
      instrument_profile_id: selectedProfileId.value,
      variant_a: {
        style: "balanced",
        speed: speed.value,
        transpose: parsedTranspose,
        arpeggiate_ms: 0,
        label: "A · 均衡主旋律",
      },
      variant_b: {
        style: "rich",
        speed: speed.value,
        transpose: parsedTranspose,
        arpeggiate_ms: 20,
        label: "B · 丰满琶音",
      },
    });
    await refreshSongs();
    await selectSong(selectedSongId.value);
    comparisonResult.value = res.comparison;
    const pickId =
      res.comparison.winner === res.arrangement_b.id
        ? res.arrangement_b.id
        : res.arrangement_a.id;
    await selectArrangement(pickId);
    statusMessage.value = `A/B 对比完成：${res.comparison.summary}`;
  } catch (err) {
    errorMessage.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

async function handleSaveEdited(payload: {
  events: PerformanceEventItem[];
  label: string;
}): Promise<void> {
  if (!selectedArrId.value || !selectedSongId.value) return;
  busy.value = true;
  errorMessage.value = "";
  try {
    const res = await api.editArrangement(selectedArrId.value, payload.events, payload.label);
    await refreshSongs();
    await selectSong(selectedSongId.value);
    await selectArrangement(res.arrangement.id);
    statusMessage.value = `已保存新版本：${res.arrangement.label ?? "手动编辑"}`;
  } catch (err) {
    errorMessage.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

async function handleToggleFavorite(): Promise<void> {
  if (!arrDetail.value) return;
  errorMessage.value = "";
  try {
    const nextFav = !arrDetail.value.arrangement.is_favorite;
    const res = await api.setFavorite(arrDetail.value.arrangement.id, nextFav);
    arrDetail.value = { ...arrDetail.value, arrangement: res.arrangement };
    arrangements.value = arrangements.value.map((a) =>
      a.id === res.arrangement.id ? res.arrangement : a,
    );
    statusMessage.value = nextFav ? "已收藏该改编版本" : "已取消收藏";
  } catch (err) {
    errorMessage.value = (err as Error).message;
  }
}

async function handleVote(vote: -1 | 1): Promise<void> {
  if (!arrDetail.value) return;
  errorMessage.value = "";
  try {
    const nextVote: -1 | 0 | 1 = arrDetail.value.arrangement.user_vote === vote ? 0 : vote;
    const res = await api.setVote(arrDetail.value.arrangement.id, nextVote);
    arrDetail.value = { ...arrDetail.value, arrangement: res.arrangement };
    arrangements.value = arrangements.value.map((a) =>
      a.id === res.arrangement.id ? res.arrangement : a,
    );
  } catch (err) {
    errorMessage.value = (err as Error).message;
  }
}

async function handlePreview(): Promise<void> {
  if (!selectedArrId.value) return;
  busy.value = true;
  errorMessage.value = "";
  clearPreviewUrl();
  try {
    previewUrl.value = await api.fetchPreviewAudioUrl(selectedArrId.value);
    statusMessage.value = "已合成离线试听 WAV，请点击下方播放器试听";
  } catch (err) {
    errorMessage.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function handleExport(fmt: "midi" | "json"): Promise<void> {
  if (!selectedArrId.value) return;
  errorMessage.value = "";
  try {
    const blob = await api.downloadExport(selectedArrId.value, fmt);
    triggerBlobDownload(blob, `${selectedArrId.value}.${fmt === "midi" ? "mid" : "json"}`);
    statusMessage.value = `已导出 ${fmt.toUpperCase()} 文件`;
  } catch (err) {
    errorMessage.value = (err as Error).message;
  }
}

async function handleExportLyrapack(): Promise<void> {
  if (!selectedArrId.value) return;
  if (!packRightsConfirmed.value) {
    errorMessage.value = "请先勾选版权授权确认（分享包默认不包含任何原始音频）";
    return;
  }
  errorMessage.value = "";
  try {
    const blob = await api.exportLyrapack(selectedArrId.value, true);
    triggerBlobDownload(blob, `${selectedArrId.value}.lyrapack`);
    statusMessage.value = "已导出 .lyrapack 分享包（不含原始音频）";
  } catch (err) {
    errorMessage.value = (err as Error).message;
  }
}

function onPackFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  packFile.value = input.files?.[0] ?? null;
}

async function handleImportLyrapack(): Promise<void> {
  if (!packFile.value) {
    errorMessage.value = "请先选择一个 .lyrapack 分享包文件";
    return;
  }
  busy.value = true;
  errorMessage.value = "";
  try {
    const res = await api.importLyrapack(packFile.value);
    await refreshSongs();
    await selectSong(res.song.id);
    await selectArrangement(res.arrangement.id);
    statusMessage.value = `已导入分享包曲目：${res.song.title}`;
  } catch (err) {
    errorMessage.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

async function handleBackupZip(): Promise<void> {
  errorMessage.value = "";
  try {
    const blob = await api.downloadBackupZip();
    triggerBlobDownload(blob, "lyraforge-backup.zip");
    statusMessage.value = "已下载本地曲库完整备份 ZIP";
  } catch (err) {
    errorMessage.value = (err as Error).message;
  }
}

async function handleSaveSettings(): Promise<void> {
  errorMessage.value = "";
  try {
    await api.saveSetting("default_style", style.value);
    await api.saveSetting("windows_allowed_titles", allowedTitlesSetting.value);
    await api.saveSetting("llm_enabled", llmEnabledSetting.value);
    if (llmBaseUrlSetting.value.trim()) {
      await api.saveSetting("llm_base_url", llmBaseUrlSetting.value.trim());
    }
    if (llmModelSetting.value.trim()) {
      await api.saveSetting("llm_model", llmModelSetting.value.trim());
    }
    if (llmApiKeySetting.value.trim()) {
      await api.saveSetting("llm_api_key", llmApiKeySetting.value.trim());
    }
    statusMessage.value = "设置已保存至本地曲库";
  } catch (err) {
    errorMessage.value = (err as Error).message;
  }
}

async function handleRunAgent(overrideAllowNetwork?: boolean): Promise<void> {
  const promptText = agentPrompt.value.trim();
  if (!promptText) {
    errorMessage.value = "请输入自然语言指令（例如歌名、乐器与编曲偏好）";
    return;
  }
  busy.value = true;
  errorMessage.value = "";
  try {
    const res = await api.runAgent({
      prompt: promptText,
      song_id: selectedSongId.value,
      arrangement_id: selectedArrId.value || null,
      allow_network: overrideAllowNetwork ?? agentAllowNetwork.value,
    });
    agentResult.value = res;
    if (res.status === "completed") {
      await refreshSongs();
      if (res.selected_song?.id) {
        await selectSong(res.selected_song.id);
      }
      if (res.selected_arrangement?.id) {
        await selectArrangement(res.selected_arrangement.id);
      }
      if (res.comparison) {
        comparisonResult.value = res.comparison;
      }
      statusMessage.value = res.message;
    } else if (res.requires_confirmation) {
      statusMessage.value = res.confirmation_prompt ?? res.message;
    } else {
      statusMessage.value = res.message;
    }
  } catch (err) {
    errorMessage.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

async function handlePrepare(): Promise<void> {
  if (!selectedArrId.value) return;
  busy.value = true;
  errorMessage.value = "";
  try {
    prepared.value = await api.preparePlayback({
      arrangement_id: selectedArrId.value,
      mode: playbackMode.value,
      realtime: realtime.value,
    });
    statusMessage.value = "已准备就绪，请阅读下方提示后显式点击确认开始";
  } catch (err) {
    errorMessage.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

async function handleStart(): Promise<void> {
  if (!prepared.value) return;
  busy.value = true;
  errorMessage.value = "";
  try {
    await api.startPlayback(prepared.value.prepare_token);
    prepared.value = null;
    playbackStatus.value = await api.playbackStatus();
    statusMessage.value = "演奏已启动";
    stopPolling();
    pollTimer = window.setInterval(async () => {
      try {
        playbackStatus.value = await api.playbackStatus();
        if (playbackStatus.value.state !== "running") {
          stopPolling();
          statusMessage.value = `演奏已结束（状态：${playbackStatus.value.state}）`;
        }
      } catch {
        stopPolling();
      }
    }, 200);
  } catch (err) {
    errorMessage.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

async function handleEmergencyStop(): Promise<void> {
  errorMessage.value = "";
  try {
    playbackStatus.value = await api.stopPlayback();
    prepared.value = null;
    stopPolling();
    statusMessage.value = "已紧急停止并释放所有按键";
  } catch (err) {
    errorMessage.value = (err as Error).message;
  }
}

onMounted(async () => {
  try {
    health.value = await api.health();
    const profList = await api.listProfiles();
    profiles.value = profList.profiles;
    if (
      profList.profiles.length > 0 &&
      !profList.profiles.some((p) => p.id === selectedProfileId.value)
    ) {
      selectedProfileId.value = profList.profiles[0].id;
    }
    profile.value = await api.getProfile(selectedProfileId.value);
    transcribers.value = (await api.listTranscribers()).transcribers;
    const { settings } = await api.getSettings();
    if (
      settings.default_style === "melody" ||
      settings.default_style === "balanced" ||
      settings.default_style === "rich"
    ) {
      style.value = settings.default_style;
    }
    if (typeof settings.windows_allowed_titles === "string") {
      allowedTitlesSetting.value = settings.windows_allowed_titles;
    }
    if (typeof settings.llm_enabled === "boolean") {
      llmEnabledSetting.value = settings.llm_enabled;
    }
    if (typeof settings.llm_base_url === "string") {
      llmBaseUrlSetting.value = settings.llm_base_url;
    }
    if (typeof settings.llm_model === "string") {
      llmModelSetting.value = settings.llm_model;
    }
    await refreshSongs();
    playbackStatus.value = await api.playbackStatus();
  } catch (err) {
    errorMessage.value = `初始化失败：${(err as Error).message}`;
  }
});

onBeforeUnmount(() => {
  stopPolling();
  stopJobPolling();
  clearPreviewUrl();
});
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <h1>LyraForge 工作台</h1>
      <div class="badges" v-if="health">
        <span class="badge">版本 {{ health.version }}</span>
        <span class="badge">运行环境 {{ health.platform }}</span>
        <span class="badge">
          {{ health.windows_playback_available ? "支持 Windows 按键 + DryRun" : "macOS DryRun 模拟模式" }}
        </span>
      </div>
    </header>

    <div class="workspace">
      <aside class="panel" aria-label="本地曲库与导入">
        <section>
          <h2>导入本地 MIDI 或音视频</h2>
          <div class="field">
            <label for="midi-upload">媒体 / MIDI 文件</label>
            <input
              id="midi-upload"
              type="file"
              accept=".mid,.midi,.wav,.mp3,.flac,.ogg,.m4a,.mp4,.mkv"
              @change="onFileChange"
            />
          </div>
          <div class="row">
            <div class="field" style="flex: 1">
              <label for="import-title">曲名（可选）</label>
              <input id="import-title" v-model="importTitle" type="text" placeholder="留空取文件名" />
            </div>
            <div class="field" style="flex: 1">
              <label for="import-artist">作者（可选）</label>
              <input id="import-artist" v-model="importArtist" type="text" />
            </div>
          </div>
          <div class="field">
            <label for="import-tags">标签（逗号分隔）</label>
            <input id="import-tags" v-model="importTags" type="text" placeholder="demo,lyre" />
          </div>
          <button type="button" class="primary" :disabled="busy" @click="handleImport">
            导入曲库
          </button>
        </section>

        <section>
          <h2>本地曲库（{{ songs.length }}）</h2>
          <div class="row">
            <div class="field" style="flex: 1">
              <label for="library-search">搜索曲库</label>
              <input
                id="library-search"
                v-model="searchQuery"
                type="search"
                placeholder="歌名 / 作者 / 标签"
                @keyup.enter="refreshSongs"
              />
            </div>
            <div class="field">
              <label for="library-tag-filter">分类标签</label>
              <input
                id="library-tag-filter"
                v-model="filterTag"
                type="text"
                placeholder="如 genshin"
                @keyup.enter="refreshSongs"
              />
            </div>
            <button type="button" :disabled="busy" @click="refreshSongs">搜索</button>
          </div>
          <div class="button-row" style="margin: 6px 0">
            <label class="checkbox-row">
              <input v-model="filterFavoritesOnly" type="checkbox" @change="refreshSongs" />
              <span>仅看已收藏版本</span>
            </label>
            <button type="button" class="btn-secondary" :disabled="busy" @click="handleBackupZip">
              备份曲库 (.zip)
            </button>
          </div>
          <div class="row" style="margin-bottom: 8px; align-items: flex-end">
            <div class="field" style="flex: 1">
              <label for="lyrapack-upload">导入分享包 (.lyrapack)</label>
              <input
                id="lyrapack-upload"
                type="file"
                accept=".lyrapack,.zip"
                @change="onPackFileChange"
              />
            </div>
            <button type="button" class="btn-secondary" :disabled="busy" @click="handleImportLyrapack">
              导入分享包
            </button>
          </div>

          <ul v-if="songs.length > 0" class="song-list">
            <li v-for="s in songs" :key="s.id">
              <button
                type="button"
                class="song-item"
                :class="{ selected: s.id === selectedSongId }"
                :aria-current="s.id === selectedSongId ? 'true' : undefined"
                @click="selectSong(s.id)"
              >
                <strong>{{ s.title }}</strong>
                <span class="muted">
                  {{ s.artist || "未知作者" }} · {{ s.arrangement_count }} 个改编版本
                </span>
              </button>
            </li>
          </ul>
          <p v-else class="muted">暂无曲目，请先导入一个本地 MIDI 或音视频文件。</p>
        </section>

        <details class="field">
          <summary>设置与默认偏好</summary>
          <div class="field" style="margin-top: 8px">
            <label for="setting-window-titles">Windows 允许焦点窗口标题（逗号分隔）</label>
            <input id="setting-window-titles" v-model="allowedTitlesSetting" type="text" />
          </div>
          <label class="checkbox-row" style="margin-top: 8px">
            <input v-model="llmEnabledSetting" type="checkbox" />
            <span>启用外部 LLM（默认离线规则解析）</span>
          </label>
          <div v-if="llmEnabledSetting" class="field" style="margin-top: 6px">
            <label for="setting-llm-url">LLM Base URL (OpenAI 兼容)</label>
            <input
              id="setting-llm-url"
              v-model="llmBaseUrlSetting"
              type="url"
              placeholder="http://127.0.0.1:11434/v1"
            />
            <label for="setting-llm-model">模型名称</label>
            <input id="setting-llm-model" v-model="llmModelSetting" type="text" placeholder="qwen2.5" />
            <label for="setting-llm-key">API Key（可选）</label>
            <input id="setting-llm-key" v-model="llmApiKeySetting" type="password" />
          </div>
          <button type="button" style="margin-top: 8px" @click="handleSaveSettings">
            保存设置
          </button>
        </details>
      </aside>

      <main class="panel">
        <div v-if="errorMessage" role="alert" class="banner-error">{{ errorMessage }}</div>
        <div v-if="statusMessage" role="status" aria-live="polite" class="badge">
          {{ statusMessage }}
        </div>

        <section class="agent-panel">
          <h2>AI Agent 智能编曲助手</h2>
          <div class="row">
            <div class="field" style="flex: 1">
              <label for="agent-prompt">自然语言指令（检索、转谱、优化、试听）</label>
              <input
                id="agent-prompt"
                v-model="agentPrompt"
                type="text"
                placeholder="例如：找《C Major Scale》转成风物之诗琴主旋律曲谱，优化并试听"
                @keyup.enter="handleRunAgent()"
              />
            </div>
            <button type="button" class="primary" :disabled="busy" @click="handleRunAgent()">
              执行智能编曲
            </button>
          </div>
          <div class="button-row" style="margin-top: 6px">
            <button
              type="button"
              class="btn-secondary"
              @click="agentPrompt = '转成风物之诗琴主旋律并优化'"
            >
              风物之诗琴主旋律
            </button>
            <button
              type="button"
              class="btn-secondary"
              @click="agentPrompt = '转成镜花之琴丰满琶音版'"
            >
              镜花之琴琶音版
            </button>
            <button
              type="button"
              class="btn-secondary"
              @click="agentPrompt = '升2个半音并对比优化'"
            >
              升2个半音并对比
            </button>
            <label class="checkbox-row">
              <input v-model="agentAllowNetwork" type="checkbox" />
              <span>允许下载指令中用户提供的外部直链（默认关闭）</span>
            </label>
          </div>

          <div v-if="agentResult" class="ab-card">
            <div class="row" style="justify-content: space-between; align-items: center">
              <strong>{{ agentResult.message }}</strong>
              <span class="badge">解析器: {{ agentResult.provider }}</span>
            </div>
            <div v-if="agentResult.requires_confirmation" class="banner-warn" style="margin-top: 8px">
              <p style="margin: 0 0 6px">{{ agentResult.confirmation_prompt }}</p>
              <button type="button" class="btn-primary" :disabled="busy" @click="handleRunAgent(true)">
                确认授权并继续下载
              </button>
            </div>
            <ol v-if="agentResult.steps.length > 0" class="agent-steps">
              <li v-for="(step, idx) in agentResult.steps" :key="idx">
                <code>{{ step.tool }}</code> [{{ step.status }}] — {{ step.detail }}
              </li>
            </ol>
          </div>
        </section>

        <section v-if="selectedSongId && hasAudioSource && !hasMidiSource">
          <h2>音频转 MIDI 转录</h2>
          <div class="row">
            <div class="field" style="flex: 1">
              <label for="transcribe-engine">识别引擎</label>
              <select id="transcribe-engine" v-model="selectedEngineId">
                <option
                  v-for="eng in transcribers"
                  :key="eng.id"
                  :value="eng.id"
                  :disabled="!eng.available"
                >
                  {{ eng.display_name }} {{ eng.available ? "" : "(未安装，需隔离环境)" }}
                </option>
              </select>
            </div>
            <button type="button" class="primary" :disabled="busy" @click="handleStartTranscribe">
              开始音频转谱
            </button>
            <button
              v-if="activeJob && (activeJob.status === 'queued' || activeJob.status === 'running')"
              type="button"
              class="danger"
              @click="handleCancelTranscribe"
            >
              取消转谱
            </button>
          </div>
          <p v-if="selectedEngineInfo" class="muted">{{ selectedEngineInfo.scope_note }}</p>
          <div v-if="activeJob" class="row" style="margin-top: 6px; align-items: center">
            <progress :value="activeJob.progress" max="1" />
            <span class="muted">
              {{ activeJob.status }} ({{ Math.round(activeJob.progress * 100) }}%) · {{ activeJob.stage }}
            </span>
          </div>
          <p v-if="songTranscriptions.length > 0" class="muted" style="margin-top: 6px">
            已有转录版本：{{ songTranscriptions[0].engine }} · {{ songTranscriptions[0].note_count }} 音符
          </p>
        </section>

        <section v-if="selectedSongId">
          <h2>编曲与版本管理（目标：{{ profile?.display_name ?? "风物之诗琴" }}）</h2>
          <div class="row">
            <div class="field" v-if="profiles.length > 0">
              <label for="profile-select">目标乐器</label>
              <select
                id="profile-select"
                v-model="selectedProfileId"
                @change="handleProfileChange"
              >
                <option v-for="p in profiles" :key="p.id" :value="p.id">
                  {{ p.display_name }} ({{ p.key_count }}键)
                </option>
              </select>
            </div>
            <div class="field">
              <label for="arrange-style">编曲风格</label>
              <select id="arrange-style" v-model="style">
                <option value="melody">主旋律优先 (melody)</option>
                <option value="balanced">平衡和声 (balanced)</option>
                <option value="rich">丰富和弦 (rich)</option>
              </select>
            </div>
            <div class="field">
              <label for="arrange-speed">倍速</label>
              <input
                id="arrange-speed"
                v-model.number="speed"
                type="number"
                min="0.25"
                max="4"
                step="0.05"
              />
            </div>
            <div class="field">
              <label for="arrange-transpose">移调（auto 或半音）</label>
              <input id="arrange-transpose" v-model="transposeInput" type="text" />
            </div>
            <div class="field">
              <label for="arrange-arp">柱式和弦琶音 (ms)</label>
              <input
                id="arrange-arp"
                v-model.number="arpeggiateMs"
                type="number"
                min="0"
                max="60"
                step="5"
              />
            </div>
            <button
              type="button"
              class="primary"
              :disabled="busy || !canArrange"
              @click="handleArrange"
            >
              生成改编版本
            </button>
            <button
              type="button"
              class="btn-secondary"
              :disabled="busy || !canArrange"
              @click="handleArrangeAB"
            >
              生成 A/B 对比版本
            </button>
          </div>

          <div v-if="comparisonResult" class="ab-card" style="margin-top: 10px">
            <div class="row" style="justify-content: space-between; align-items: center">
              <strong>A/B 编曲质量对比：{{ comparisonResult.summary }}</strong>
              <div class="button-row">
                <button type="button" class="btn-secondary" @click="selectArrangement(comparisonResult.id_a)">
                  使用版本 A ({{ comparisonResult.score_a.toFixed(1) }}分)
                </button>
                <button type="button" class="btn-secondary" @click="selectArrangement(comparisonResult.id_b)">
                  使用版本 B ({{ comparisonResult.score_b.toFixed(1) }}分)
                </button>
              </div>
            </div>
          </div>

          <div v-if="arrangements.length > 0" class="row" style="margin-top: 10px; align-items: flex-end">
            <div class="field" style="flex: 1">
              <label for="arrangement-select">已保存版本</label>
              <select
                id="arrangement-select"
                :value="selectedArrId"
                @change="selectArrangement(($event.target as HTMLSelectElement).value)"
              >
                <option v-for="a in arrangements" :key="a.id" :value="a.id">
                  {{ a.is_favorite ? "★ " : "" }}{{ a.label ? `${a.label} · ` : "" }}{{ a.style }} | 移调
                  {{ a.transpose >= 0 ? `+${a.transpose}` : a.transpose }} | {{ a.speed }}x |
                  {{ a.event_count }} 音 ({{ Math.round(a.playable_ratio * 100) }}%){{
                    a.score != null ? ` · ${a.score.toFixed(1)}分` : ""
                  }}
                </option>
              </select>
            </div>
            <div v-if="arrDetail" class="button-row">
              <button type="button" class="btn-secondary" @click="handleToggleFavorite">
                {{ arrDetail.arrangement.is_favorite ? "★ 已收藏" : "☆ 收藏" }}
              </button>
              <button
                type="button"
                class="btn-secondary"
                :aria-pressed="arrDetail.arrangement.user_vote === 1"
                @click="handleVote(1)"
              >
                👍 {{ arrDetail.arrangement.user_vote === 1 ? "已赞" : "推荐" }}
              </button>
              <button
                type="button"
                class="btn-secondary"
                :aria-pressed="arrDetail.arrangement.user_vote === -1"
                @click="handleVote(-1)"
              >
                👎 {{ arrDetail.arrangement.user_vote === -1 ? "不推荐" : "较差" }}
              </button>
            </div>
          </div>
        </section>

        <section v-if="arrDetail">
          <div class="stats-grid">
            <div class="stat-card" v-if="arrDetail.report?.quality">
              <div class="label">综合评分</div>
              <div class="value">{{ arrDetail.report.quality.overall_score.toFixed(1) }} / 100</div>
            </div>
            <div class="stat-card">
              <div class="label">可弹音比例</div>
              <div class="value">{{ Math.round(arrDetail.arrangement.playable_ratio * 100) }}%</div>
            </div>
            <div class="stat-card">
              <div class="label">输出音符数</div>
              <div class="value">{{ arrDetail.arrangement.event_count }}</div>
            </div>
            <div class="stat-card">
              <div class="label">时长</div>
              <div class="value">{{ (arrDetail.arrangement.duration_ms / 1000).toFixed(1) }} s</div>
            </div>
            <div class="stat-card">
              <div class="label">八度折叠 / 半音替换</div>
              <div class="value">
                {{ arrDetail.report?.stats.octave_folded ?? 0 }} /
                {{ arrDetail.report?.stats.semitone_substituted ?? 0 }}
              </div>
            </div>
          </div>

          <div v-if="arrDetail.report?.quality" class="quality-strip">
            <span>主旋律保留 {{ Math.round(arrDetail.report.quality.melody_preservation * 100) }}%</span>
            <span>节奏保真 {{ Math.round(arrDetail.report.quality.rhythmic_fidelity * 100) }}%</span>
            <span>轮廓保真 {{ Math.round(arrDetail.report.quality.pitch_contour_preservation * 100) }}%</span>
            <span>和声一致 {{ Math.round(arrDetail.report.quality.harmonic_coherence * 100) }}%</span>
            <span v-if="arrDetail.report.quality.warnings.length > 0" class="muted">
              提示: {{ arrDetail.report.quality.warnings.join(", ") }}
            </span>
          </div>

          <div v-if="profile" style="margin-top: 12px">
            <h3>{{ profile.display_name }} {{ profile.key_count }} 键分布（{{ profile.calibration.status }}）</h3>
            <LyreKeyboard :keys="profile.keys" :event-counts="eventCounts" />
          </div>

          <div v-if="profile && arrDetail.performance.events.length > 0" style="margin-top: 14px">
            <h3>Piano Roll 可视化编辑与版本保存</h3>
            <PianoRollEditor
              :keys="profile.keys"
              :events="arrDetail.performance.events"
              :saving="busy"
              @save="handleSaveEdited"
            />
          </div>

          <div style="margin-top: 14px">
            <h3>离线试听与导出</h3>
            <div class="row">
              <button type="button" :disabled="busy" @click="handlePreview">
                合成并试听当前版本
              </button>
              <button type="button" :disabled="busy" @click="handleExport('midi')">
                导出 MIDI
              </button>
              <button type="button" :disabled="busy" @click="handleExport('json')">
                导出 JSON
              </button>
              <audio v-if="previewUrl" controls :src="previewUrl" />
            </div>
            <div class="row" style="margin-top: 8px; align-items: center">
              <label class="checkbox-row">
                <input v-model="packRightsConfirmed" type="checkbox" />
                <span>我确认拥有分享授权（.lyrapack 分享包默认不含原始音频）</span>
              </label>
              <button
                type="button"
                class="btn-secondary"
                :disabled="busy"
                @click="handleExportLyrapack"
              >
                导出分享包 (.lyrapack)
              </button>
            </div>
          </div>

          <div style="margin-top: 14px">
            <h3>安全演奏控制（两步授权）</h3>
            <div class="banner-warn" style="margin-bottom: 10px">
              注意：第三方自动按键可能违反游戏条款；请勿依赖任何后台静默演奏。macOS 仅允许
              DryRun 模拟演奏；Windows 游戏内实音演奏需切回 Windows 真机并提前打开乐器界面。
            </div>
            <div class="row">
              <div class="field">
                <label for="playback-mode">输出驱动</label>
                <select id="playback-mode" v-model="playbackMode">
                  <option value="dry-run">DryRun 模拟演奏（安全，不发系统按键）</option>
                  <option value="windows" :disabled="!health?.windows_playback_available">
                    Windows 游戏键盘模拟 {{ health?.windows_playback_available ? "" : "(仅 Windows 可用)" }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label for="playback-realtime">时序模式</label>
                <select id="playback-realtime" v-model="realtime">
                  <option :value="true">真实时间 (MonotonicClock)</option>
                  <option :value="false">虚拟时钟快速验证 (VirtualClock)</option>
                </select>
              </div>
              <button type="button" :disabled="busy" @click="handlePrepare">
                1. 准备演奏
              </button>
              <button
                type="button"
                class="primary"
                :disabled="busy || !prepared"
                @click="handleStart"
              >
                2. 确认授权开始
              </button>
              <button type="button" class="danger" @click="handleEmergencyStop">
                紧急停止
              </button>
            </div>

            <p v-if="prepared" class="banner-warn" style="margin-top: 8px">
              已就绪（{{ prepared.mode }}，校准状态：{{ prepared.calibration_status }}）：{{
                prepared.risk_notice
              }}
            </p>
            <p v-if="playbackStatus" class="muted" style="margin-top: 8px">
              当前状态：<strong>{{ playbackStatus.state }}</strong>
              <span v-if="playbackStatus.last_result">
                · 已发送 {{ playbackStatus.last_result.actions_sent }}/{{
                  playbackStatus.last_result.actions_total
                }}
                动作
              </span>
            </p>
          </div>
        </section>

        <section v-else>
          <h2>欢迎使用 LyraForge</h2>
          <p class="muted">
            请从左侧导入本地 `.mid` 或音频/视频文件，转录并生成《原神》风物之诗琴改编版本。
          </p>
        </section>
      </main>
    </div>
  </div>
</template>
