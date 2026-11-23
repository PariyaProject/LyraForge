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

export interface TranscriptionRecord {
  id: string;
  engine: string;
  engine_version: string;
  status: string;
  note_count: number;
  created_at: string;
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
  status: "queued" | "running" | "completed" | "cancelled" | "failed";
  stage: string;
  progress: number;
  transcription: TranscriptionRecord | null;
  error: { code: string; message: string } | null;
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
      emitted_events: number;
      considered_notes: number;
      octave_folded: number;
      semitone_substituted: number;
      playable_ratio: number;
    };
    quality?: QualityBreakdown;
  } | null;
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
  } | null;
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

  listTools(): Promise<ToolsResponse> {
    return this.request<ToolsResponse>("/v1/tools");
  }

  listPresets(profileId?: string): Promise<{ presets: ArrangePresetInfo[] }> {
    const qs = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : "";
    return this.request<{ presets: ArrangePresetInfo[] }>(`/v1/presets${qs}`);
  }

  installTool(toolId: string): Promise<{ install: ToolInstallState }> {
    return this.request<{ install: ToolInstallState }>(
      `/v1/tools/${encodeURIComponent(toolId)}/install`,
      { method: "POST" },
    );
  }

  importMedia(file: File, title: string, artist: string, tags: string): Promise<{ song: SongSummary }> {
    const fd = new FormData();
    fd.append("file", file);
    if (title.trim()) fd.append("title", title.trim());
    if (artist.trim()) fd.append("artist", artist.trim());
    if (tags.trim()) fd.append("tags", tags.trim());
    return this.request("/v1/imports", { method: "POST", body: fd });
  }

  submitTranscribeJob(songId: string, engineId: string): Promise<{ job: TranscriptionJob }> {
    return this.request("/v1/jobs/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ song_id: songId, engine_id: engineId, async_mode: true }),
    });
  }

  getJob(jobId: string): Promise<{ job: TranscriptionJob }> {
    return this.request(`/v1/jobs/${encodeURIComponent(jobId)}`);
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
    label?: string | null;
  }): Promise<{ arrangement: ArrangementRecord }> {
    return this.request("/v1/jobs/arrange", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  arrangeAB(payload: {
    song_id: string;
    instrument_profile_id?: string;
    variant_a?: {
      style: "melody" | "balanced" | "rich";
      speed: number;
      transpose: number | null;
      arpeggiate_ms?: number;
      label?: string;
    };
    variant_b?: {
      style: "melody" | "balanced" | "rich";
      speed: number;
      transpose: number | null;
      arpeggiate_ms?: number;
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

  async fetchPreviewAudioUrl(arrangementId: string): Promise<string> {
    const headers = new Headers();
    if (this.token) {
      headers.set("X-LyraForge-Token", this.token);
    }
    const resp = await fetch(`${this.base}/v1/preview`, {
      method: "POST",
      headers: { ...Object.fromEntries(headers.entries()), "Content-Type": "application/json" },
      body: JSON.stringify({ arrangement_id: arrangementId }),
    });
    if (!resp.ok) {
      throw new Error(`预览生成失败 (HTTP ${resp.status})`);
    }
    const wavResp = await fetch(
      `${this.base}/v1/arrangements/${encodeURIComponent(arrangementId)}/preview.wav`,
      { headers },
    );
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
  }): Promise<PlaybackPrepareResponse> {
    return this.request("/v1/playback/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  startPlayback(prepareToken: string): Promise<{ session_id: string; status: string }> {
    return this.request("/v1/playback/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prepare_token: prepareToken }),
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
