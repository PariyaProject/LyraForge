import { computed, onBeforeUnmount, ref } from "vue";
import {
  LyraForgeApi,
  type AgentRunResult,
  type ArrangementDetailResponse,
  type ArrangementRecord,
  type ArrangePresetInfo,
  type ArrangerStrategyInfo,
  type ComparisonResult,
  type GpuStatus,
  type HealthResponse,
  type HotkeyActionInfo,
  type PerformanceEventItem,
  type PipelineInfo,
  type PlaybackPrepareResponse,
  type PlaybackStatusResponse,
  type ProfileDetail,
  type ProfileSummary,
  type QueueState,
  type SongSummary,
  type SongTrackInfo,
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

export function arrangementTitle(arr: ArrangementRecord): string {
  const custom = (arr.label ?? "").trim();
  if (custom) return custom;
  const styles: Record<string, string> = {
    melody: "主旋律",
    balanced: "均衡",
    rich: "丰满",
  };
  const style = styles[arr.style] ?? arr.style;
  const transpose =
    arr.transpose === 0 ? "原调" : `移调${arr.transpose > 0 ? "+" : ""}${arr.transpose}`;
  const stratSuffix = arr.arranger_strategy === "vocal_lead" ? " · 主旋律增强" : "";
  return `${style} · ${transpose} · ${arr.speed}x${stratSuffix}`;
}

const DEFAULT_PIPELINES: PipelineInfo[] = [
  {
    id: "direct",
    display_name: "经典直转（原流程）",
    description: "直接把音频送入所选转谱引擎识别，速度快，与原有行为完全一致。",
    recommended_for: "纯钢琴 / 独奏 / BGM / 现成简单混音",
    stages: ["音频提取", "单引擎转谱", "常规清理入库"],
    required_tools: [],
    available: true,
    missing_tools: [],
    default_engine_id: "builtin-mono",
    default_vocal_engine_id: null,
    default_accomp_engine_id: null,
    default_arranger_strategy: "classic",
    supports_engine_override: true,
  },
];

const DEFAULT_ARRANGER_STRATEGIES: ArrangerStrategyInfo[] = [
  {
    id: "classic",
    display_name: "经典基线（原算法）",
    description: "保留原始全局均衡移调与高音优先和弦裁剪逻辑。",
    recommended_for: "纯器乐 / 独奏 / 精选 MIDI",
  },
  {
    id: "vocal_lead",
    display_name: "主旋律优先 · 音乐学增强",
    description: "主旋律加权移调、伴奏低于主旋律、回避撞音并自动在人声段让路。",
    recommended_for: "人声流行歌 / 分轨转录 / 复杂混音",
  },
];

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
  const pipelines = ref<PipelineInfo[]>([...DEFAULT_PIPELINES]);
  const arrangerStrategies = ref<ArrangerStrategyInfo[]>([...DEFAULT_ARRANGER_STRATEGIES]);
  const presets = ref<ArrangePresetInfo[]>([]);
  const hotkeyActions = ref<HotkeyActionInfo[]>([]);
  const hotkeyBindings = ref<Record<string, string>>({});
  const hotkeyErrors = ref<Record<string, string>>({});
  const hotkeySupported = ref(true);
  const gpuStatus = ref<GpuStatus | null>(null);
  const tools = ref<ToolStatus[]>([]);
  const toolInstalls = ref<Record<string, ToolInstallState>>({});
  const toolsDir = ref("");
  const toolBusy = ref<string | null>(null);
  const songs = ref<SongSummary[]>([]);
  const allSongs = ref<SongSummary[]>([]);
  const searchQuery = ref("");
  const filterTag = ref("");
  const filterFavoritesOnly = ref(false);
  const selectedSongId = ref<string | null>(null);
  const selectedSongSnapshot = ref<SongSummary | null>(null);
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
  const selectedPipelineId = ref("direct");
  const selectedEngineId = ref("builtin-mono");
  const selectedVocalEngineId = ref("auto");
  const selectedAccompEngineId = ref("auto");
  const transcriptionJobs = ref<TranscriptionJob[]>([]);

  // Arrangement state
  const style = ref<"melody" | "balanced" | "rich">("balanced");
  const speed = ref(1.0);
  const transposeInput = ref("auto");
  const arpeggiateMs = ref(0);
  const selectedArrangerStrategy = ref("classic");
  const selectedTranscriptionId = ref<string | null>(null);
  const songTracks = ref<SongTrackInfo[]>([]);
  const selectedTrackIndices = ref<number[] | null>(null);
  const selectedMelodyTrack = ref<number | null>(null);
  const detectedMelodyTrack = ref<number | null>(null);

  // Preview audio
  const previewUrl = ref<string | null>(null);
  const previewCurrentMs = ref(0);
  const previewDurationMs = ref(0);
  const previewPlaying = ref(false);
  const previewSeekTargetMs = ref<number | null>(null);

  // Playback
  const playbackMode = ref<"dry-run" | "windows">("dry-run");
  const realtime = ref(true);
  const prepared = ref<PlaybackPrepareResponse | null>(null);
  const playbackStatus = ref<PlaybackStatusResponse | null>(null);
  const queue = ref<QueueState>({ items: [], index: 0, mode: "dry-run", realtime: false });

  // Settings
  const allowedTitlesSetting = ref("Genshin Impact, 原神");
  const allowedProcessesSetting = ref("GenshinImpact.exe, YuanShen.exe");
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
  let jobPollInFlight = false;
  let jobPollFailures = 0;
  let selectSongSeq = 0;
  let selectArrSeq = 0;

  function isJobRunning(job: TranscriptionJob): boolean {
    return job.status === "queued" || job.status === "running";
  }

  const hasMidiSource = computed(() => songSources.value.some((s) => s.kind === "midi"));
  const hasAudioSource = computed(() => songSources.value.some((s) => s.kind === "audio"));
  const canArrange = computed(
    () => hasMidiSource.value || songTranscriptions.value.some((t) => t.status === "completed"),
  );
  const selectedEngineInfo = computed(
    () => transcribers.value.find((t) => t.id === selectedEngineId.value) ?? null,
  );
  const selectedPipelineInfo = computed(
    () => pipelines.value.find((p) => p.id === selectedPipelineId.value) ?? pipelines.value[0] ?? null,
  );
  const availableTranscribers = computed(() =>
    transcribers.value.filter((t) => t.available),
  );
  const selectedSong = computed(() => {
    const id = selectedSongId.value;
    if (!id) return null;
    return (
      allSongs.value.find((s) => s.id === id) ??
      songs.value.find((s) => s.id === id) ??
      (selectedSongSnapshot.value?.id === id ? selectedSongSnapshot.value : null)
    );
  });
  const recentSongs = computed(() =>
    (allSongs.value.length > 0 ? allSongs.value : songs.value).slice(0, 6),
  );

  function songTitleById(songId: string): string {
    return (
      allSongs.value.find((s) => s.id === songId)?.title ??
      songs.value.find((s) => s.id === songId)?.title ??
      (selectedSongSnapshot.value?.id === songId ? selectedSongSnapshot.value.title : undefined) ??
      songId
    );
  }

  const runningTranscriptionJobs = computed(() => transcriptionJobs.value.filter(isJobRunning));

  const currentSongJob = computed<TranscriptionJob | null>(() => {
    const id = selectedSongId.value;
    if (!id) return null;
    const forSong = transcriptionJobs.value.filter((j) => j.song_id === id);
    return forSong.find(isJobRunning) ?? forSong[0] ?? null;
  });

  const activeJob = computed<TranscriptionJob | null>(() => currentSongJob.value);

  const otherSongJobs = computed<TranscriptionJob[]>(() => {
    const curId = selectedSongId.value;
    const running = transcriptionJobs.value.filter((j) => j.song_id !== curId && isJobRunning(j));
    const seenSongs = new Set<string>(running.map((j) => j.song_id));
    const recentTerminal: TranscriptionJob[] = [];
    for (const job of transcriptionJobs.value) {
      if (job.song_id === curId || isJobRunning(job) || seenSongs.has(job.song_id)) {
        continue;
      }
      seenSongs.add(job.song_id);
      recentTerminal.push(job);
    }
    return [...running, ...recentTerminal].slice(0, 6);
  });

  function isSongTranscribing(songId: string): boolean {
    return runningTranscriptionJobs.value.some((j) => j.song_id === songId);
  }

  const transcribeSongId = computed(() => selectedSongId.value);
  const transcribeSongTitle = computed(() => selectedSong.value?.title ?? "");
  const transcribeSources = songSources;
  const transcribeTranscriptions = songTranscriptions;
  const transcribeHasAudio = hasAudioSource;

  const eventCounts = computed<Record<string, number>>(() => {
    const counts: Record<string, number> = {};
    for (const ev of arrDetail.value?.performance.events ?? []) {
      counts[ev.key_id] = (counts[ev.key_id] ?? 0) + 1;
    }
    return counts;
  });

  const soundingKeyIds = computed<string[]>(() => {
    if (!previewPlaying.value && previewCurrentMs.value <= 0) return [];
    const pos = previewCurrentMs.value;
    const active = new Set<string>();
    for (const ev of arrDetail.value?.performance.events ?? []) {
      const span = Math.max(140, ev.hold_ms);
      if (ev.at_ms <= pos && pos <= ev.at_ms + span) {
        active.add(ev.key_id);
      }
    }
    return [...active];
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
    previewCurrentMs.value = 0;
    previewDurationMs.value = 0;
    previewPlaying.value = false;
    previewSeekTargetMs.value = null;
  }

  function updatePreviewPlayback(currentMs: number, durationMs: number, playing: boolean): void {
    previewCurrentMs.value = Math.max(0, Math.round(currentMs));
    if (Number.isFinite(durationMs) && durationMs > 0) {
      previewDurationMs.value = Math.round(durationMs);
    }
    previewPlaying.value = playing;
  }

  function requestPreviewSeek(ms: number): void {
    previewSeekTargetMs.value = Math.max(0, Math.round(ms));
    previewCurrentMs.value = Math.max(0, Math.round(ms));
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
    jobPollInFlight = false;
    jobPollFailures = 0;
  }

  function upsertTranscriptionJob(job: TranscriptionJob): void {
    const idx = transcriptionJobs.value.findIndex((item) => item.id === job.id);
    if (idx >= 0) {
      const next = [...transcriptionJobs.value];
      next[idx] = job;
      transcriptionJobs.value = next;
      return;
    }
    transcriptionJobs.value = [job, ...transcriptionJobs.value].slice(0, 20);
  }

  function mergeSongSummary(
    rawSong: SongSummary,
    arrangementCount: number,
    cached?: SongSummary | null,
  ): SongSummary {
    const partial = rawSong as Partial<SongSummary>;
    return {
      id: rawSong.id,
      title: rawSong.title,
      artist: partial.artist ?? cached?.artist ?? "",
      tags: partial.tags ?? cached?.tags ?? [],
      arrangement_count: partial.arrangement_count ?? arrangementCount,
      created_at: partial.created_at ?? cached?.created_at ?? "",
      updated_at: partial.updated_at ?? cached?.updated_at ?? "",
    };
  }

  async function refreshSongTracks(songId: string, transcriptionId?: string | null): Promise<void> {
    if (!songId) {
      songTracks.value = [];
      selectedTrackIndices.value = null;
      selectedMelodyTrack.value = null;
      detectedMelodyTrack.value = null;
      return;
    }
    if (typeof api.getSongTracks === "function") {
      try {
        const res = await api.getSongTracks(songId, transcriptionId);
        if (selectedSongId.value !== songId) return;
        songTracks.value = res.tracks ?? [];
        detectedMelodyTrack.value = res.detected_melody_track ?? null;
        selectedTrackIndices.value = songTracks.value
          .filter((t) => !t.is_percussion)
          .map((t) => t.index);
        selectedMelodyTrack.value = null;
        return;
      } catch {
        // fallback cleanly below when no MIDI/transcription exists yet
      }
    }
    const tr =
      (transcriptionId ? songTranscriptions.value.find((t) => t.id === transcriptionId) : null) ??
      songTranscriptions.value[0] ??
      null;
    const trTracks = tr?.tracks ?? [];
    songTracks.value = trTracks;
    detectedMelodyTrack.value = trTracks[0]?.index ?? null;
    selectedTrackIndices.value = trTracks.filter((t) => !t.is_percussion).map((t) => t.index);
    selectedMelodyTrack.value = null;
  }

  function applySongDetail(
    songId: string,
    detail: {
      song: SongSummary;
      sources?: SourceRecord[];
      transcriptions?: TranscriptionRecord[];
      arrangements: ArrangementRecord[];
    },
  ): void {
    const cached =
      allSongs.value.find((s) => s.id === songId) ??
      songs.value.find((s) => s.id === songId) ??
      null;
    const resolvedSong = mergeSongSummary(detail.song, detail.arrangements.length, cached);
    selectedSongSnapshot.value = resolvedSong;
    const idx = allSongs.value.findIndex((s) => s.id === songId);
    if (idx < 0) {
      allSongs.value = [resolvedSong, ...allSongs.value];
    } else {
      const next = [...allSongs.value];
      next[idx] = resolvedSong;
      allSongs.value = next;
    }
    songSources.value = detail.sources ?? [];
    songTranscriptions.value = detail.transcriptions ?? [];
    arrangements.value = detail.arrangements;
  }

  async function reloadSelectedSongDetail(expectedSongId?: string): Promise<void> {
    const targetId = expectedSongId ?? selectedSongId.value;
    if (!targetId || selectedSongId.value !== targetId) return;
    const seq = selectSongSeq;
    const detail = await api.getSong(targetId);
    if (seq !== selectSongSeq || selectedSongId.value !== targetId) return;
    applySongDetail(targetId, detail);
    if (
      !selectedTranscriptionId.value ||
      !songTranscriptions.value.some((t) => t.id === selectedTranscriptionId.value)
    ) {
      selectedTranscriptionId.value = songTranscriptions.value[0]?.id ?? null;
    }
    await refreshSongTracks(targetId, selectedTranscriptionId.value);
  }

  function ensureJobPolling(): void {
    if (typeof window === "undefined") return;
    if (runningTranscriptionJobs.value.length === 0) {
      stopJobPolling();
      return;
    }
    if (jobPollTimer !== null) return;
    jobPollTimer = window.setInterval(async () => {
      if (jobPollInFlight) return;
      const active = runningTranscriptionJobs.value;
      if (active.length === 0) {
        stopJobPolling();
        return;
      }
      jobPollInFlight = true;
      const prevStatusById = new Map(active.map((j) => [j.id, j.status]));
      try {
        const results = await Promise.allSettled(active.map((j) => api.getJob(j.id)));
        let anySucceeded = false;
        for (const result of results) {
          if (result.status !== "fulfilled") continue;
          anySucceeded = true;
          const nextJob = result.value.job;
          upsertTranscriptionJob(nextJob);
          const prevStatus = prevStatusById.get(nextJob.id);
          if (prevStatus !== "queued" && prevStatus !== "running") continue;
          const title = songTitleById(nextJob.song_id);
          if (nextJob.status === "completed") {
            await reloadSelectedSongDetail(nextJob.song_id);
            reportOk(`《${title}》音频转谱完成，共保留 ${nextJob.transcription?.note_count ?? 0} 个音符`);
          } else if (nextJob.status === "cancelled" || nextJob.status === "failed") {
            await reloadSelectedSongDetail(nextJob.song_id);
            if (nextJob.error) {
              reportError(`《${title}》转谱失败：${nextJob.error.message}`);
            } else {
              pushToast("info", `《${title}》音频转谱已取消`);
            }
          }
        }
        if (anySucceeded) {
          jobPollFailures = 0;
        } else {
          jobPollFailures += 1;
          if (jobPollFailures >= 3) {
            stopJobPolling();
          }
        }
        if (runningTranscriptionJobs.value.length === 0) {
          stopJobPolling();
        }
      } finally {
        jobPollInFlight = false;
      }
    }, 400);
  }

  async function refreshJobs(): Promise<void> {
    if (typeof api.listJobs !== "function") return;
    try {
      const res = await api.listJobs();
      for (const job of [...res.jobs].reverse()) {
        upsertTranscriptionJob(job);
      }
      if (runningTranscriptionJobs.value.length > 0) {
        ensureJobPolling();
      }
    } catch {
      // ignore transient job listing failures on startup
    }
  }

  async function refreshSongs(options?: { alsoRefreshAll?: boolean }): Promise<void> {
    const hasFilter = Boolean(
      searchQuery.value.trim() || filterTag.value.trim() || filterFavoritesOnly.value,
    );
    const opts =
      filterTag.value.trim() || filterFavoritesOnly.value
        ? { tag: filterTag.value.trim(), favoritesOnly: filterFavoritesOnly.value }
        : undefined;
    const res = opts
      ? await api.listSongs(searchQuery.value, opts)
      : await api.listSongs(searchQuery.value);
    songs.value = res.songs;
    if (!hasFilter) {
      allSongs.value = res.songs;
    } else if (options?.alsoRefreshAll || allSongs.value.length === 0) {
      const fullRes = await api.listSongs("");
      allSongs.value = fullRes.songs;
    }
    if (!selectedSongId.value && songs.value.length > 0) {
      await selectSong(songs.value[0].id);
    }
  }

  async function selectSong(songId: string): Promise<void> {
    if (!songId) return;
    const seq = ++selectSongSeq;
    const arrSeq = ++selectArrSeq;
    selectedSongId.value = songId;
    prepared.value = null;
    comparisonResult.value = null;
    clearPreviewUrl();
    const cached =
      allSongs.value.find((s) => s.id === songId) ??
      songs.value.find((s) => s.id === songId) ??
      null;
    if (cached) {
      selectedSongSnapshot.value = cached;
    }
    const detail = await api.getSong(songId);
    if (seq !== selectSongSeq || selectedSongId.value !== songId) return;
    applySongDetail(songId, detail);
    selectedTranscriptionId.value = detail.transcriptions?.[0]?.id ?? null;
    await refreshSongTracks(songId, selectedTranscriptionId.value);
    if (detail.arrangements.length > 0) {
      await selectArrangement(detail.arrangements[0].id, arrSeq);
    } else if (arrSeq === selectArrSeq) {
      selectedArrId.value = "";
      arrDetail.value = null;
    }
  }

  async function selectTranscriptionForStudio(transcriptionId: string): Promise<void> {
    selectedTranscriptionId.value = transcriptionId || null;
    if (selectedSongId.value) {
      await refreshSongTracks(selectedSongId.value, selectedTranscriptionId.value);
    }
  }

  async function openTranscriptionInStudio(
    songId: string,
    transcriptionId?: string | null,
  ): Promise<void> {
    if (songId && songId !== selectedSongId.value) {
      await selectSong(songId);
    }
    if (transcriptionId) {
      selectedTranscriptionId.value = transcriptionId;
      const tr = songTranscriptions.value.find((t) => t.id === transcriptionId);
      if (tr?.pipeline_id?.startsWith("vocal_split")) {
        selectedArrangerStrategy.value = "vocal_lead";
      }
      await refreshSongTracks(selectedSongId.value ?? songId, transcriptionId);
    }
    setView("studio");
  }

  function toggleTrackIncluded(trackIndex: number): void {
    const pitched = songTracks.value.filter((t) => !t.is_percussion).map((t) => t.index);
    const current = new Set(selectedTrackIndices.value ?? pitched);
    if (current.has(trackIndex)) {
      current.delete(trackIndex);
    } else {
      current.add(trackIndex);
    }
    selectedTrackIndices.value = pitched.filter((idx) => current.has(idx));
  }

  const selectTranscribeSong = selectSong;

  async function selectArrangement(arrangementId: string, expectedArrSeq?: number): Promise<void> {
    const arrSeq = expectedArrSeq ?? ++selectArrSeq;
    selectedArrId.value = arrangementId;
    prepared.value = null;
    clearPreviewUrl();
    if (!arrangementId) {
      arrDetail.value = null;
      return;
    }
    const detail = await api.getArrangement(arrangementId);
    if (arrSeq !== selectArrSeq || selectedArrId.value !== arrangementId) return;
    arrDetail.value = detail;
    const ownerSongId = detail.arrangement.song_id;
    if (ownerSongId && ownerSongId !== selectedSongId.value) {
      const songSeq = ++selectSongSeq;
      selectedSongId.value = ownerSongId;
      comparisonResult.value = null;
      const songDetail = await api.getSong(ownerSongId);
      if (songSeq === selectSongSeq && selectedSongId.value === ownerSongId) {
        applySongDetail(ownerSongId, songDetail);
      }
    }
    if (detail.arrangement.profile_id && profile.value?.id !== detail.arrangement.profile_id) {
      selectedProfileId.value = detail.arrangement.profile_id;
      profile.value = await api.getProfile(detail.arrangement.profile_id);
    }
  }

  async function openSongInView(songId: string, view: StudioViewId): Promise<void> {
    if (songId && songId !== selectedSongId.value) {
      await selectSong(songId);
    }
    setView(view);
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
        await refreshSongs({ alsoRefreshAll: true });
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
      await refreshSongs({ alsoRefreshAll: true });
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
    const songId = selectedSongId.value;
    if (!songId) return;
    if (!hasAudioSource.value) {
      reportError("当前曲目没有音频/视频来源，无法转谱；请先导入音频或视频");
      return;
    }
    if (currentSongJob.value && isJobRunning(currentSongJob.value)) {
      return;
    }
    busy.value = true;
    errorMessage.value = "";
    try {
      const pipelineId = selectedPipelineId.value || "direct";
      const { job } =
        pipelineId === "direct"
          ? await api.submitTranscribeJob(songId, selectedEngineId.value)
          : await api.submitTranscribeJob(songId, selectedEngineId.value, {
              pipelineId,
              vocalEngineId: selectedVocalEngineId.value,
              accompEngineId: selectedAccompEngineId.value,
            });
      upsertTranscriptionJob(job);
      reportOk(`已提交音频转谱任务：${songTitleById(songId)} (${job.engine_id})`);
      ensureJobPolling();
    } catch (err) {
      reportError((err as Error).message);
    } finally {
      busy.value = false;
    }
  }

  async function handleCancelTranscribe(jobId?: unknown): Promise<void> {
    const targetId = typeof jobId === "string" ? jobId : currentSongJob.value?.id;
    if (!targetId) return;
    try {
      const res = await api.cancelJob(targetId);
      upsertTranscriptionJob(res.job);
      if (runningTranscriptionJobs.value.length === 0) {
        stopJobPolling();
      }
      const msg = `已请求取消音频转谱：${songTitleById(res.job.song_id)}`;
      pushToast("info", msg);
      statusMessage.value = msg;
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

  function resolveIncludeTracksPayload(): number[] | null {
    const pitched = songTracks.value.filter((t) => !t.is_percussion).map((t) => t.index);
    if (pitched.length === 0 || selectedTrackIndices.value === null) return null;
    if (selectedTrackIndices.value.length === 0) return [];
    if (selectedTrackIndices.value.length === pitched.length) return null;
    return [...selectedTrackIndices.value];
  }

  async function handleArrange(): Promise<void> {
    if (!selectedSongId.value) return;
    const parsedTranspose = parseTranspose();
    if (parsedTranspose === "invalid") {
      reportError("移调请输入 auto 或整数半音");
      return;
    }
    const includeTracks = resolveIncludeTracksPayload();
    if (includeTracks !== null && includeTracks.length === 0) {
      reportError("请至少勾选一条音轨参与编曲");
      return;
    }
    busy.value = true;
    errorMessage.value = "";
    try {
      const activeTr = !hasMidiSource.value
        ? songTranscriptions.value.find((t) => t.id === selectedTranscriptionId.value) ??
          songTranscriptions.value[0] ??
          null
        : null;
      const pipePrefix =
        activeTr?.pipeline_id && activeTr.pipeline_id !== "direct"
          ? `${activeTr.pipeline_id} · `
          : "";
      const strategyLabel =
        selectedArrangerStrategy.value === "vocal_lead" ? "主旋律增强" : "经典基线";
      const customLabel =
        selectedArrangerStrategy.value !== "classic" || pipePrefix
          ? `${pipePrefix}${strategyLabel} · ${style.value}`
          : null;

      const payload: Parameters<LyraForgeApi["arrangeSong"]>[0] = {
        song_id: selectedSongId.value,
        instrument_profile_id: selectedProfileId.value,
        style: style.value,
        speed: speed.value,
        transpose: parsedTranspose,
        arpeggiate_ms: Math.max(0, Math.min(60, Math.round(Number(arpeggiateMs.value) || 0))),
        prefer_melody_track: true,
        arranger_strategy: selectedArrangerStrategy.value,
      };
      if (activeTr?.id) payload.transcription_id = activeTr.id;
      if (includeTracks !== null) payload.include_tracks = includeTracks;
      if (selectedMelodyTrack.value !== null) payload.melody_track = selectedMelodyTrack.value;
      if (customLabel) payload.label = customLabel;

      const res = await api.arrangeSong(payload);
      comparisonResult.value = null;
      await refreshSongs({ alsoRefreshAll: true });
      await selectSong(selectedSongId.value);
      if (activeTr?.id) {
        selectedTranscriptionId.value = activeTr.id;
        await refreshSongTracks(selectedSongId.value, activeTr.id);
      }
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
    const includeTracks = resolveIncludeTracksPayload();
    if (includeTracks !== null && includeTracks.length === 0) {
      reportError("请至少勾选一条音轨参与编曲");
      return;
    }
    busy.value = true;
    errorMessage.value = "";
    try {
      const trId = !hasMidiSource.value
        ? selectedTranscriptionId.value ?? songTranscriptions.value[0]?.id ?? null
        : null;
      const arp = Math.max(0, Math.min(60, Math.round(Number(arpeggiateMs.value) || 0)));
      const res = await api.arrangeAB({
        song_id: selectedSongId.value,
        instrument_profile_id: selectedProfileId.value,
        transcription_id: trId,
        variant_a: {
          style: style.value,
          speed: speed.value,
          transpose: parsedTranspose,
          arpeggiate_ms: arp,
          arranger_strategy: "classic",
          include_tracks: includeTracks,
          melody_track: selectedMelodyTrack.value,
          label: "A · 经典基线",
        },
        variant_b: {
          style: style.value,
          speed: speed.value,
          transpose: parsedTranspose,
          arpeggiate_ms: arp,
          arranger_strategy: "vocal_lead",
          include_tracks: includeTracks,
          melody_track: selectedMelodyTrack.value,
          label: "B · 主旋律增强",
        },
      });
      await refreshSongs({ alsoRefreshAll: true });
      await selectSong(selectedSongId.value);
      if (trId) {
        selectedTranscriptionId.value = trId;
        await refreshSongTracks(selectedSongId.value, trId);
      }
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
      await refreshSongs({ alsoRefreshAll: true });
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

  async function handleRenameArrangement(arrangementId: string, label: string): Promise<void> {
    try {
      const res = await api.renameArrangement(arrangementId, label);
      arrangements.value = arrangements.value.map((a) =>
        a.id === res.arrangement.id ? res.arrangement : a,
      );
      if (arrDetail.value?.arrangement.id === res.arrangement.id) {
        arrDetail.value = { ...arrDetail.value, arrangement: res.arrangement };
      }
      await refreshQueue();
      pushToast("ok", "版本名称已更新");
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
      await refreshSongs({ alsoRefreshAll: true });
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
      stopJobPolling();
      transcriptionJobs.value = [];
      selectedSongId.value = null;
      selectedSongSnapshot.value = null;
      allSongs.value = [];
      songSources.value = [];
      songTranscriptions.value = [];
      arrangements.value = [];
      selectedArrId.value = "";
      arrDetail.value = null;
      selectedTranscriptionId.value = null;
      songTracks.value = [];
      selectedTrackIndices.value = null;
      selectedMelodyTrack.value = null;
      detectedMelodyTrack.value = null;
      await refreshSongs({ alsoRefreshAll: true });
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
      await api.saveSetting("windows_allowed_processes", allowedProcessesSetting.value);
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
        await refreshSongs({ alsoRefreshAll: true });
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
      const started = await api.startPlayback(prepared.value.prepare_token, 10);
      prepared.value = null;
      playbackStatus.value = await api.playbackStatus();
      reportOk(
        started.status === "waiting_focus"
          ? "已进入等待焦点状态：请在 10 秒内切换到游戏窗口，检测到后才会开始发送按键"
          : "演奏已启动",
      );
      stopPolling();
      pollTimer = window.setInterval(async () => {
        try {
          playbackStatus.value = await api.playbackStatus();
          const state = playbackStatus.value.state;
          if (state === "focus_timeout" || state === "permission_required") {
            stopPolling();
            const detail = playbackStatus.value.last_result?.error;
            reportError(
              typeof detail === "string" && detail
                ? detail
                : `演奏未开始：${state}（请切到游戏窗口或检查管理员权限）`,
            );
            return;
          }
          if (state !== "running" && state !== "paused" && state !== "waiting_focus") {
            stopPolling();
            reportOk(`演奏已结束（状态：${state}）`);
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

  async function refreshQueue(): Promise<void> {
    queue.value = await api.getQueue();
  }

  async function handleAddToQueue(): Promise<void> {
    if (!selectedArrId.value) return;
    try {
      queue.value = await api.addToQueue(selectedArrId.value);
      pushToast("ok", `已加入播放队列（共 ${queue.value.items.length} 首）`);
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  async function handleQueueStep(delta: number): Promise<void> {
    try {
      const res = await api.stepQueue(delta);
      queue.value = res.queue;
      playbackStatus.value = await api.playbackStatus();
      const item = res.queue.items[res.queue.index];
      if (item) {
        pushToast("info", `队列切换到：${item.label}`);
      } else {
        pushToast("info", "播放队列为空");
      }
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  async function handleClearQueue(): Promise<void> {
    try {
      queue.value = await api.clearQueue();
      pushToast("info", "已清空播放队列");
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  async function refreshGpu(): Promise<void> {
    gpuStatus.value = await api.getGpuStatus();
  }

  async function handleSetGpuDevice(device: string): Promise<void> {
    try {
      gpuStatus.value = await api.setDettatoDevice(device);
      pushToast("ok", `dettato 推理设备已设置为 ${gpuStatus.value.device}`);
    } catch (err) {
      reportError((err as Error).message);
    }
  }

  async function runGpuTorchInstall(
    toolKey: "dettato-gpu" | "demucs-gpu",
    starter: () => Promise<unknown>,
    label: string,
  ): Promise<void> {
    if (toolBusy.value) return;
    toolBusy.value = toolKey;
    try {
      await starter();
      pushToast("info", `正在为 ${label} 安装 CUDA 版 PyTorch（约 2.5 GB），请保持网络连接…`);
      const deadline = Date.now() + 60 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        await refreshTools();
        const state = toolInstalls.value[toolKey];
        if (state && state.status !== "running") {
          if (state.status === "installed") {
            pushToast("ok", `${label} CUDA 版 PyTorch 已安装并验证可用`);
          } else {
            pushToast("error", state.error ?? `${label} CUDA 版 PyTorch 安装失败`);
          }
          break;
        }
      }
      await refreshGpu();
    } catch (err) {
      reportError((err as Error).message);
    } finally {
      toolBusy.value = null;
    }
  }

  async function handleInstallGpuTorch(): Promise<void> {
    await runGpuTorchInstall("dettato-gpu", () => api.installDettatoGpu(), "dettato");
  }

  async function handleInstallDemucsGpu(): Promise<void> {
    await runGpuTorchInstall("demucs-gpu", () => api.installDemucsGpu(), "Demucs");
  }

  async function refreshHotkeys(): Promise<void> {
    const state = await api.getHotkeys();
    hotkeyActions.value = state.actions;
    hotkeyBindings.value = { ...state.bindings };
    hotkeyErrors.value = { ...state.errors };
    hotkeySupported.value = state.supported;
  }

  async function handleSaveHotkeys(): Promise<void> {
    const bindings = Object.entries(hotkeyBindings.value)
      .filter(([, text]) => text.trim())
      .map(([action, text]) => ({ action, text: text.trim() }));
    try {
      const res = await api.saveHotkeys(bindings);
      hotkeyBindings.value = { ...res.bindings };
      hotkeyErrors.value = { ...res.errors };
      hotkeySupported.value = res.supported;
      const failed = Object.keys(res.errors);
      if (failed.length > 0) {
        pushToast("error", `部分热键未注册：${failed.join("、")}`);
      } else {
        pushToast("ok", bindings.length ? "全局热键已保存并生效" : "已清空所有全局热键");
      }
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

  async function handleRelaunchElevated(): Promise<void> {
    try {
      const res = await api.relaunchElevated();
      if (res.relaunched) {
        pushToast("info", "已请求以管理员身份重启，请在 UAC 提示中确认；随后重新准备并开始演奏");
      } else {
        pushToast("error", "无法自动提权，请手动右键 LyraForge.exe → 以管理员身份运行");
      }
    } catch (err) {
      reportError((err as Error).message);
    }
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

  async function refreshPipelinesAndArrangers(): Promise<void> {
    if (typeof api.listPipelines === "function") {
      try {
        const res = await api.listPipelines();
        if (res.pipelines?.length) {
          pipelines.value = res.pipelines;
        }
      } catch {
        pipelines.value = [...DEFAULT_PIPELINES];
      }
    }
    if (typeof api.listArrangers === "function") {
      try {
        const res = await api.listArrangers();
        if (res.strategies?.length) {
          arrangerStrategies.value = res.strategies;
        }
      } catch {
        arrangerStrategies.value = [...DEFAULT_ARRANGER_STRATEGIES];
      }
    }
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
      await refreshPipelinesAndArrangers();
      await refreshGpu();
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
      await refreshPipelinesAndArrangers();
      await refreshPresets();
      await refreshHotkeys();
      await refreshTools();
      await refreshQueue();
      await refreshGpu();
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
      if (typeof settings.windows_allowed_processes === "string") {
        allowedProcessesSetting.value = settings.windows_allowed_processes;
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
      await refreshJobs();
      if (typeof window !== "undefined") {
        const songParam = new URLSearchParams(window.location.search).get("song");
        if (songParam && allSongs.value.some((s) => s.id === songParam)) {
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
    availableTranscribers,
    pipelines,
    selectedPipelineId,
    selectedPipelineInfo,
    selectedVocalEngineId,
    selectedAccompEngineId,
    arrangerStrategies,
    selectedArrangerStrategy,
    selectedTranscriptionId,
    songTracks,
    selectedTrackIndices,
    selectedMelodyTrack,
    detectedMelodyTrack,
    songs,
    allSongs,
    recentSongs,
    searchQuery,
    filterTag,
    filterFavoritesOnly,
    selectedSongId,
    selectedSong,
    songSources,
    songTranscriptions,
    songTitleById,
    transcribeSongId,
    transcribeSongTitle,
    transcribeSources,
    transcribeTranscriptions,
    transcribeHasAudio,
    selectTranscribeSong,
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
    transcriptionJobs,
    runningTranscriptionJobs,
    currentSongJob,
    otherSongJobs,
    isSongTranscribing,
    activeJob,
    style,
    speed,
    transposeInput,
    arpeggiateMs,
    previewUrl,
    previewCurrentMs,
    previewDurationMs,
    previewPlaying,
    previewSeekTargetMs,
    updatePreviewPlayback,
    requestPreviewSeek,
    soundingKeyIds,
    playbackMode,
    realtime,
    prepared,
    playbackStatus,
    allowedTitlesSetting,
    allowedProcessesSetting,
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
    handleRelaunchElevated,
    gpuStatus,
    refreshGpu,
    handleSetGpuDevice,
    handleInstallGpuTorch,
    handleInstallDemucsGpu,
    presets,
    refreshPresets,
    applyPreset,
    hotkeyActions,
    hotkeyBindings,
    hotkeyErrors,
    hotkeySupported,
    refreshHotkeys,
    handleSaveHotkeys,
    queue,
    refreshQueue,
    handleAddToQueue,
    handleQueueStep,
    handleClearQueue,
    selectSong,
    selectArrangement,
    selectTranscriptionForStudio,
    openSongInView,
    openTranscriptionInStudio,
    refreshSongTracks,
    toggleTrackIncluded,
    reloadSelectedSongDetail,
    refreshJobs,
    handleProfileChange,
    importDroppedOrPickedFile,
    handleImport,
    handleStartTranscribe,
    handleCancelTranscribe,
    handleArrange,
    handleArrangeAB,
    handleSaveEdited,
    handleToggleFavorite,
    handleRenameArrangement,
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
