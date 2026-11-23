import { computed, onBeforeUnmount, ref } from "vue";
import {
  LyraForgeApi,
  type AgentRunResult,
  type ArrangementDetailResponse,
  type ArrangementRecord,
  type ArrangePresetInfo,
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
  type ToolInstallState,
  type ToolStatus,
} from "../api";
import type { ToastItem } from "../components/ToastStack.vue";

export type StudioViewId =
  | "home"
  | "library"
  | "transcribe"
  | "studio"
  | "playback"
  | "settings";

export const VALID_VIEWS: readonly StudioViewId[] = [
  "home",
  "library",
  "transcribe",
  "studio",
  "playback",
  "settings",
];

export function isImeEnter(event: KeyboardEvent): boolean {
  return event.key === "Enter" && !event.isComposing && event.keyCode !== 229;
}

export function createLyraStore(api: LyraForgeApi) {
  const activeView = ref<StudioViewId>("home");
  if (typeof window !== "undefined") {
    const viewParam = new URLSearchParams(window.location.search).get("view") as StudioViewId | null;
    if (viewParam && VALID_VIEWS.includes(viewParam)) {
      activeView.value = viewParam;
    }
  }

  const health = ref<HealthResponse | null>(null);
  const profiles = ref<ProfileSummary[]>([]);
  const selectedProfileId = ref("genshin.windsong_lyre.v1");
  const profile = ref<ProfileDetail | null>(null);
  const transcribers = ref<TranscriberInfo[]>([]);
  const presets = ref<ArrangePresetInfo[]>([]);
  const tools = ref<ToolStatus[]>([]);
  const toolInstalls = ref<Record<string, ToolInstallState>>({});
  const toolsDir = ref("");
  const toolBusy = ref<string | null>(null);
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

  // Import state
  const uploadFile = ref<File | null>(null);
  const importTitle = ref("");
  const importArtist = ref("");
  const importTags = ref("");
  const packFile = ref<File | null>(null);
  const packRightsConfirmed = ref(false);
  const restoreFile = ref<File | null>(null);
  const restoreConfirmed = ref(false);

  // Transcription state
  const selectedEngineId = ref("builtin-mono");
  const activeJob = ref<TranscriptionJob | null>(null);

  // Arrangement state
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
  const llmApiKeyConfigured = ref(false);

  // Agent
  const agentPrompt = ref("");
  const agentAllowNetwork = ref(false);
  const agentResult = ref<AgentRunResult | null>(null);

  // UI feedback
  const initializing = ref(true);
  const busy = ref(false);
  const statusMessage = ref("");
  const errorMessage = ref("");
  const toasts = ref<ToastItem[]>([]);
  let toastSeq = 1;
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
  const selectedSong = computed(
    () => songs.value.find((s) => s.id === selectedSongId.value) ?? null,
  );
  const recentSongs = computed(() => songs.value.slice(0, 6));

  const eventCounts = computed<Record<string, number>>(() => {
    const counts: Record<string, number> = {};
    for (const ev of arrDetail.value?.performance.events ?? []) {
      counts[ev.key_id] = (counts[ev.key_id] ?? 0) + 1;
    }
    return counts;
  });

  function pushToast(kind: ToastItem["kind"], text: string): void {
    const id = toastSeq++;
    toasts.value = [...toasts.value.slice(-3), { id, kind, text }];
    if (typeof window !== "undefined") {
      window.setTimeout(() => dismissToast(id), 4500);
    }
  }

  function dismissToast(id: number): void {
    toasts.value = toasts.value.filter((t) => t.id !== id);
  }

  function reportOk(msg: string): void {
    statusMessage.value = msg;
    errorMessage.value = "";
    pushToast("ok", msg);
  }

  function reportError(msg: string): void {
    errorMessage.value = msg;
    pushToast("error", msg);
  }

  function setView(view: StudioViewId): void {
    activeView.value = view;
    if (typeof window !== "undefined" && window.location.protocol !== "about:") {
      try {
        const url = new URL(window.location.href);
        url.searchParams.set("view", view);
        window.history.replaceState(null, "", url.pathname + url.search + url.hash);
      } catch {
        // ignore URL manipulation issues inside test/sandboxed webviews
      }
    }
  }

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
    const res = opts
      ? await api.listSongs(searchQuery.value, opts)
      : await api.listSongs(searchQuery.value);
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
      reportError((err as Error).message);
    }
  }

  async function importDroppedOrPickedFile(
    file: File,
    meta?: { title?: string; artist?: string; tags?: string },
  ): Promise<void> {
    busy.value = true;
    errorMessage.value = "";
    try {
      const lower = file.name.toLowerCase();
      if (lower.endsWith(".lyrapack") || lower.endsWith(".zip")) {
        const res = await api.importLyrapack(file);
        await refreshSongs();
        await selectSong(res.song.id);
        await selectArrangement(res.arrangement.id);
        reportOk(`已导入分享包：${res.song.title}`);
        setView("studio");
        return;
      }
      const res = await api.importMedia(
        file,
        meta?.title ?? importTitle.value,
        meta?.artist ?? importArtist.value,
        meta?.tags ?? importTags.value,
      );
      importTitle.value = "";
      importArtist.value = "";
      importTags.value = "";
      uploadFile.value = null;
      await refreshSongs();
      await selectSong(res.song.id);
      reportOk(`已导入曲目：${res.song.title}`);
      const isMidi = lower.endsWith(".mid") || lower.endsWith(".midi");
      setView(isMidi ? "studio" : "transcribe");
    } catch (err) {
      reportError((err as Error).message);
    } finally {
      busy.value = false;
    }
  }

  async function handleImport(): Promise<void> {
    if (!uploadFile.value) {
      reportError("请先选择一个 .mid/.midi 或音视频文件");
      return;
    }
    await importDroppedOrPickedFile(uploadFile.value);
  }

  async function handleStartTranscribe(): Promise<void> {
    if (!selectedSongId.value) return;
    busy.value = true;
    errorMessage.value = "";
    try {
      const { job } = await api.submitTranscribeJob(selectedSongId.value, selectedEngineId.value);
      activeJob.value = job;
      reportOk(`已提交音频转谱任务 (${job.engine_id})`);
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
            reportOk(`音频转谱完成，共保留 ${res.job.transcription?.note_count ?? 0} 个音符`);
          } else if (res.job.status === "cancelled" || res.job.status === "failed") {
            stopJobPolling();
            if (res.job.error) {
              reportError(res.job.error.message);
            } else {
              pushToast("info", "音频转谱已取消");
            }
          }
        } catch {
          stopJobPolling();
        }
      }, 150);
    } catch (err) {
      reportError((err as Error).message);
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
      pushToast("info", "已请求取消音频转谱");
      statusMessage.value = "已请求取消音频转谱";
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  function parseTranspose(): number | null | "invalid" {
    const clean = transposeInput.value.trim();
    if (clean === "auto" || clean === "") return null;
    const val = Number(clean);
    return Number.isInteger(val) ? val : "invalid";
  }

  async function handleArrange(): Promise<void> {
    if (!selectedSongId.value) return;
    const parsedTranspose = parseTranspose();
    if (parsedTranspose === "invalid") {
      reportError("移调请输入 auto 或整数半音");
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
      reportOk(`已生成 ${res.arrangement.style} 版本（${res.arrangement.event_count} 个音符）`);
    } catch (err) {
      reportError((err as Error).message);
    } finally {
      busy.value = false;
    }
  }

  async function handleArrangeAB(): Promise<void> {
    if (!selectedSongId.value) return;
    const parsedTranspose = parseTranspose();
    if (parsedTranspose === "invalid") {
      reportError("移调请输入 auto 或整数半音");
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
      reportOk(`A/B 对比完成：${res.comparison.summary}`);
    } catch (err) {
      reportError((err as Error).message);
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
      reportOk(`已保存新版本：${res.arrangement.label ?? "手动编辑"}`);
    } catch (err) {
      reportError((err as Error).message);
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
      reportOk(nextFav ? "已收藏该改编版本" : "已取消收藏");
    } catch (err) {
      reportError((err as Error).message);
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
      reportError((err as Error).message);
    }
  }

  async function handlePreview(): Promise<void> {
    if (!selectedArrId.value) return;
    busy.value = true;
    errorMessage.value = "";
    clearPreviewUrl();
    try {
      previewUrl.value = await api.fetchPreviewAudioUrl(selectedArrId.value);
      reportOk("已合成离线试听 WAV，请点击播放器试听");
    } catch (err) {
      reportError((err as Error).message);
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
      reportOk(`已导出 ${fmt.toUpperCase()} 文件`);
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  async function handleExportLyrapack(): Promise<void> {
    if (!selectedArrId.value) return;
    if (!packRightsConfirmed.value) {
      reportError("请先勾选版权授权确认（分享包默认不包含任何原始音频）");
      return;
    }
    errorMessage.value = "";
    try {
      const blob = await api.exportLyrapack(selectedArrId.value, true);
      triggerBlobDownload(blob, `${selectedArrId.value}.lyrapack`);
      reportOk("已导出 .lyrapack 分享包（不含原始音频）");
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  async function handleImportLyrapack(): Promise<void> {
    if (!packFile.value) {
      reportError("请先选择一个 .lyrapack 分享包文件");
      return;
    }
    busy.value = true;
    errorMessage.value = "";
    try {
      const res = await api.importLyrapack(packFile.value);
      packFile.value = null;
      await refreshSongs();
      await selectSong(res.song.id);
      await selectArrangement(res.arrangement.id);
      reportOk(`已导入分享包曲目：${res.song.title}`);
    } catch (err) {
      reportError((err as Error).message);
    } finally {
      busy.value = false;
    }
  }

  async function handleBackupZip(): Promise<void> {
    errorMessage.value = "";
    try {
      const blob = await api.downloadBackupZip();
      triggerBlobDownload(blob, "lyraforge-backup.zip");
      reportOk("已下载本地曲库完整备份 ZIP");
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  async function handleRestoreBackupZip(): Promise<void> {
    if (!restoreFile.value) {
      reportError("请先选择一个本地曲库备份 ZIP 文件");
      return;
    }
    if (!restoreConfirmed.value) {
      reportError("恢复备份将覆盖当前曲库数据（密钥凭据保持独立），请先勾选确认");
      return;
    }
    busy.value = true;
    errorMessage.value = "";
    try {
      const res = await api.restoreBackupZip(restoreFile.value);
      restoreFile.value = null;
      restoreConfirmed.value = false;
      selectedSongId.value = null;
      await refreshSongs();
      reportOk(`已安全恢复曲库备份，共载入 ${res.restored.song_count} 首曲目`);
    } catch (err) {
      reportError((err as Error).message);
    } finally {
      busy.value = false;
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
        const updated = await api.saveSetting("llm_api_key", llmApiKeySetting.value.trim());
        llmApiKeyConfigured.value = Boolean(updated.settings.llm_api_key_configured);
        llmApiKeySetting.value = "";
      }
      reportOk("设置已保存至本地曲库（敏感密钥已入系统凭据库）");
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  async function handleRunAgent(overrideAllowNetwork?: boolean): Promise<void> {
    const promptText = agentPrompt.value.trim();
    if (!promptText) {
      reportError("请输入自然语言指令（例如歌名、乐器与编曲偏好）");
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
        reportOk(res.message);
      } else if (res.requires_confirmation) {
        statusMessage.value = res.confirmation_prompt ?? res.message;
        pushToast("info", statusMessage.value);
      } else {
        statusMessage.value = res.message;
        pushToast("info", res.message);
      }
    } catch (err) {
      reportError((err as Error).message);
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
      reportOk("已准备就绪，请核对风险提示后显式确认开始");
    } catch (err) {
      reportError((err as Error).message);
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
      reportOk("演奏已启动");
      stopPolling();
      pollTimer = window.setInterval(async () => {
        try {
          playbackStatus.value = await api.playbackStatus();
          if (
            playbackStatus.value.state !== "running" &&
            playbackStatus.value.state !== "paused"
          ) {
            stopPolling();
            reportOk(`演奏已结束（状态：${playbackStatus.value.state}）`);
          }
        } catch {
          stopPolling();
        }
      }, 200);
    } catch (err) {
      reportError((err as Error).message);
    } finally {
      busy.value = false;
    }
  }

  async function handlePause(): Promise<void> {
    errorMessage.value = "";
    try {
      playbackStatus.value = await api.pausePlayback();
      reportOk("演奏已暂停并释放全部按键");
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  async function handleResume(): Promise<void> {
    errorMessage.value = "";
    try {
      playbackStatus.value = await api.resumePlayback();
      reportOk("已恢复演奏");
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  async function handleEmergencyStop(): Promise<void> {
    errorMessage.value = "";
    try {
      playbackStatus.value = await api.stopPlayback();
      prepared.value = null;
      stopPolling();
      reportOk("已紧急停止并释放所有按键");
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  async function refreshPresets(): Promise<void> {
    presets.value = (await api.listPresets()).presets;
  }

  function applyPreset(presetId: string): void {
    const preset = presets.value.find((item) => item.id === presetId);
    if (!preset) return;
    style.value = preset.style;
    transposeInput.value = preset.transpose === null ? "auto" : String(preset.transpose);
    arpeggiateMs.value = preset.arpeggiate_ms;
    speed.value = preset.speed;
    pushToast("ok", `已应用预设：${preset.name}`);
  }

  async function refreshTools(): Promise<void> {
    const res = await api.listTools();
    tools.value = res.tools;
    toolsDir.value = res.tools_dir;
    const map: Record<string, ToolInstallState> = {};
    for (const item of res.installs) {
      map[item.tool_id] = item;
    }
    toolInstalls.value = map;
  }

  async function handleInstallTool(toolId: string): Promise<void> {
    if (toolBusy.value) return;
    toolBusy.value = toolId;
    try {
      await api.installTool(toolId);
      pushToast("info", `正在下载并安装 ${toolId}，请保持网络连接…`);
      const deadline = Date.now() + 30 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        await refreshTools();
        const state = toolInstalls.value[toolId];
        if (state && state.status !== "running") {
          if (state.status === "installed") {
            pushToast("ok", `${toolId} 安装完成，可直接选用该引擎`);
          } else {
            pushToast("error", state.error ?? `${toolId} 安装失败`);
          }
          break;
        }
      }
      transcribers.value = (await api.listTranscribers()).transcribers;
    } catch (err) {
      reportError((err as Error).message);
    } finally {
      toolBusy.value = null;
    }
  }

  async function initialize(): Promise<void> {
    initializing.value = true;
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
      await refreshPresets();
      await refreshTools();
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
      llmApiKeyConfigured.value = Boolean(settings.llm_api_key_configured);
      await refreshSongs();
      if (typeof window !== "undefined") {
        const songParam = new URLSearchParams(window.location.search).get("song");
        if (songParam && songs.value.some((s) => s.id === songParam)) {
          await selectSong(songParam);
        }
      }
      playbackStatus.value = await api.playbackStatus();
    } catch (err) {
      reportError(`初始化失败：${(err as Error).message}`);
    } finally {
      initializing.value = false;
    }
  }

  onBeforeUnmount(() => {
    stopPolling();
    stopJobPolling();
    clearPreviewUrl();
  });

  return {
    activeView,
    setView,
    health,
    profiles,
    selectedProfileId,
    profile,
    transcribers,
    songs,
    recentSongs,
    searchQuery,
    filterTag,
    filterFavoritesOnly,
    selectedSongId,
    selectedSong,
    songSources,
    songTranscriptions,
    arrangements,
    selectedArrId,
    arrDetail,
    comparisonResult,
    uploadFile,
    importTitle,
    importArtist,
    importTags,
    packFile,
    packRightsConfirmed,
    restoreFile,
    restoreConfirmed,
    selectedEngineId,
    activeJob,
    style,
    speed,
    transposeInput,
    arpeggiateMs,
    previewUrl,
    playbackMode,
    realtime,
    prepared,
    playbackStatus,
    allowedTitlesSetting,
    llmEnabledSetting,
    llmBaseUrlSetting,
    llmModelSetting,
    llmApiKeySetting,
    llmApiKeyConfigured,
    agentPrompt,
    agentAllowNetwork,
    agentResult,
    initializing,
    busy,
    statusMessage,
    errorMessage,
    toasts,
    dismissToast,
    pushToast,
    hasMidiSource,
    hasAudioSource,
    canArrange,
    selectedEngineInfo,
    eventCounts,
    refreshSongs,
    tools,
    toolInstalls,
    toolsDir,
    toolBusy,
    refreshTools,
    handleInstallTool,
    presets,
    refreshPresets,
    applyPreset,
    selectSong,
    selectArrangement,
    handleProfileChange,
    importDroppedOrPickedFile,
    handleImport,
    handleStartTranscribe,
    handleCancelTranscribe,
    handleArrange,
    handleArrangeAB,
    handleSaveEdited,
    handleToggleFavorite,
    handleVote,
    handlePreview,
    handleExport,
    handleExportLyrapack,
    handleImportLyrapack,
    handleBackupZip,
    handleRestoreBackupZip,
    handleSaveSettings,
    handleRunAgent,
    handlePrepare,
    handleStart,
    handlePause,
    handleResume,
    handleEmergencyStop,
    initialize,
  };
}

export type LyraStore = ReturnType<typeof createLyraStore>;
