export interface HealthResponse {
  status: string;
  version: string;
  platform: string;
  windows_playback_available: boolean;
}

export interface ProfileKeyDef {
  key_id: string;
  row?: string;
  degree?: number;
  pitch: number;
  binding: string;
}

export interface ProfileSummary {
  id: string;
  display_name: string;
  display_name_en?: string;
  key_count: number;
  calibration_status: string;
}

export interface ProfileDetail {
  id: string;
  display_name: string;
  key_count: number;
  keys: ProfileKeyDef[];
  calibration: { status: string };
}

export interface SourceRecord {
  id: string;
  kind: "midi" | "audio";
  original_name: string;
}

export interface SongTrackInfo {
  index: number;
  name: string;
  note_count: number;
  channels: number[];
  is_percussion: boolean;
  min_pitch: number;
  max_pitch: number;
}

export interface SongTracksResponse {
  song_id: string;
  source_kind: string | null;
  transcription_id: string | null;
  pipeline_id: string | null;
  detected_melody_track: number | null;
  tracks: SongTrackInfo[];
}

export interface TranscriptionRecord {
  id: string;
  engine: string;
  engine_version: string;
  pipeline_id?: string;
  tracks?: SongTrackInfo[];
  metadata?: {
    degraded_mode?: boolean;
    drums_removed?: boolean;
    warnings?: string[];
    vocal_cleanup?: string | null;
    vocal_range?: string | null;
  };
  status: string;
  note_count: number;
  created_at: string;
}

export interface PipelineInfo {
  id: string;
  display_name: string;
  description: string;
  recommended_for: string;
  stages: string[];
  required_tools: string[];
  available: boolean;
  missing_tools: string[];
  default_engine_id: string;
  default_vocal_engine_id: string | null;
  default_accomp_engine_id: string | null;
  default_arranger_strategy: string;
  supports_engine_override: boolean;
  resolved_vocal_engine_id?: string | null;
  resolved_accomp_engine_id?: string | null;
  low_resource_available?: boolean;
  warnings?: string[];
}

export interface ArrangerStrategyInfo {
  id: string;
  display_name: string;
  description: string;
  recommended_for: string;
}

export interface TranscriberInfo {
  id: string;
  display_name: string;
  available: boolean;
  license: string;
  scope_note: string;
}

export interface ToolStatus {
  id: string;
  display_name: string;
  license: string;
  description: string;
  kind: "binary" | "python";
  download_mb: number;
  env_var: string;
  installed: boolean;
  source: "managed" | "system" | null;
  path: string | null;
  version: string | null;
}

export interface ToolInstallState {
  tool_id: string;
  status: "running" | "installed" | "failed";
  progress: number;
  message: string;
  error: string | null;
}

export interface ToolsResponse {
  tools_dir: string;
  tools: ToolStatus[];
  installs: ToolInstallState[];
}

export interface HotkeyActionInfo {
  id: string;
  label: string;
}

export interface QueueItemInfo {
  arrangement_id: string;
  label: string;
}

export interface QueueState {
  items: QueueItemInfo[];
  index: number;
  mode: string;
  realtime: boolean;
}

export interface HotkeyState {
  supported: boolean;
  bindings: Record<string, string>;
  errors: Record<string, string>;
  actions: HotkeyActionInfo[];
}

export interface GpuTorchInfo {
  version: string | null;
  cuda_build: string | null;
  cuda_available: boolean;
  device_count: number;
  mps_available?: boolean;
  torchaudio_version?: string | null;
  torchaudio_ok?: boolean;
  torchaudio_error?: string | null;
}

export interface GpuStatus {
  nvidia: { present: boolean; name: string | null; driver: string | null };
  dettato_installed: boolean;
  dettato_torch: GpuTorchInfo | null;
  demucs_installed?: boolean;
  demucs_torch?: GpuTorchInfo | null;
  device: string;
  device_env: string;
}

export interface ArrangePresetInfo {
  id: string;
  profile_id: string;
  name: string;
  name_en: string;
  description: string;
  style: "melody" | "balanced" | "rich";
  transpose: number | null;
  arpeggiate_ms: number;
  speed: number;
  semitone_policy: "nearest" | "drop";
  max_chord_keys: number | null;
}

export interface TranscriptionJob {
  id: string;
  song_id: string;
  engine_id: string;
  pipeline_id?: string;
  status: "queued" | "running" | "completed" | "cancelled" | "failed";
  stage: string;
  progress: number;
  warnings?: string[];
  transcription: TranscriptionRecord | null;
  error: { code: string; message: string } | null;
  started_at?: number | null;
  finished_at?: number | null;
  elapsed_s?: number;
}

export interface SongSummary {
  id: string;
  title: string;
  artist: string;
  tags: string[];
  arrangement_count: number;
  created_at: string;
  updated_at: string;
}

export interface ArrangementRecord {
  id: string;
  song_id: string;
  profile_id: string;
  style: string;
  transpose: number;
  speed: number;
  playable_ratio: number;
  event_count: number;
  duration_ms: number;
  preview_path: string | null;
  is_favorite?: boolean;
  parent_id?: string | null;
  score?: number | null;
  user_vote?: number;
  label?: string | null;
  transcription_id?: string | null;
  arranger_strategy?: string;
  created_at: string;
}

export interface PerformanceEventItem {
  at_ms: number;
  key_id: string;
  action?: string;
  hold_ms: number;
  source_pitch?: number;
  mapped_pitch: number;
  source_track?: number;
  source_channel?: number;
  velocity?: number;
  adjustments?: string[];
}

export interface QualityBreakdown {
  overall_score: number;
  melody_preservation: number;
  rhythmic_fidelity: number;
  pitch_contour_preservation: number;
  harmonic_coherence: number;
  missing_note_penalty: number;
  dense_key_conflict_penalty: number;
  large_leap_penalty: number;
  melody_track?: number | null;
  warnings: string[];
}

export interface ComparisonMetricDiff {
  a: number;
  b: number;
  delta: number;
}

export interface ComparisonResult {
  id_a: string;
  id_b: string;
  winner: string;
  score_a: number;
  score_b: number;
  score_delta: number;
  metrics: Record<string, ComparisonMetricDiff>;
  summary: string;
  a?: ArrangementRecord;
  b?: ArrangementRecord;
}

export type AccompDensity = "auto" | "minimal" | "balanced" | "full";
export type PhraseOctaveMode = "original" | "smooth_lift" | "centered";

export interface ArrangementDetailResponse {
  arrangement: ArrangementRecord;
  performance: {
    arrangement_id: string;
    duration_ms: number;
    events: PerformanceEventItem[];
  };
  report: {
    calibration_status: string;
    stats: {
      input_notes?: number;
      excluded_percussion?: number;
      excluded_tracks?: number;
      emitted_events: number;
      considered_notes: number;
      direct?: number;
      octave_folded: number;
      semitone_substituted: number;
      dropped?: {
        out_of_range?: number;
        semitone_dropped?: number;
        duplicate_key?: number;
        polyphony_limit?: number;
        repeat_too_fast?: number;
        accomp_thinned?: number;
        [reason: string]: number | undefined;
      };
      playable_ratio: number;
      unchanged_ratio?: number;
      max_chord_size?: number;
      melody_track?: number | null;
      arranger_strategy?: string;
      timing_mode?: TimingMode;
      timing_adjustments?: {
        arpeggiated_events?: number;
        melody_retrigger_replacements?: number;
        hold_shortened_for_retrigger?: number;
        inter_key_adjusted?: number;
        min_same_key_interval_ms?: number;
        min_key_release_gap_ms?: number;
        min_inter_key_interval_ms?: number;
        trigger_mode?: string;
        timing_provisional?: boolean;
      };
      dynamics_adjustments?: {
        accomp_density?: string;
        phrase_octave_mode?: string;
        cross_stem_align_ms?: number;
        cross_stem_aligned?: number;
        accomp_thinned?: number;
        used_stem_dynamics?: boolean;
        phrase_count?: number;
        phrases_shifted_up?: number;
        phrases_shifted_down?: number;
        phrase_shifted_notes?: number;
      };
    };
    quality?: QualityBreakdown;
  } | null;
}

export type TimingMode = "adapted" | "strict_fidelity";
export type LateEventPolicy = "shift_clock" | "drop_late" | "catch_up";
export type PreviewTimbre = "auto" | "piano" | "lyre" | "zither" | "vintage";

export interface ArrangePreviewResponse {
  arrangement_id: string;
  already_exists: boolean;
  existing_label?: string | null;
  performance: {
    arrangement_id: string;
    duration_ms: number;
    events: PerformanceEventItem[];
  };
  report: ArrangementDetailResponse["report"];
}

export interface PlaybackPrepareResponse {
  prepare_token: string;
  expires_in_s: number;
  arrangement_id: string;
  mode: "dry-run" | "windows";
  realtime: boolean;
  event_count: number;
  duration_ms: number;
  calibration_status: string;
  sends_os_input: boolean;
  risk_notice: string;
}

export interface PlaybackStatusResponse {
  state: string;
  session_id: string | null;
  arrangement_id: string | null;
  mode: string | null;
  sends_os_input: boolean;
  keys_still_pressed: string[];
  last_result: {
    state: string;
    actions_sent: number;
    actions_total: number;
    elapsed_ms: number;
    stop_reason: string | null;
    error: string | null;
    p50_lateness_ms?: number;
    p95_lateness_ms?: number;
    p99_lateness_ms?: number;
    max_lateness_ms?: number;
    mean_lateness_ms?: number;
    late_events_count?: number;
    late_events_dropped?: number;
    clock_shifts_count?: number;
    total_clock_shift_ms?: number;
    retrigger_conflicts_count?: number;
    late_event_policy?: LateEventPolicy;
    min_key_release_gap_ms?: number;
  } | null;
}

export interface CalibrationPatternInfo {
  id: string;
  code: string;
  display_name: string;
  description: string;
  default_duration_s: number | null;
}

export interface CalibrationRunDryResponse {
  tier: "dry_run_virtual" | "realtime_scheduler";
  verifies_game_audio: boolean;
  notice: string;
  pattern: CalibrationPatternInfo;
  instrument_profile_id: string;
  timing_profile: Record<string, unknown>;
  expected_events: number;
  expected_duration_ms: number;
  actual_elapsed_ms: number;
  drift_ms: number;
  cpu_pct: number;
  result: NonNullable<PlaybackStatusResponse["last_result"]>;
  log_verification: {
    down_count: number;
    first_12_keys: string[];
    overlapping_key_downs: number;
    min_observed_release_gap_ms: number | null;
  };
  segments: Array<Record<string, unknown>>;
}

export interface CalibrationPrepareResponse extends PlaybackPrepareResponse {
  pattern: CalibrationPatternInfo;
  segments: Array<Record<string, unknown>>;
}

export interface CalibrationAnalyzeResponse {
  measurement_basis: string;
  pattern_id: string;
  sample_rate: number;
  duration_ms: number;
  estimated_offset_ms: number;
  expected_onset_clusters: number;
  detected_onsets_total: number;
  matched_onsets: number;
  detection_rate: number;
  mean_abs_error_ms: number | null;
  max_abs_error_ms: number | null;
  segments: Array<Record<string, unknown>>;
  suggested_timing: Record<string, unknown>;
}

export interface ApiClientConfig {
  apiBase: string;
  sessionToken: string;
}

export interface AgentStep {
  tool: string;
  status: string;
  detail: string;
  output: Record<string, unknown>;
}

export interface AgentRunResult {
  status: "completed" | "needs_confirmation" | "not_found";
  provider: string;
  intent: Record<string, unknown>;
  steps: AgentStep[];
  candidates: Array<Record<string, unknown>>;
  selected_song: SongSummary | null;
  selected_arrangement: ArrangementRecord | null;
  comparison: ComparisonResult | null;
  preview_url: string | null;
  requires_confirmation: boolean;
  confirmation_prompt: string | null;
  message: string;
}

export function resolveBootstrapConfig(): ApiClientConfig {
  if (typeof window !== "undefined") {
    if (window.__LYRAFORGE_CONFIG__) {
      return window.__LYRAFORGE_CONFIG__;
    }
    if (window.location.hash.length > 1) {
      const params = new URLSearchParams(window.location.hash.slice(1));
      const apiBase = params.get("apiBase") ?? "";
      const sessionToken = params.get("sessionToken") ?? "";
      if (sessionToken) {
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
        return { apiBase, sessionToken };
      }
    }
  }
  return { apiBase: "", sessionToken: "" };
}

export class LyraForgeApi {
  readonly base: string;
  readonly token: string;

  constructor(cfg: ApiClientConfig = resolveBootstrapConfig()) {
    this.base = cfg.apiBase.replace(/\/$/, "");
    this.token = cfg.sessionToken;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers ?? {});
    if (this.token) {
      headers.set("X-LyraForge-Token", this.token);
    }
    const resp = await fetch(`${this.base}${path}`, { ...init, headers });
    if (!resp.ok) {
      let msg = `HTTP ${resp.status}`;
      try {
        const body = await resp.json();
        msg = body?.error?.message ?? body?.detail?.message ?? msg;
      } catch {
        // ignore JSON parse errors on error payloads
      }
      throw new Error(msg);
    }
    return (await resp.json()) as T;
  }

  health(): Promise<HealthResponse> {
    return this.request<HealthResponse>("/health");
  }

  listProfiles(): Promise<{ profiles: ProfileSummary[] }> {
    return this.request<{ profiles: ProfileSummary[] }>("/v1/profiles");
  }

  getProfile(profileId: string): Promise<ProfileDetail> {
    return this.request<ProfileDetail>(`/v1/profiles/${encodeURIComponent(profileId)}`);
  }

  listSongs(
    query = "",
    opts?: { tag?: string; favoritesOnly?: boolean },
  ): Promise<{ songs: SongSummary[] }> {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (opts?.tag?.trim()) params.set("tag", opts.tag.trim());
    if (opts?.favoritesOnly) params.set("favorites_only", "true");
    const qs = params.toString();
    return this.request<{ songs: SongSummary[] }>(`/v1/library/songs${qs ? `?${qs}` : ""}`);
  }

  getSong(songId: string): Promise<{
    song: SongSummary;
    sources: SourceRecord[];
    transcriptions: TranscriptionRecord[];
    arrangements: ArrangementRecord[];
  }> {
    return this.request(`/v1/library/songs/${encodeURIComponent(songId)}`);
  }

  listTranscribers(): Promise<{ transcribers: TranscriberInfo[] }> {
    return this.request<{ transcribers: TranscriberInfo[] }>("/v1/transcribers");
  }

  listPipelines(): Promise<{ pipelines: PipelineInfo[] }> {
    return this.request<{ pipelines: PipelineInfo[] }>("/v1/pipelines");
  }

  listArrangers(): Promise<{ strategies: ArrangerStrategyInfo[] }> {
    return this.request<{ strategies: ArrangerStrategyInfo[] }>("/v1/arrangers");
  }

  getSongTracks(songId: string, transcriptionId?: string | null): Promise<SongTracksResponse> {
    const qs = transcriptionId ? `?transcription_id=${encodeURIComponent(transcriptionId)}` : "";
    return this.request<SongTracksResponse>(
      `/v1/library/songs/${encodeURIComponent(songId)}/tracks${qs}`,
    );
  }

  listTools(): Promise<ToolsResponse> {
    return this.request<ToolsResponse>("/v1/tools");
  }

  listPresets(profileId?: string): Promise<{ presets: ArrangePresetInfo[] }> {
    const qs = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : "";
    return this.request<{ presets: ArrangePresetInfo[] }>(`/v1/presets${qs}`);
  }

  relaunchElevated(): Promise<{ relaunched: boolean }> {
    return this.request<{ relaunched: boolean }>("/v1/app/relaunch-elevated", {
      method: "POST",
    });
  }

  renameArrangement(
    arrangementId: string,
    label: string,
  ): Promise<{ arrangement: ArrangementRecord }> {
    return this.request<{ arrangement: ArrangementRecord }>(
      `/v1/arrangements/${encodeURIComponent(arrangementId)}/label`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label }),
      },
    );
  }

  getHotkeys(): Promise<HotkeyState> {
    return this.request<HotkeyState>("/v1/hotkeys");
  }

  getQueue(): Promise<QueueState> {
    return this.request<QueueState>("/v1/playback/queue");
  }

  addToQueue(arrangementId: string): Promise<QueueState> {
    return this.request<QueueState>("/v1/playback/queue/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arrangement_id: arrangementId }),
    });
  }

  clearQueue(): Promise<QueueState> {
    return this.request<QueueState>("/v1/playback/queue/clear", { method: "POST" });
  }

  stepQueue(delta: number): Promise<{ queue: QueueState; playback: { status?: string } }> {
    return this.request("/v1/playback/queue/step", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ delta }),
    });
  }

  saveHotkeys(
    bindings: Array<{ action: string; text: string }>,
  ): Promise<{ supported: boolean; bindings: Record<string, string>; errors: Record<string, string> }> {
    return this.request("/v1/hotkeys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bindings }),
    });
  }

  installTool(toolId: string): Promise<{ install: ToolInstallState }> {
    return this.request<{ install: ToolInstallState }>(
      `/v1/tools/${encodeURIComponent(toolId)}/install`,
      { method: "POST" },
    );
  }

  getGpuStatus(): Promise<GpuStatus> {
    return this.request<GpuStatus>("/v1/gpu");
  }

  setDettatoDevice(device: string): Promise<GpuStatus> {
    return this.request<GpuStatus>("/v1/gpu/device", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device }),
    });
  }

  installDettatoGpu(): Promise<{ install: ToolInstallState }> {
    return this.request<{ install: ToolInstallState }>("/v1/gpu/install", {
      method: "POST",
    });
  }

  installDemucsGpu(): Promise<{ install: ToolInstallState }> {
    return this.request<{ install: ToolInstallState }>("/v1/tools/demucs-gpu/install", {
      method: "POST",
    });
  }

  importMedia(file: File, title: string, artist: string, tags: string): Promise<{ song: SongSummary }> {
    const fd = new FormData();
    fd.append("file", file);
    if (title.trim()) fd.append("title", title.trim());
    if (artist.trim()) fd.append("artist", artist.trim());
    if (tags.trim()) fd.append("tags", tags.trim());
    return this.request("/v1/imports", { method: "POST", body: fd });
  }

  submitTranscribeJob(
    songId: string,
    engineId: string,
    opts?: {
      pipelineId?: string;
      vocalEngineId?: string | null;
      accompEngineId?: string | null;
      vocalCleanup?: string;
      vocalRange?: string;
    },
  ): Promise<{ job: TranscriptionJob }> {
    const payload: Record<string, unknown> = {
      song_id: songId,
      engine_id: engineId,
      async_mode: true,
    };
    if (opts?.pipelineId) payload.pipeline_id = opts.pipelineId;
    if (opts?.vocalEngineId && opts.vocalEngineId !== "auto") {
      payload.vocal_engine_id = opts.vocalEngineId;
    }
    if (opts?.accompEngineId && opts.accompEngineId !== "auto") {
      payload.accomp_engine_id = opts.accompEngineId;
    }
    if (opts?.vocalCleanup) payload.vocal_cleanup = opts.vocalCleanup;
    if (opts?.vocalRange) payload.vocal_range = opts.vocalRange;
    return this.request("/v1/jobs/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  getJob(jobId: string): Promise<{ job: TranscriptionJob }> {
    return this.request(`/v1/jobs/${encodeURIComponent(jobId)}`);
  }

  listJobs(): Promise<{ jobs: TranscriptionJob[] }> {
    return this.request<{ jobs: TranscriptionJob[] }>("/v1/jobs");
  }

  cancelJob(jobId: string): Promise<{ job: TranscriptionJob }> {
    return this.request(`/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  }

  arrangeSong(payload: {
    song_id: string;
    instrument_profile_id?: string;
    style: "melody" | "balanced" | "rich";
    speed: number;
    transpose: number | null;
    arpeggiate_ms?: number;
    prefer_melody_track?: boolean;
    transcription_id?: string | null;
    arranger_strategy?: string;
    include_tracks?: number[] | null;
    melody_track?: number | null;
    vocal_ducking?: boolean;
    melody_ceiling?: boolean;
    anti_clash_semitones?: boolean;
    timing_mode?: TimingMode;
    accomp_density?: AccompDensity | null;
    phrase_octave_mode?: PhraseOctaveMode | null;
    cross_stem_align_ms?: number | null;
    label?: string | null;
  }): Promise<{ arrangement: ArrangementRecord; created?: boolean }> {
    return this.request("/v1/jobs/arrange", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  previewArrange(
    payload: Parameters<LyraForgeApi["arrangeSong"]>[0],
  ): Promise<ArrangePreviewResponse> {
    return this.request("/v1/studio/preview-arrange", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  arrangeAB(payload: {
    song_id: string;
    instrument_profile_id?: string;
    transcription_id?: string | null;
    variant_a?: {
      style: "melody" | "balanced" | "rich";
      speed: number;
      transpose: number | null;
      arpeggiate_ms?: number;
      arranger_strategy?: string;
      include_tracks?: number[] | null;
      melody_track?: number | null;
      timing_mode?: TimingMode;
      accomp_density?: AccompDensity | null;
      phrase_octave_mode?: PhraseOctaveMode | null;
      cross_stem_align_ms?: number | null;
      label?: string;
    };
    variant_b?: {
      style: "melody" | "balanced" | "rich";
      speed: number;
      transpose: number | null;
      arpeggiate_ms?: number;
      arranger_strategy?: string;
      include_tracks?: number[] | null;
      melody_track?: number | null;
      timing_mode?: TimingMode;
      accomp_density?: AccompDensity | null;
      phrase_octave_mode?: PhraseOctaveMode | null;
      cross_stem_align_ms?: number | null;
      label?: string;
    };
  }): Promise<{
    arrangement_a: ArrangementRecord;
    arrangement_b: ArrangementRecord;
    comparison: ComparisonResult;
  }> {
    return this.request("/v1/jobs/arrange-ab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  editArrangement(
    arrangementId: string,
    events: PerformanceEventItem[],
    label?: string,
  ): Promise<{ arrangement: ArrangementRecord }> {
    return this.request(`/v1/arrangements/${encodeURIComponent(arrangementId)}/edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events, label: label?.trim() || null }),
    });
  }

  setFavorite(arrangementId: string, isFavorite: boolean): Promise<{ arrangement: ArrangementRecord }> {
    return this.request(`/v1/arrangements/${encodeURIComponent(arrangementId)}/favorite`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_favorite: isFavorite }),
    });
  }

  setVote(arrangementId: string, vote: -1 | 0 | 1): Promise<{ arrangement: ArrangementRecord }> {
    return this.request(`/v1/arrangements/${encodeURIComponent(arrangementId)}/vote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vote }),
    });
  }

  compareArrangements(arrangementAId: string, arrangementBId: string): Promise<ComparisonResult> {
    return this.request("/v1/arrangements/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arrangement_a_id: arrangementAId, arrangement_b_id: arrangementBId }),
    });
  }

  getArrangement(arrangementId: string): Promise<ArrangementDetailResponse> {
    return this.request(`/v1/arrangements/${encodeURIComponent(arrangementId)}`);
  }

  deleteArrangement(
    arrangementId: string,
  ): Promise<{ deleted: boolean; arrangement_id: string; song_id: string; queue: QueueState }> {
    return this.request(`/v1/arrangements/${encodeURIComponent(arrangementId)}`, {
      method: "DELETE",
    });
  }

  async fetchPreviewAudioUrl(
    arrangementId: string,
    fixedVelocity = false,
    timbre: PreviewTimbre = "auto",
  ): Promise<string> {
    const headers = new Headers();
    if (this.token) {
      headers.set("X-LyraForge-Token", this.token);
    }
    const cleanTimbre: PreviewTimbre = timbre || "auto";
    const bodyPayload: {
      arrangement_id: string;
      fixed_velocity: boolean;
      timbre?: PreviewTimbre;
    } = {
      arrangement_id: arrangementId,
      fixed_velocity: fixedVelocity,
    };
    if (cleanTimbre !== "auto") {
      bodyPayload.timbre = cleanTimbre;
    }
    const resp = await fetch(`${this.base}/v1/preview`, {
      method: "POST",
      headers: { ...Object.fromEntries(headers.entries()), "Content-Type": "application/json" },
      body: JSON.stringify(bodyPayload),
    });
    if (!resp.ok) {
      throw new Error(`预览生成失败 (HTTP ${resp.status})`);
    }
    const fallbackParams: string[] = [];
    if (fixedVelocity) fallbackParams.push("fixed_velocity=true");
    if (cleanTimbre !== "auto") fallbackParams.push(`timbre=${encodeURIComponent(cleanTimbre)}`);
    const fallbackQuery = fallbackParams.length > 0 ? `?${fallbackParams.join("&")}` : "";
    let previewPath = `/v1/arrangements/${encodeURIComponent(arrangementId)}/preview.wav${fallbackQuery}`;
    if (typeof resp.json === "function") {
      try {
        const meta = (await resp.json()) as { preview_url?: string };
        if (meta && typeof meta.preview_url === "string" && meta.preview_url) {
          previewPath = meta.preview_url;
        }
      } catch {
        // Fallback for minimal Response stubs without JSON payload.
      }
    }
    const resolvedUrl = previewPath.startsWith("http") ? previewPath : `${this.base}${previewPath}`;
    const wavResp = await fetch(resolvedUrl, { headers });
    if (!wavResp.ok) {
      throw new Error(`音频加载失败 (HTTP ${wavResp.status})`);
    }
    const blob = await wavResp.blob();
    return URL.createObjectURL(blob);
  }

  preparePlayback(payload: {
    arrangement_id: string;
    mode: "dry-run" | "windows";
    realtime: boolean;
    min_key_release_gap_ms?: number | null;
    key_hold_ms?: number | null;
    late_event_policy?: LateEventPolicy;
    late_threshold_ms?: number;
    record_trace?: boolean;
  }): Promise<PlaybackPrepareResponse> {
    return this.request("/v1/playback/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  listCalibrationPatterns(): Promise<{ patterns: CalibrationPatternInfo[] }> {
    return this.request("/v1/calibration/patterns");
  }

  runDryCalibration(payload: {
    pattern_id: string;
    instrument_profile_id?: string;
    realtime?: boolean;
    duration_s?: number | null;
  }): Promise<CalibrationRunDryResponse> {
    return this.request("/v1/calibration/run-dry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  prepareCalibration(payload: {
    pattern_id: string;
    instrument_profile_id?: string;
    mode: "dry-run" | "windows";
    realtime?: boolean;
    duration_s?: number | null;
    min_key_release_gap_ms?: number | null;
    key_hold_ms?: number | null;
    late_event_policy?: LateEventPolicy;
  }): Promise<CalibrationPrepareResponse> {
    return this.request("/v1/calibration/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  analyzeCalibrationWav(
    file: File,
    patternId: string,
    instrumentProfileId?: string,
    toleranceMs = 45,
  ): Promise<CalibrationAnalyzeResponse> {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("pattern_id", patternId);
    if (instrumentProfileId) {
      fd.append("instrument_profile_id", instrumentProfileId);
    }
    fd.append("tolerance_ms", String(toleranceMs));
    return this.request("/v1/calibration/analyze", { method: "POST", body: fd });
  }

  startPlayback(
    prepareToken: string,
    waitForFocusS = 10,
  ): Promise<{ session_id: string; status: string; wait_for_focus_s?: number }> {
    return this.request("/v1/playback/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prepare_token: prepareToken,
        wait_for_focus_s: waitForFocusS,
      }),
    });
  }

  playbackStatus(): Promise<PlaybackStatusResponse> {
    return this.request("/v1/playback/status");
  }

  pausePlayback(): Promise<PlaybackStatusResponse> {
    return this.request("/v1/playback/pause", { method: "POST" });
  }

  resumePlayback(): Promise<PlaybackStatusResponse> {
    return this.request("/v1/playback/resume", { method: "POST" });
  }

  stopPlayback(): Promise<PlaybackStatusResponse> {
    return this.request("/v1/playback/stop", { method: "POST" });
  }

  async downloadExport(arrangementId: string, fmt: "midi" | "json"): Promise<Blob> {
    const headers = new Headers();
    if (this.token) {
      headers.set("X-LyraForge-Token", this.token);
    }
    const ext = fmt === "midi" ? "mid" : "json";
    const resp = await fetch(
      `${this.base}/v1/arrangements/${encodeURIComponent(arrangementId)}/export.${ext}`,
      { headers },
    );
    if (!resp.ok) {
      throw new Error(`导出失败 (HTTP ${resp.status})`);
    }
    return await resp.blob();
  }

  getSettings(): Promise<{ settings: Record<string, unknown> }> {
    return this.request("/v1/settings");
  }

  saveSetting(key: string, value: unknown): Promise<{ settings: Record<string, unknown> }> {
    return this.request("/v1/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    });
  }

  runAgent(payload: {
    prompt: string;
    song_id?: string | null;
    arrangement_id?: string | null;
    allow_network?: boolean;
    source_url?: string | null;
  }): Promise<AgentRunResult> {
    return this.request("/v1/agent/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async exportLyrapack(
    arrangementId: string,
    copyrightConfirmed: boolean,
    licenseNotice = "",
  ): Promise<Blob> {
    const headers = new Headers({ "Content-Type": "application/json" });
    if (this.token) {
      headers.set("X-LyraForge-Token", this.token);
    }
    const resp = await fetch(
      `${this.base}/v1/arrangements/${encodeURIComponent(arrangementId)}/export.lyrapack`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          copyright_confirmed: copyrightConfirmed,
          license_notice: licenseNotice,
        }),
      },
    );
    if (!resp.ok) {
      throw new Error(`分享包导出失败 (HTTP ${resp.status})`);
    }
    return await resp.blob();
  }

  importLyrapack(file: File): Promise<{ song: SongSummary; arrangement: ArrangementRecord }> {
    const fd = new FormData();
    fd.append("file", file);
    return this.request("/v1/imports/lyrapack", { method: "POST", body: fd });
  }

  async downloadBackupZip(): Promise<Blob> {
    const headers = new Headers();
    if (this.token) {
      headers.set("X-LyraForge-Token", this.token);
    }
    const resp = await fetch(`${this.base}/v1/library/backup.zip`, { headers });
    if (!resp.ok) {
      throw new Error(`备份下载失败 (HTTP ${resp.status})`);
    }
    return await resp.blob();
  }

  restoreBackupZip(file: File): Promise<{
    restored: { restored_files: number; song_count: number; schema_version: number };
  }> {
    const fd = new FormData();
    fd.append("file", file);
    return this.request("/v1/library/restore", { method: "POST", body: fd });
  }
}
