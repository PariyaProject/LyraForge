import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import App from "../App.vue";
import type { ArrangementRecord, LyraForgeApi, SongTrackInfo, TranscriptionRecord } from "../api";

function makeStubApi(sourceKind: "midi" | "audio" = "midi"): LyraForgeApi {
  const arr = {
    id: "arr-1",
    song_id: "song-1",
    profile_id: "genshin.windsong_lyre.v1",
    style: "balanced",
    transpose: 0,
    speed: 1.0,
    playable_ratio: 1.0,
    event_count: 8,
    duration_ms: 4000,
    preview_path: null,
    is_favorite: false,
    user_vote: 0,
    score: 92.5,
    label: "均衡版",
  };
  const arrB = {
    ...arr,
    id: "arr-2",
    style: "rich",
    event_count: 10,
    score: 95.0,
    label: "B · 丰满琶音",
  };
  return {
    health: vi.fn().mockResolvedValue({
      status: "ok",
      version: "0.1.0.dev0",
      platform: "darwin",
      windows_playback_available: false,
    }),
    listProfiles: vi.fn().mockResolvedValue({
      profiles: [
        {
          id: "genshin.windsong_lyre.v1",
          display_name: "风物之诗琴",
          key_count: 21,
          calibration_status: "unverified",
        },
        {
          id: "genshin.floral_zither.v1",
          display_name: "镜花之琴",
          key_count: 21,
          calibration_status: "unverified",
        },
      ],
    }),
    getProfile: vi.fn().mockResolvedValue({
      id: "genshin.windsong_lyre.v1",
      display_name: "风物之诗琴",
      key_count: 21,
      calibration: { status: "unverified" },
      keys: [
        { key_id: "high_1", row: "high", degree: 1, pitch: 72, binding: "Q" },
        { key_id: "mid_1", row: "mid", degree: 1, pitch: 60, binding: "A" },
        { key_id: "low_1", row: "low", degree: 1, pitch: 48, binding: "Z" },
      ],
    }),
    listTranscribers: vi.fn().mockResolvedValue({
      transcribers: [
        {
          id: "builtin-mono",
          display_name: "内置单音旋律识别 (YIN)",
          available: true,
          license: "Self-authored",
          scope_note: "适合独奏",
        },
        {
          id: "basic-pitch",
          display_name: "Spotify Basic Pitch",
          available: false,
          license: "Apache-2.0",
          scope_note: "多音识别",
        },
      ],
    }),
    listPipelines: vi.fn().mockResolvedValue({
      pipelines: [
        {
          id: "direct",
          display_name: "经典直转（原流程）",
          description: "直接单引擎转谱",
          recommended_for: "纯钢琴 / 独奏",
          stages: ["音频提取", "单引擎转谱"],
          required_tools: [],
          available: true,
          missing_tools: [],
          default_engine_id: "builtin-mono",
          default_vocal_engine_id: null,
          default_accomp_engine_id: null,
          default_arranger_strategy: "classic",
          supports_engine_override: true,
        },
        {
          id: "vocal_split_full",
          display_name: "人声分离 · 主旋律 + 无鼓伴奏双轨",
          description: "Demucs 分离并去鼓后分别转谱合流",
          recommended_for: "人声流行歌",
          stages: ["Demucs 4 轨分离与去鼓", "人声主旋律识别", "无鼓伴奏识别", "双角色多轨 MIDI 融合"],
          required_tools: ["demucs"],
          available: true,
          missing_tools: [],
          default_engine_id: "basic-pitch",
          default_vocal_engine_id: "basic-pitch",
          default_accomp_engine_id: "basic-pitch",
          default_arranger_strategy: "vocal_lead",
          supports_engine_override: false,
        },
      ],
    }),
    listArrangers: vi.fn().mockResolvedValue({
      strategies: [
        {
          id: "classic",
          display_name: "经典基线",
          description: "原有平衡规则",
          recommended_for: "纯乐器 MIDI",
        },
        {
          id: "vocal_lead",
          display_name: "人声主旋律增强",
          description: "75% 主旋律权重移调、天花板、避让与间奏交接",
          recommended_for: "人声与多轨编曲",
        },
      ],
    }),
    getSongTracks: vi.fn().mockResolvedValue({
      song_id: "song-1",
      source_kind: sourceKind,
      transcription_id: null,
      pipeline_id: sourceKind === "midi" ? "midi" : null,
      detected_melody_track: 0,
      tracks: [],
    }),
    listTools: vi.fn().mockResolvedValue({
      tools_dir: "/tmp/lyraforge-tools",
      tools: [
        {
          id: "ffmpeg",
          display_name: "FFmpeg",
          license: "LGPL/GPL",
          description: "MP3/MP4 decode",
          kind: "binary",
          download_mb: 40,
          env_var: "LYRAFORGE_FFMPEG_BIN",
          installed: false,
          source: null,
          path: null,
          version: null,
        },
        {
          id: "basic-pitch",
          display_name: "Spotify Basic Pitch",
          license: "Apache-2.0",
          description: "polyphonic",
          kind: "python",
          download_mb: 700,
          env_var: "LYRAFORGE_BASIC_PITCH_PYTHON",
          installed: false,
          source: null,
          path: null,
          version: null,
        },
      ],
      installs: [],
    }),
    installTool: vi.fn(),
    listPresets: vi.fn().mockResolvedValue({
      presets: [
        {
          id: "genshin.windsong_lyre.v1.melody",
          profile_id: "genshin.windsong_lyre.v1",
          name: "风物之诗琴 · 主旋律优先",
          name_en: "Windsong Lyre · Melody first",
          description: "只保留主旋律",
          style: "melody",
          transpose: null,
          arpeggiate_ms: 0,
          speed: 1,
          semitone_policy: "nearest",
          max_chord_keys: null,
        },
      ],
    }),
    getHotkeys: vi.fn().mockResolvedValue({
      supported: true,
      bindings: {},
      errors: {},
      actions: [
        { id: "start", label: "开始演奏" },
        { id: "pause", label: "暂停" },
      ],
    }),
    saveHotkeys: vi.fn().mockResolvedValue({ supported: true, bindings: {}, errors: {} }),
    getQueue: vi.fn().mockResolvedValue({ items: [], index: 0, mode: "dry-run", realtime: false }),
    getGpuStatus: vi.fn().mockResolvedValue({
      nvidia: { present: false, name: null, driver: null },
      dettato_installed: false,
      dettato_torch: null,
      device: "auto",
      device_env: "LYRAFORGE_DETTATO_DEVICE",
    }),
    setDettatoDevice: vi.fn(),
    installDettatoGpu: vi.fn(),
    installDemucsGpu: vi.fn(),
    addToQueue: vi.fn(),
    clearQueue: vi.fn(),
    stepQueue: vi.fn(),
    getSettings: vi.fn().mockResolvedValue({ settings: { default_style: "balanced" } }),
    saveSetting: vi.fn().mockResolvedValue({ settings: {} }),
    listSongs: vi.fn().mockResolvedValue({
      songs: [
        {
          id: "song-1",
          title: "C Major Scale",
          artist: "Tester",
          tags: ["demo"],
          arrangement_count: sourceKind === "midi" ? 1 : 0,
          created_at: "2026-11-22T00:00:00Z",
          updated_at: "2026-11-22T00:00:00Z",
        },
      ],
    }),
    getSong: vi.fn().mockResolvedValue({
      song: { id: "song-1", title: "C Major Scale" },
      sources: [{ id: "src-1", kind: sourceKind, original_name: "demo" }],
      transcriptions: [],
      arrangements: sourceKind === "midi" ? [arr] : [],
    }),
    getArrangement: vi.fn().mockResolvedValue({
      arrangement: arr,
      performance: {
        arrangement_id: "arr-1",
        duration_ms: 4000,
        events: [{ at_ms: 0, key_id: "mid_1", mapped_pitch: 60, hold_ms: 40 }],
      },
      report: {
        calibration_status: "unverified",
        stats: {
          emitted_events: 8,
          considered_notes: 8,
          octave_folded: 0,
          semitone_substituted: 0,
          playable_ratio: 1.0,
        },
        quality: {
          overall_score: 92.5,
          melody_preservation: 1.0,
          rhythmic_fidelity: 0.98,
          pitch_contour_preservation: 1.0,
          harmonic_coherence: 0.95,
          missing_note_penalty: 0.0,
          dense_key_conflict_penalty: 0.0,
          large_leap_penalty: 0.0,
          warnings: [],
        },
      },
    }),
    deleteArrangement: vi.fn().mockResolvedValue({
      deleted: true,
      arrangement_id: "arr-1",
      song_id: "song-1",
      queue: { items: [], index: 0, mode: "dry-run", realtime: false },
    }),
    playbackStatus: vi.fn().mockResolvedValue({
      state: "idle",
      session_id: null,
      arrangement_id: null,
      mode: null,
      sends_os_input: false,
      keys_still_pressed: [],
      last_result: null,
    }),
    preparePlayback: vi.fn().mockResolvedValue({
      prepare_token: "tok-1",
      expires_in_s: 60,
      arrangement_id: "arr-1",
      mode: "dry-run",
      realtime: true,
      event_count: 8,
      duration_ms: 4000,
      calibration_status: "unverified",
      sends_os_input: false,
      risk_notice: "Dry-run mode",
    }),
    startPlayback: vi.fn().mockResolvedValue({ session_id: "sess-1", status: "running" }),
    pausePlayback: vi.fn().mockResolvedValue({
      state: "paused",
      session_id: "sess-1",
      arrangement_id: "arr-1",
      mode: "dry-run",
      sends_os_input: false,
      keys_still_pressed: [],
      last_result: null,
    }),
    resumePlayback: vi.fn().mockResolvedValue({
      state: "running",
      session_id: "sess-1",
      arrangement_id: "arr-1",
      mode: "dry-run",
      sends_os_input: false,
      keys_still_pressed: [],
      last_result: null,
    }),
    stopPlayback: vi.fn().mockResolvedValue({
      state: "stopped",
      session_id: "sess-1",
      arrangement_id: "arr-1",
      mode: "dry-run",
      sends_os_input: false,
      keys_still_pressed: [],
      last_result: null,
    }),
    listCalibrationPatterns: vi.fn().mockResolvedValue({
      patterns: [
        {
          id: "same_key_retrigger",
          code: "B",
          display_name: "B · 同键重复触发（30–150 ms 阶梯）",
          description: "对单键 mid_1 连击",
          default_duration_s: null,
        },
        {
          id: "rapid_arpeggio",
          code: "D",
          display_name: "D · 快速上下行琶音（10–50 ms 音序）",
          description: "验证快速琶音顺序",
          default_duration_s: null,
        },
      ],
    }),
    runDryCalibration: vi.fn().mockResolvedValue({
      tier: "realtime_scheduler",
      verifies_game_audio: false,
      notice: "Dry-Run 基准仅验证事件时间轴",
      pattern: {
        id: "same_key_retrigger",
        code: "B",
        display_name: "B · 同键重复触发（30–150 ms 阶梯）",
        description: "对单键 mid_1 连击",
        default_duration_s: null,
      },
      instrument_profile_id: "genshin.windsong_lyre.v1",
      timing_profile: { min_key_release_gap_ms: 20 },
      expected_events: 18,
      expected_duration_ms: 1800,
      actual_elapsed_ms: 1801.2,
      drift_ms: 1.2,
      cpu_pct: 0.4,
      result: {
        state: "completed",
        actions_sent: 36,
        actions_total: 36,
        elapsed_ms: 1801.2,
        stop_reason: null,
        error: null,
        p50_lateness_ms: 0.08,
        p95_lateness_ms: 0.31,
        max_lateness_ms: 0.45,
        retrigger_conflicts_count: 0,
      },
      log_verification: {
        down_count: 18,
        first_12_keys: ["mid_1"],
        overlapping_key_downs: 0,
        min_observed_release_gap_ms: 20.0,
      },
      segments: [],
    }),
    prepareCalibration: vi.fn().mockResolvedValue({
      prepare_token: "cal-tok-1",
      expires_in_s: 60,
      arrangement_id: "calibration:same_key_retrigger",
      mode: "dry-run",
      realtime: true,
      event_count: 18,
      duration_ms: 1800,
      calibration_status: "unverified",
      sends_os_input: false,
      risk_notice: "Calibration dry-run",
      pattern: {
        id: "same_key_retrigger",
        code: "B",
        display_name: "B · 同键重复触发（30–150 ms 阶梯）",
        description: "对单键 mid_1 连击",
        default_duration_s: null,
      },
      segments: [],
    }),
    analyzeCalibrationWav: vi.fn().mockResolvedValue({
      measurement_basis: "recorded_audio_onset_analysis",
      pattern_id: "same_key_retrigger",
      sample_rate: 44100,
      duration_ms: 2200,
      estimated_offset_ms: 58.5,
      expected_onset_clusters: 18,
      detected_onsets_total: 15,
      matched_onsets: 15,
      detection_rate: 0.8333,
      mean_abs_error_ms: 6.2,
      max_abs_error_ms: 14.0,
      segments: [],
      suggested_timing: { min_same_key_interval_ms: 60, provisional: false },
    }),
    submitTranscribeJob: vi.fn().mockResolvedValue({
      job: {
        id: "job-1",
        song_id: "song-1",
        engine_id: "builtin-mono",
        status: "running",
        stage: "analyzing",
        progress: 0.4,
        transcription: null,
        error: null,
      },
    }),
    getJob: vi.fn().mockResolvedValue({
      job: {
        id: "job-1",
        song_id: "song-1",
        engine_id: "builtin-mono",
        status: "running",
        stage: "analyzing",
        progress: 0.5,
        transcription: null,
        error: null,
      },
    }),
    listJobs: vi.fn().mockResolvedValue({ jobs: [] }),
    cancelJob: vi.fn().mockResolvedValue({
      job: {
        id: "job-1",
        song_id: "song-1",
        engine_id: "builtin-mono",
        status: "cancelled",
        stage: "cancelled",
        progress: 0.4,
        transcription: null,
        error: null,
      },
    }),
    importMedia: vi.fn(),
    arrangeSong: vi.fn(),
    arrangeAB: vi.fn().mockResolvedValue({
      arrangement_a: arr,
      arrangement_b: arrB,
      comparison: {
        id_a: "arr-1",
        id_b: "arr-2",
        winner: "arr-2",
        score_a: 92.5,
        score_b: 95.0,
        score_delta: -2.5,
        metrics: {},
        summary: "arr-2 scores higher (95.0 vs 92.5)",
      },
    }),
    editArrangement: vi.fn().mockResolvedValue({
      arrangement: { ...arr, id: "arr-edited", parent_id: "arr-1", label: "Piano Roll 编辑版" },
    }),
    setFavorite: vi.fn().mockResolvedValue({
      arrangement: { ...arr, is_favorite: true },
    }),
    setVote: vi.fn().mockResolvedValue({
      arrangement: { ...arr, user_vote: 1 },
    }),
    compareArrangements: vi.fn(),
    runAgent: vi.fn().mockResolvedValue({
      status: "completed",
      provider: "rule-based-offline",
      intent: { action: "arrange" },
      steps: [{ tool: "arrange.run", status: "ok", detail: "已生成改编", output: {} }],
      candidates: [],
      selected_song: { id: "song-1", title: "C Major Scale" },
      selected_arrangement: arr,
      comparison: null,
      preview_url: "/v1/arrangements/arr-1/preview.wav",
      requires_confirmation: false,
      confirmation_prompt: null,
      message: "Agent 已完成《C Major Scale》编曲",
    }),
    fetchPreviewAudioUrl: vi.fn().mockResolvedValue("blob:http://127.0.0.1/preview"),
    downloadExport: vi.fn().mockResolvedValue(new Blob(["test"])),
    exportLyrapack: vi.fn().mockResolvedValue(new Blob(["PK"])),
    importLyrapack: vi.fn().mockResolvedValue({
      song: { id: "song-pack", title: "Packed Song" },
      arrangement: arr,
    }),
    downloadBackupZip: vi.fn().mockResolvedValue(new Blob(["PK"])),
    restoreBackupZip: vi.fn().mockResolvedValue({
      restored: { restored_files: 4, song_count: 1, schema_version: 3 },
    }),
  } as unknown as LyraForgeApi;
}

async function clickNav(wrapper: ReturnType<typeof mount>, label: string): Promise<void> {
  const navBtn = wrapper
    .findAll("nav button.rail-item")
    .find((b) => b.text().includes(label));
  expect(navBtn, `nav item ${label} should exist`).toBeDefined();
  await navBtn!.trigger("click");
  await flushPromises();
}

describe("App", () => {
  it("loads macOS DryRun badge, disables windows option, enforces 2-step playback, and renders MCP setup", async () => {
    window.history.replaceState(null, "", "/");
    const stub = makeStubApi("midi");
    const wrapper = mount(App, { props: { client: stub } });
    await flushPromises();

    expect(wrapper.text()).toContain("macOS DryRun 模拟模式");
    expect(wrapper.text()).toContain("C Major Scale");

    await clickNav(wrapper, "试听与演奏");

    const winOpt = wrapper.find('option[value="windows"]');
    expect(winOpt.attributes("disabled")).toBeDefined();

    const prepBtn = wrapper.findAll("button").find((b) => b.text().includes("1. 准备演奏"))!;
    const startBtn = wrapper.findAll("button").find((b) => b.text().includes("2. 确认授权开始"))!;
    expect(startBtn.attributes("disabled")).toBeDefined();

    await prepBtn.trigger("click");
    await flushPromises();
    expect(stub.preparePlayback).toHaveBeenCalledTimes(1);
    expect(startBtn.attributes("disabled")).toBeUndefined();

    await startBtn.trigger("click");
    await flushPromises();
    expect(stub.startPlayback).toHaveBeenCalledWith("tok-1", 10);

    // Simulate running -> pause -> resume transitions via unified transport
    vi.mocked(stub.playbackStatus).mockResolvedValueOnce({
      state: "running",
      session_id: "sess-1",
      arrangement_id: "arr-1",
      mode: "dry-run",
      sends_os_input: false,
      keys_still_pressed: [],
      last_result: null,
    });
    const prepBtn2 = wrapper.findAll("button").find((b) => b.text().includes("1. 准备演奏"))!;
    await prepBtn2.trigger("click");
    await flushPromises();
    const startBtn2 = wrapper.findAll("button").find((b) => b.text().includes("2. 确认授权开始"))!;
    await startBtn2.trigger("click");
    await flushPromises();

    const pauseBtn = wrapper.findAll("button").find((b) => b.text().includes("暂停演奏"))!;
    await pauseBtn.trigger("click");
    await flushPromises();
    expect(stub.pausePlayback).toHaveBeenCalledTimes(1);

    const resumeBtn = wrapper.findAll("button").find((b) => b.text().includes("继续演奏"))!;
    await resumeBtn.trigger("click");
    await flushPromises();
    expect(stub.resumePlayback).toHaveBeenCalledTimes(1);

    // Persistent WAV preview stays loaded across tab changes
    const previewQuickBtn = wrapper.findAll("button").find((b) => b.text().includes("快速试听"))!;
    await previewQuickBtn.trigger("click");
    await flushPromises();
    expect(wrapper.find('footer audio[src="blob:http://127.0.0.1/preview"]').exists()).toBe(true);

    const stopBtn = wrapper.findAll("button").find((b) => b.text().includes("紧急停止"))!;
    await stopBtn.trigger("click");
    await flushPromises();
    expect(stub.stopPlayback).toHaveBeenCalledTimes(1);

    await clickNav(wrapper, "设置");
    expect(wrapper.find('footer audio[src="blob:http://127.0.0.1/preview"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("uv");
    expect(wrapper.text()).toContain("lyraforge");
    const codexTab = wrapper.findAll('[role="tab"]').find((b) => b.text().includes("Codex"))!;
    await codexTab.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("[mcp_servers.lyraforge]");

    const saveBtn = wrapper.findAll("button").find((b) => b.text().includes("保存设置"))!;
    await saveBtn.trigger("click");
    await flushPromises();
    expect(stub.saveSetting).toHaveBeenCalledWith("default_style", "balanced");
  });

  it("shows audio transcription controls and supports starting and cancelling a job", async () => {
    window.history.replaceState(null, "", "/");
    const stub = makeStubApi("audio");
    const wrapper = mount(App, { props: { client: stub } });
    await flushPromises();

    await clickNav(wrapper, "音频转谱");

    expect(wrapper.text()).toContain("音频转 MIDI 转录");
    const bpOpt = wrapper.find('option[value="basic-pitch"]');
    expect(bpOpt.attributes("disabled")).toBeDefined();

    const startTrBtn = wrapper.findAll("button").find((b) => b.text().includes("开始音频转谱"))!;
    await startTrBtn.trigger("click");
    await flushPromises();
    expect(stub.submitTranscribeJob).toHaveBeenCalledWith("song-1", "builtin-mono");

    const cancelTrBtn = wrapper.findAll("button").find((b) => b.text().includes("取消转谱"))!;
    await cancelTrBtn.trigger("click");
    await flushPromises();
    expect(stub.cancelJob).toHaveBeenCalledWith("job-1");
  });

  it("supports M3/M4/M5 flows across Studio, Agent, Library, and Playback views", async () => {
    window.history.replaceState(null, "", "/");
    const stub = makeStubApi("midi");
    const wrapper = mount(App, { props: { client: stub } });
    await flushPromises();

    // Home IME-safe search jump: composition Enter must NOT submit
    const homeInput = wrapper.find("#home-quick-search");
    await homeInput.setValue("千本");
    await homeInput.trigger("keydown", { key: "Enter", isComposing: true, keyCode: 229 });
    await flushPromises();
    expect(wrapper.find("h1").text()).toContain("LyraForge 编曲与演奏工作台");

    // Non-composing Enter jumps to library and queries backend
    await homeInput.trigger("keydown", { key: "Enter", isComposing: false, keyCode: 13 });
    await flushPromises();
    expect(wrapper.find("h1").text()).toContain("本地曲库");
    expect(stub.listSongs).toHaveBeenCalledWith("千本");

    // Studio view: metrics, profile change, favorite, vote, A/B arrange, Piano Roll save
    await clickNav(wrapper, "编曲工作室");
    expect(wrapper.text()).toContain("92.5 / 100");
    expect(wrapper.text()).toContain("MIDI Piano Roll 可视化编辑器");

    await wrapper.find("#profile-select").setValue("genshin.floral_zither.v1");
    await flushPromises();
    expect(stub.getProfile).toHaveBeenCalledWith("genshin.floral_zither.v1");

    const favBtn = wrapper.findAll("button").find((b) => b.text().includes("收藏"))!;
    await favBtn.trigger("click");
    await flushPromises();
    expect(stub.setFavorite).toHaveBeenCalledWith("arr-1", true);

    const voteBtn = wrapper.findAll("button").find((b) => b.text().includes("推荐"))!;
    await voteBtn.trigger("click");
    await flushPromises();
    expect(stub.setVote).toHaveBeenCalledWith("arr-1", 1);

    const abBtn = wrapper.findAll("button").find((b) => b.text().includes("生成 A/B 对比版本"))!;
    await abBtn.trigger("click");
    await flushPromises();
    expect(stub.arrangeAB).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("A/B 编曲对比结果");

    const prSaveBtn = wrapper.findAll("button").find((b) => b.text().includes("保存为新版本"))!;
    await prSaveBtn.trigger("click");
    await flushPromises();
    expect(stub.editArrangement).toHaveBeenCalledTimes(1);

    // Transcribe view: Agent natural language automation
    await clickNav(wrapper, "音频转谱");
    await wrapper.find("#agent-prompt").setValue("转成风物之诗琴主旋律并优化");
    const agentBtn = wrapper.findAll("button").find((b) => b.text().includes("执行"))!;
    await agentBtn.trigger("click");
    await flushPromises();
    expect(stub.runAgent).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("Agent 已完成《C Major Scale》编曲");
    expect(wrapper.text()).toContain("arrange.run");

    // Library & Playback M5 flows: filter, backup, rights-gated .lyrapack export
    const originalCreateObjectURL = globalThis.URL.createObjectURL;
    const originalRevokeObjectURL = globalThis.URL.revokeObjectURL;
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    globalThis.URL.createObjectURL = vi.fn(() => "blob:mock");
    globalThis.URL.revokeObjectURL = vi.fn();
    try {
      await clickNav(wrapper, "本地曲库");
      await wrapper.find("#library-search").setValue("");
      await wrapper.find("#library-tag-filter").setValue("demo");
      const searchBtn = wrapper.findAll("button").find((b) => b.text().trim() === "搜索")!;
      await searchBtn.trigger("click");
      await flushPromises();
      expect(stub.listSongs).toHaveBeenCalledWith("", { tag: "demo", favoritesOnly: false });

      const backupBtn = wrapper.findAll("button").find((b) => b.text().includes("备份曲库"))!;
      await backupBtn.trigger("click");
      await flushPromises();
      expect(stub.downloadBackupZip).toHaveBeenCalledTimes(1);

      await clickNav(wrapper, "试听与演奏");
      const packExportBtn = wrapper.findAll("button").find((b) => b.text().includes("导出分享包"))!;
      await packExportBtn.trigger("click");
      await flushPromises();
      expect(stub.exportLyrapack).not.toHaveBeenCalled();

      const rightsBox = wrapper
        .findAll("label")
        .find((l) => l.text().includes("分享授权"))!
        .find("input[type='checkbox']");
      await rightsBox.setValue(true);
      await packExportBtn.trigger("click");
      await flushPromises();
      expect(stub.exportLyrapack).toHaveBeenCalledWith("arr-1", true);
    } finally {
      clickSpy.mockRestore();
      globalThis.URL.createObjectURL = originalCreateObjectURL;
      globalThis.URL.revokeObjectURL = originalRevokeObjectURL;
    }
  });

  it("keeps transcription status per-song, syncs song selection across views, and lets topbar switch songs under filters", async () => {
    vi.useFakeTimers();
    try {
      window.history.replaceState(null, "", "/");
      const songA = {
        id: "song-a",
        title: "Song A",
        artist: "Artist A",
        tags: ["alpha"],
        arrangement_count: 0,
        created_at: "2026-11-24T00:00:00Z",
        updated_at: "2026-11-24T00:00:00Z",
      };
      const songB = {
        id: "song-b",
        title: "Song B",
        artist: "Artist B",
        tags: ["beta"],
        arrangement_count: 0,
        created_at: "2026-11-24T00:00:01Z",
        updated_at: "2026-11-24T00:00:01Z",
      };
      let songATranscribed = false;
      const stub = makeStubApi("audio");
      vi.mocked(stub.listSongs).mockImplementation(async (query = "") => {
        const all = [songA, songB];
        if (!query.trim()) return { songs: all };
        const q = query.trim().toLowerCase();
        return { songs: all.filter((s) => s.title.toLowerCase().includes(q)) };
      });
      vi.mocked(stub.getSong).mockImplementation(async (songId: string) => {
        if (songId === "song-a") {
          return {
            song: songA,
            sources: [{ id: "src-a", kind: "audio", original_name: "a.mp3" }],
            transcriptions: songATranscribed
              ? [
                  {
                    id: "tr-a",
                    engine: "builtin-mono",
                    engine_version: "1.0",
                    status: "completed",
                    note_count: 24,
                    created_at: "2026-11-24T00:01:00Z",
                  },
                ]
              : [],
            arrangements: [],
          };
        }
        return {
          song: songB,
          sources: [{ id: "src-b", kind: "audio", original_name: "b.mp3" }],
          transcriptions: [],
          arrangements: [],
        };
      });
      vi.mocked(stub.submitTranscribeJob).mockResolvedValueOnce({
        job: {
          id: "job-a",
          song_id: "song-a",
          engine_id: "builtin-mono",
          status: "running",
          stage: "analyzing",
          progress: 0.4,
          transcription: null,
          error: null,
        },
      });
      vi.mocked(stub.getJob).mockImplementation(async () => {
        songATranscribed = true;
        return {
          job: {
            id: "job-a",
            song_id: "song-a",
            engine_id: "builtin-mono",
            status: "completed",
            stage: "completed",
            progress: 1.0,
            transcription: {
              id: "tr-a",
              engine: "builtin-mono",
              engine_version: "1.0",
              status: "completed",
              note_count: 24,
              created_at: "2026-11-24T00:01:00Z",
            },
            error: null,
          },
        };
      });

      const wrapper = mount(App, { props: { client: stub } });
      await flushPromises();

      // Navigate to Transcribe and start job on Song A
      await clickNav(wrapper, "音频转谱");
      const startBtn = wrapper.findAll("button").find((b) => b.text().includes("开始音频转谱"))!;
      await startBtn.trigger("click");
      await flushPromises();
      expect(stub.submitTranscribeJob).toHaveBeenCalledWith("song-a", "builtin-mono");
      expect(wrapper.find(".topbar-job-pill").text()).toContain("转谱中：Song A 40%");

      // Switch to Song B via #transcribe-song-select while Song A is running
      await wrapper.find("#transcribe-song-select").setValue("song-b");
      await flushPromises();

      // Topbar must sync to Song B, and TranscribeView stepper must NOT show Song A's running state
      expect((wrapper.find("#topbar-song-select").element as HTMLSelectElement).value).toBe("song-b");
      const steps = wrapper.findAll(".pipeline-stepper .pipe-step");
      expect(steps[0].classes()).toContain("done");
      expect(steps[1].classes()).not.toContain("current");
      expect(steps[1].classes()).not.toContain("done");
      expect(wrapper.text()).toContain("当前选中曲目：Song B");
      expect(wrapper.text()).toContain("其他曲目的转谱任务 (1)");

      // Navigating to Studio on untranscribed Song B guides back to Transcribe
      await clickNav(wrapper, "编曲工作室");
      expect(wrapper.text()).toContain("当前曲目「Song B」尚未完成音频转谱");
      const goTrBtn = wrapper.findAll("button").find((b) => b.text().includes("前往音频转谱"))!;
      await goTrBtn.trigger("click");
      await flushPromises();
      expect(wrapper.find("h1").text()).toContain("音频转谱");

      // Poll completes job-a in the background while user remains on Song B
      await vi.advanceTimersByTimeAsync(450);
      await flushPromises();

      // Active song stays Song B (no hijack), while Song A offers "去编曲"
      expect((wrapper.find("#topbar-song-select").element as HTMLSelectElement).value).toBe("song-b");
      const goStudioOtherBtn = wrapper.findAll("button").find((b) => b.text().trim() === "去编曲")!;
      await goStudioOtherBtn.trigger("click");
      await flushPromises();

      expect(wrapper.find("h1").text()).toContain("编曲工作室");
      expect((wrapper.find("#topbar-song-select").element as HTMLSelectElement).value).toBe("song-a");
      expect(wrapper.text()).toContain("当前曲目「Song A」尚无改编版本");

      // Even under a Library search filter narrowing `songs` to Song A, topbar still switches to Song B
      await clickNav(wrapper, "本地曲库");
      await wrapper.find("#library-search").setValue("Song A");
      const libSearchBtn = wrapper.findAll("button").find((b) => b.text().trim() === "搜索")!;
      await libSearchBtn.trigger("click");
      await flushPromises();

      await wrapper.find("#topbar-song-select").setValue("song-b");
      await flushPromises();
      expect((wrapper.find("#topbar-song-select").element as HTMLSelectElement).value).toBe("song-b");
    } finally {
      vi.useRealTimers();
    }
  });

  it("supports selectable vocal-split pipeline, transcription switching, arranger strategy, and track selection in Studio", async () => {
    vi.useFakeTimers();
    try {
      window.history.replaceState(null, "", "/");
      const stub = makeStubApi("audio");
      const trDirect: TranscriptionRecord = {
        id: "tr-direct",
        engine: "builtin-mono",
        engine_version: "1.0",
        pipeline_id: "direct",
        tracks: [],
        status: "completed",
        note_count: 18,
        created_at: "2026-11-24T00:00:00Z",
      };
      const vocalTracks = [
        {
          index: 1,
          name: "Vocal Lead",
          note_count: 42,
          channels: [0],
          is_percussion: false,
          min_pitch: 60,
          max_pitch: 76,
        },
        {
          index: 2,
          name: "Accompaniment",
          note_count: 64,
          channels: [1],
          is_percussion: false,
          min_pitch: 48,
          max_pitch: 72,
        },
      ];
      const trFull: TranscriptionRecord = {
        id: "tr-full",
        engine: "vocal:basic-pitch+accomp:dettato",
        engine_version: "pipeline:vocal_split_full",
        pipeline_id: "vocal_split_full",
        tracks: vocalTracks,
        status: "completed",
        note_count: 106,
        created_at: "2026-11-24T01:00:00Z",
      };

      let transcriptions: TranscriptionRecord[] = [trDirect];
      vi.mocked(stub.listTranscribers).mockResolvedValue({
        transcribers: [
          {
            id: "builtin-mono",
            display_name: "内置单音旋律识别 (YIN)",
            available: true,
            license: "Self-authored",
            scope_note: "适合独奏",
          },
          {
            id: "basic-pitch",
            display_name: "Spotify Basic Pitch",
            available: true,
            license: "Apache-2.0",
            scope_note: "多音识别",
          },
          {
            id: "dettato",
            display_name: "dettato",
            available: true,
            license: "Apache-2.0",
            scope_note: "伴奏识别",
          },
        ],
      });
      vi.mocked(stub.getSong).mockImplementation(async () => ({
        song: {
          id: "song-1",
          title: "Vocal Pop Demo",
          artist: "Tester",
          tags: ["demo"],
          arrangement_count: 0,
          created_at: "2026-11-24T00:00:00Z",
          updated_at: "2026-11-24T00:00:00Z",
        },
        sources: [{ id: "src-1", kind: "audio", original_name: "pop.wav" }],
        transcriptions,
        arrangements: [],
      }));
      vi.mocked(stub.getSongTracks).mockImplementation(async (_songId, trId) => ({
        song_id: "song-1",
        source_kind: "transcription",
        transcription_id: trId ?? trFull.id,
        pipeline_id: "vocal_split_full",
        detected_melody_track: 2,
        tracks: vocalTracks,
      }));
      vi.mocked(stub.submitTranscribeJob).mockResolvedValue({
        job: {
          id: "job-split",
          song_id: "song-1",
          engine_id: "vocal:basic-pitch+accomp:dettato",
          pipeline_id: "vocal_split_full",
          status: "running",
          stage: "separating",
          progress: 0.25,
          transcription: null,
          error: null,
        },
      });
      vi.mocked(stub.getJob).mockImplementation(async () => {
        transcriptions = [trFull, trDirect];
        return {
          job: {
            id: "job-split",
            song_id: "song-1",
            engine_id: "vocal:basic-pitch+accomp:dettato",
            pipeline_id: "vocal_split_full",
            status: "completed",
            stage: "done",
            progress: 1,
            transcription: trFull,
            error: null,
          },
        };
      });
      const newArr: ArrangementRecord = {
        id: "arr-vocal-1",
        song_id: "song-1",
        profile_id: "genshin.windsong_lyre.v1",
        style: "balanced",
        transpose: -2,
        speed: 1.0,
        playable_ratio: 0.96,
        event_count: 88,
        duration_ms: 4000,
        preview_path: null,
        is_favorite: false,
        user_vote: 0,
        score: 94.0,
        label: "vocal_split_full · 主旋律增强 · balanced",
        transcription_id: "tr-full",
        arranger_strategy: "vocal_lead",
        created_at: "2026-11-24T01:05:00Z",
      };
      vi.mocked(stub.arrangeSong).mockResolvedValue({ arrangement: newArr });
      vi.mocked(stub.getArrangement).mockResolvedValue({
        arrangement: newArr,
        performance: {
          arrangement_id: newArr.id,
          duration_ms: 4000,
          events: [],
        },
        report: {
          calibration_status: "experimental",
          quality: {
            overall_score: 94.0,
            melody_preservation: 98.0,
            rhythmic_fidelity: 95.0,
            pitch_contour_preservation: 96.0,
            harmonic_coherence: 92.0,
            missing_note_penalty: 1.0,
            dense_key_conflict_penalty: 0.5,
            large_leap_penalty: 0.5,
            melody_track: 1,
            warnings: [],
          },
          stats: {
            emitted_events: 88,
            considered_notes: 90,
            octave_folded: 4,
            semitone_substituted: 0,
            playable_ratio: 0.96,
          },
        },
      });

      const wrapper = mount(App, { props: { client: stub } });
      await flushPromises();
      await clickNav(wrapper, "音频转谱");

      const pipeSelect = wrapper.find("#transcribe-pipeline-select");
      expect(pipeSelect.exists()).toBe(true);
      await pipeSelect.setValue("vocal_split_full");
      await flushPromises();

      await wrapper.find("#transcribe-vocal-engine").setValue("basic-pitch");
      await wrapper.find("#transcribe-accomp-engine").setValue("dettato");
      await flushPromises();

      const startBtn = wrapper.findAll("button").find((b) => b.text().includes("开始音频转谱"))!;
      await startBtn.trigger("click");
      await flushPromises();

      expect(stub.submitTranscribeJob).toHaveBeenCalledWith("song-1", "builtin-mono", {
        pipelineId: "vocal_split_full",
        vocalEngineId: "basic-pitch",
        accompEngineId: "dettato",
        vocalCleanup: "standard",
        vocalRange: "auto",
      });

      await vi.advanceTimersByTimeAsync(1100);
      await flushPromises();

      const useBtn = wrapper.findAll("button").find((b) => b.text().includes("以此编曲"))!;
      expect(useBtn).toBeDefined();
      await useBtn.trigger("click");
      await flushPromises();

      expect(wrapper.find("h1").text()).toContain("编曲工作室");
      expect(
        (wrapper.find("#studio-transcription-select").element as HTMLSelectElement).value,
      ).toBe("tr-full");
      expect(
        (wrapper.find("#studio-arranger-strategy").element as HTMLSelectElement).value,
      ).toBe("vocal_lead");
      expect(wrapper.text()).toContain("MIDI 分轨与主旋律");
      expect(wrapper.text()).toContain("Vocal Lead");
      expect(wrapper.text()).toContain("Accompaniment");

      // Pin Vocal Lead (track 1) as melody and uncheck Accompaniment (track 2)
      const trackRows = wrapper.findAll("li.track-row");
      expect(trackRows).toHaveLength(2);
      const pinVocalBtn = trackRows[0].find("button");
      await pinVocalBtn.trigger("click");
      const accompCheckbox = trackRows[1].find('input[type="checkbox"]');
      await accompCheckbox.setValue(false);
      await flushPromises();

      const arrangeBtn = wrapper
        .findAll("button")
        .find((b) => b.text().includes("生成改编版本"))!;
      await arrangeBtn.trigger("click");
      await flushPromises();

      expect(stub.arrangeSong).toHaveBeenCalledWith(
        expect.objectContaining({
          song_id: "song-1",
          transcription_id: "tr-full",
          arranger_strategy: "vocal_lead",
          include_tracks: [1],
          melody_track: 1,
        }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("blocks auto vocal_split_full when only builtin-mono is installed, unless explicitly opted in", async () => {
    window.history.replaceState(null, "", "/");
    const stub = makeStubApi("audio");
    vi.mocked(stub.listPipelines).mockResolvedValue({
      pipelines: [
        {
          id: "direct",
          display_name: "经典直转（原流程）",
          description: "直转",
          recommended_for: "独奏",
          stages: ["提取", "识别"],
          required_tools: [],
          available: true,
          missing_tools: [],
          default_engine_id: "builtin-mono",
          default_vocal_engine_id: null,
          default_accomp_engine_id: null,
          default_arranger_strategy: "classic",
          supports_engine_override: true,
        },
        {
          id: "vocal_split_full",
          display_name: "人声分离 · 双轨",
          description: "分轨",
          recommended_for: "流行歌",
          stages: ["Demucs", "人声", "伴奏"],
          required_tools: ["dettato/basic-pitch"],
          available: false,
          missing_tools: ["dettato/basic-pitch"],
          default_engine_id: "builtin-mono",
          default_vocal_engine_id: "builtin-mono",
          default_accomp_engine_id: null,
          resolved_vocal_engine_id: "builtin-mono",
          resolved_accomp_engine_id: null,
          low_resource_available: true,
          warnings: ["未安装多音伴奏引擎"],
          default_arranger_strategy: "vocal_lead",
          supports_engine_override: false,
        },
      ],
    });
    const wrapper = mount(App, { props: { client: stub } });
    await flushPromises();
    await clickNav(wrapper, "音频转谱");

    await wrapper.find("#transcribe-pipeline-select").setValue("vocal_split_full");
    await flushPromises();

    const startBtn = wrapper.findAll("button").find((b) => b.text().includes("开始音频转谱"))!;
    expect((startBtn.element as HTMLButtonElement).disabled).toBe(true);
    expect(wrapper.text()).toContain("未安装多音伴奏引擎");

    // Explicit opt-in to builtin-mono enables submission with explicit monophonic warning
    await wrapper.find("#transcribe-accomp-engine").setValue("builtin-mono");
    await flushPromises();
    expect((startBtn.element as HTMLButtonElement).disabled).toBe(false);
    expect(wrapper.text()).toContain("低资源/显式降级模式");
  });

  it("preserves Studio track selection after arranging, shows drop breakdown, deletes versions with confirmation, and displays dual GPU pills", async () => {
    window.history.replaceState(null, "", "/");
    const stub = makeStubApi("midi");
    const trFullTracks: SongTrackInfo[] = [
      { index: 1, name: "Vocal Lead", is_percussion: false, note_count: 10, channels: [0], min_pitch: 60, max_pitch: 72 },
      { index: 2, name: "Accompaniment", is_percussion: false, note_count: 20, channels: [1], min_pitch: 48, max_pitch: 64 },
    ];
    const trFull: TranscriptionRecord = {
      id: "tr-full",
      pipeline_id: "vocal_split_full",
      engine: "basic-pitch+dettato",
      engine_version: "1.0",
      status: "completed",
      tracks: trFullTracks,
      note_count: 30,
      created_at: "2026-11-24T01:00:00Z",
    };
    const songFull = {
      id: "song-1",
      title: "C Major Scale",
      artist: "Tester",
      tags: ["demo"],
      arrangement_count: 2,
      created_at: "2026-11-22T00:00:00Z",
      updated_at: "2026-11-24T02:00:00Z",
    };
    const arr2 = {
      id: "arr-2",
      song_id: "song-1",
      profile_id: "genshin.windsong_lyre.v1",
      style: "balanced",
      transpose: 0,
      arpeggiate_ms: 0,
      speed: 1.0,
      playable_ratio: 0.95,
      event_count: 8,
      duration_ms: 4000,
      preview_path: null,
      is_favorite: false,
      user_vote: 0,
      score: 94.0,
      label: "仅主旋律编排",
      transcription_id: "tr-full",
      arranger_strategy: "vocal_lead",
      created_at: "2026-11-24T02:00:00Z",
    };
    const arr1 = {
      ...arr2,
      id: "arr-1",
      label: "均衡版本",
    };
    vi.mocked(stub.getSong)
      .mockResolvedValueOnce({
        song: songFull,
        sources: [{ id: "src-1", kind: "midi", original_name: "demo.mid" }],
        transcriptions: [trFull],
        arrangements: [arr2, arr1],
      })
      .mockResolvedValueOnce({
        song: songFull,
        sources: [{ id: "src-1", kind: "midi", original_name: "demo.mid" }],
        transcriptions: [trFull],
        arrangements: [arr2, arr1],
      })
      .mockResolvedValue({
        song: { ...songFull, arrangement_count: 1 },
        sources: [{ id: "src-1", kind: "midi", original_name: "demo.mid" }],
        transcriptions: [trFull],
        arrangements: [arr1],
      });
    vi.mocked(stub.deleteArrangement).mockResolvedValue({
      deleted: true,
      arrangement_id: "arr-2",
      song_id: "song-1",
      queue: { items: [], index: 0, mode: "dry-run", realtime: false },
    });
    vi.mocked(stub.getSongTracks).mockResolvedValue({
      song_id: "song-1",
      source_kind: "midi",
      pipeline_id: "vocal_split_full",
      transcription_id: "tr-full",
      detected_melody_track: 1,
      tracks: trFullTracks,
    });
    vi.mocked(stub.arrangeSong).mockResolvedValue({ arrangement: arr2 });
    vi.mocked(stub.getArrangement).mockResolvedValue({
      arrangement: arr2,
      performance: {
        arrangement_id: "arr-2",
        duration_ms: 4000,
        events: [
          { at_ms: 0, key_id: "mid_1", mapped_pitch: 60, hold_ms: 40, source_track: 1 },
        ],
      },
      report: {
        calibration_status: "verified",
        stats: {
          considered_notes: 10,
          emitted_events: 8,
          octave_folded: 1,
          semitone_substituted: 0,
          playable_ratio: 0.8,
          dropped: {
            duplicate_key: 2,
            repeat_too_fast: 0,
            polyphony_limit: 0,
            semitone_dropped: 0,
            out_of_range: 0,
          },
        },
        quality: {
          overall_score: 94.0,
          melody_preservation: 1.0,
          rhythmic_fidelity: 0.95,
          pitch_contour_preservation: 1.0,
          harmonic_coherence: 0.9,
          missing_note_penalty: 0,
          dense_key_conflict_penalty: 0,
          large_leap_penalty: 0,
          melody_track: 1,
          warnings: [],
        },
      },
    });
    vi.mocked(stub.getGpuStatus).mockResolvedValue({
      nvidia: { present: true, name: "RTX 4070", driver: "560.94" },
      dettato_installed: true,
      dettato_torch: {
        version: "2.5.1+cu121",
        cuda_build: "12.1",
        cuda_available: true,
        device_count: 1,
      },
      demucs_installed: true,
      demucs_torch: {
        version: "2.5.1+cpu",
        cuda_build: null,
        cuda_available: false,
        device_count: 0,
      },
      device: "auto",
      device_env: "LYRAFORGE_DETTATO_DEVICE",
    });

    const wrapper = mount(App, { props: { client: stub } });
    await flushPromises();
    await clickNav(wrapper, "编曲工作室");
    await flushPromises();

    // Verify colored track dots & drop reason breakdown render
    expect(wrapper.find(".track-dot.track-c-0").exists()).toBe(true);
    expect(wrapper.text()).toContain("同键去重 2");

    // Uncheck track 2 & pin track 1, then arrange -> selection must stay intact!
    const trackRows = wrapper.findAll("li.track-row");
    await trackRows[0].find("button").trigger("click");
    const accompCheck = trackRows[1].find('input[type="checkbox"]');
    await accompCheck.setValue(false);
    await flushPromises();

    const arrangeBtn = wrapper.findAll("button").find((b) => b.text().includes("生成改编版本"))!;
    await arrangeBtn.trigger("click");
    await flushPromises();

    expect((wrapper.findAll("li.track-row")[1].find('input[type="checkbox"]').element as HTMLInputElement).checked).toBe(false);
    expect(wrapper.findAll("li.track-row")[0].find("button").text()).toContain("主旋律");

    // Two-step delete in Studio
    const studioDelBtn = wrapper.findAll("button").find((b) => b.text().includes("删除版本"))!;
    await studioDelBtn.trigger("click");
    expect(stub.deleteArrangement).not.toHaveBeenCalled();
    const confirmStudioDel = wrapper.findAll("button").find((b) => b.text().trim() === "确认删除")!;
    await confirmStudioDel.trigger("click");
    await flushPromises();
    expect(stub.deleteArrangement).toHaveBeenCalledWith("arr-2");

    // Two-step delete in Library
    await clickNav(wrapper, "本地曲库");
    await flushPromises();
    const libDelBtn = wrapper.find('button[aria-label="删除编曲版本"]');
    await libDelBtn.trigger("click");
    const confirmLibDel = wrapper.findAll("button").find((b) => b.text().trim() === "确认删除")!;
    await confirmLibDel.trigger("click");
    await flushPromises();
    expect(stub.deleteArrangement).toHaveBeenCalledWith("arr-1");

    // Dual GPU pills in Settings
    await clickNav(wrapper, "设置");
    await flushPromises();
    expect(wrapper.text()).toContain("dettato: CUDA 可用");
    expect(wrapper.text()).toContain("Demucs: CPU 推理");
  });

  it("wires timing_mode in Studio, scheduler timing options & diagnostics in Playback, and Benchmark A-G calibration", async () => {
    const stub = makeStubApi("midi");
    vi.mocked(stub.getArrangement).mockResolvedValue({
      arrangement: {
        id: "arr-1",
        song_id: "song-1",
        profile_id: "genshin.windsong_lyre.v1",
        style: "balanced",
        speed: 1.0,
        transpose: 0,
        arranger_strategy: "classic",
        playable_ratio: 1.0,
        event_count: 8,
        duration_ms: 4000,
        preview_path: null,
        is_favorite: false,
        user_vote: 0,
        score: 94.0,
        label: "均衡版",
        created_at: "2026-11-24T00:00:00Z",
      },
      performance: {
        arrangement_id: "arr-1",
        duration_ms: 4000,
        events: [{ at_ms: 0, key_id: "mid_1", mapped_pitch: 60, hold_ms: 40 }],
      },
      report: {
        calibration_status: "unverified",
        stats: {
          emitted_events: 8,
          considered_notes: 8,
          octave_folded: 0,
          semitone_substituted: 0,
          playable_ratio: 1.0,
          timing_mode: "adapted",
          timing_adjustments: {
            arpeggiated_events: 3,
            melody_retrigger_replacements: 1,
            hold_shortened_for_retrigger: 2,
          },
        },
        quality: {
          overall_score: 94.0,
          melody_preservation: 1.0,
          rhythmic_fidelity: 0.98,
          pitch_contour_preservation: 1.0,
          harmonic_coherence: 0.95,
          missing_note_penalty: 0,
          dense_key_conflict_penalty: 0,
          large_leap_penalty: 0,
          warnings: [],
        },
      },
    });
    vi.mocked(stub.playbackStatus).mockResolvedValue({
      state: "completed",
      session_id: "sess-1",
      arrangement_id: "arr-1",
      mode: "dry-run",
      sends_os_input: false,
      keys_still_pressed: [],
      last_result: {
        state: "completed",
        actions_sent: 16,
        actions_total: 16,
        elapsed_ms: 4001.0,
        stop_reason: null,
        error: null,
        p50_lateness_ms: 0.12,
        p95_lateness_ms: 0.42,
        max_lateness_ms: 0.78,
        late_events_count: 1,
        clock_shifts_count: 1,
        retrigger_conflicts_count: 2,
      },
    });

    const wrapper = mount(App, { props: { client: stub } });
    await flushPromises();
    await clickNav(wrapper, "编曲工作室");
    await flushPromises();

    // Studio timing adjustments rendered and timing_mode selector forwarded
    expect(wrapper.text()).toContain("和弦自动琶音 3");
    expect(wrapper.text()).toContain("同键让位主旋律 1");
    expect(wrapper.text()).toContain("释放间隙缩短保持 2");

    await wrapper.find("#studio-timing-mode").setValue("strict_fidelity");
    await flushPromises();
    const arrangeBtn = wrapper.findAll("button").find((b) => b.text().includes("生成改编版本"))!;
    await arrangeBtn.trigger("click");
    await flushPromises();
    expect(stub.arrangeSong).toHaveBeenCalledWith(
      expect.objectContaining({ timing_mode: "strict_fidelity" }),
    );

    // Playback timing telemetry, overrides & Benchmark A-G calibration
    await clickNav(wrapper, "试听与演奏");
    await flushPromises();
    expect(wrapper.text()).toContain("0.12 / 0.42 / 0.78 ms");
    expect(wrapper.text()).toContain("同键冲突修复: 2");

    await wrapper.find("#playback-late-policy").setValue("drop_late");
    await wrapper.find("#playback-release-gap").setValue("25");
    await wrapper.find("#playback-key-hold").setValue("35");
    const prepBtn = wrapper.findAll("button").find((b) => b.text().includes("1. 准备演奏"))!;
    await prepBtn.trigger("click");
    await flushPromises();
    expect(stub.preparePlayback).toHaveBeenCalledWith(
      expect.objectContaining({
        late_event_policy: "drop_late",
        min_key_release_gap_ms: 25,
        key_hold_ms: 35,
      }),
    );

    await wrapper.find("#calibration-pattern-select").setValue("rapid_arpeggio");
    const runCalBtn = wrapper.findAll("button").find((b) => b.text().includes("运行调度基准"))!;
    await runCalBtn.trigger("click");
    await flushPromises();
    expect(stub.runDryCalibration).toHaveBeenCalledWith(
      expect.objectContaining({ pattern_id: "rapid_arpeggio" }),
    );
    expect(wrapper.text()).toContain("realtime_scheduler");
    expect(wrapper.text()).toContain("重叠按键 0");

    const prepCalBtn = wrapper.findAll("button").find((b) => b.text().includes("准备实机校准序列"))!;
    await prepCalBtn.trigger("click");
    await flushPromises();
    expect(stub.prepareCalibration).toHaveBeenCalledWith(
      expect.objectContaining({ pattern_id: "rapid_arpeggio" }),
    );
    const startCalBtn = wrapper.findAll("button").find((b) => b.text().includes("2. 确认授权开始"))!;
    expect(startCalBtn.attributes("disabled")).toBeUndefined();

    const fileInput = wrapper.find("#calibration-wav-file").element as HTMLInputElement;
    const wavFile = new File([new Uint8Array(64)], "cal.wav", { type: "audio/wav" });
    Object.defineProperty(fileInput, "files", { value: [wavFile], configurable: true });
    await wrapper.find("#calibration-wav-file").trigger("change");
    await flushPromises();
    expect(stub.analyzeCalibrationWav).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("15 / 18");
    expect(wrapper.text()).toContain("58.5 ms");
  });

  it("supports vocal_dynamic controls, dynamics adjustment badges, and fixed-velocity preview toggle", async () => {
    const stub = makeStubApi("midi");
    const dynArr = {
      id: "arr-dyn",
      song_id: "song-1",
      profile_id: "genshin.windsong_lyre.v1",
      style: "balanced",
      speed: 1.0,
      transpose: 0,
      arranger_strategy: "vocal_dynamic",
      playable_ratio: 0.9,
      event_count: 12,
      duration_ms: 4000,
      preview_path: null,
      is_favorite: false,
      user_vote: 0,
      score: 91.0,
      label: "强弱动态",
      created_at: "2026-11-25T00:00:00Z",
    };
    vi.mocked(stub.listArrangers).mockResolvedValue({
      strategies: [
        { id: "classic", display_name: "经典基线", description: "原算法", recommended_for: "纯器乐" },
        { id: "vocal_lead", display_name: "主旋律优先", description: "让路", recommended_for: "人声" },
        { id: "vocal_dynamic", display_name: "主旋律强弱动态", description: "分句护航", recommended_for: "分轨人声" },
      ],
    });
    vi.mocked(stub.arrangeSong).mockResolvedValue({ arrangement: dynArr });
    vi.mocked(stub.getArrangement).mockResolvedValue({
      arrangement: dynArr,
      performance: {
        arrangement_id: "arr-dyn",
        duration_ms: 4000,
        events: [{ at_ms: 0, key_id: "mid_1", mapped_pitch: 60, hold_ms: 40, source_track: 0 }],
      },
      report: {
        calibration_status: "verified",
        stats: {
          considered_notes: 20,
          emitted_events: 12,
          octave_folded: 2,
          semitone_substituted: 0,
          playable_ratio: 0.9,
          dropped: { accomp_thinned: 5 },
          dynamics_adjustments: {
            phrases_shifted_up: 1,
            cross_stem_aligned: 3,
            accomp_thinned: 5,
          },
        },
      },
    });
    vi.mocked(stub.getSong).mockResolvedValue({
      song: {
        id: "song-1",
        title: "C Major Scale",
        artist: "Tester",
        tags: [],
        arrangement_count: 1,
        created_at: "2026-11-25T00:00:00Z",
        updated_at: "2026-11-25T00:00:00Z",
      },
      sources: [{ id: "src-1", kind: "midi", original_name: "scale.mid" }],
      transcriptions: [],
      arrangements: [dynArr],
    });

    const wrapper = mount(App, { props: { client: stub } });
    await flushPromises();
    await clickNav(wrapper, "编曲工作室");
    await flushPromises();

    // Renders dynamics drop reason & adjustment pills
    expect(wrapper.text()).toContain("伴奏节奏让路 5");
    expect(wrapper.text()).toContain("低音句抬升八度 1");
    expect(wrapper.text()).toContain("跨轨微对齐 3");

    // Select vocal_dynamic & dynamic parameter overrides
    await wrapper.find("#studio-arranger-strategy").setValue("vocal_dynamic");
    await wrapper.find("#studio-accomp-density").setValue("minimal");
    await wrapper.find("#studio-phrase-octave").setValue("centered");
    await wrapper.find("#studio-cross-align").setValue("30");
    const arrangeBtn = wrapper.findAll("button").find((b) => b.text().includes("生成改编版本"))!;
    await arrangeBtn.trigger("click");
    await flushPromises();
    expect(stub.arrangeSong).toHaveBeenCalledWith(
      expect.objectContaining({
        arranger_strategy: "vocal_dynamic",
        accomp_density: "minimal",
        phrase_octave_mode: "centered",
        cross_stem_align_ms: 30,
      }),
    );

    // Default fixed-velocity preview toggle is ON (true), clicking switches to false
    const quickPreviewBtn = wrapper.findAll("button").find((b) => b.text().includes("快速试听"))!;
    await quickPreviewBtn.trigger("click");
    await flushPromises();
    expect(stub.fetchPreviewAudioUrl).toHaveBeenLastCalledWith("arr-dyn", true);

    await wrapper.find("#transport-fixed-vel-toggle").trigger("click");
    const refreshPreviewBtn = wrapper.findAll("button").find((b) => b.text().includes("刷新试听"))!;
    await refreshPreviewBtn.trigger("click");
    await flushPromises();
    expect(stub.fetchPreviewAudioUrl).toHaveBeenLastCalledWith("arr-dyn", false);

    // Changing Piano Roll timbre selector forwards explicit timbre to offline WAV preview
    await wrapper.find("#pr-timbre-select").setValue("piano");
    await refreshPreviewBtn.trigger("click");
    await flushPromises();
    expect(stub.fetchPreviewAudioUrl).toHaveBeenLastCalledWith("arr-dyn", false, "piano");
  });

  it("defaults to genshin.harmonic_keys.v1 when offered first by backend", async () => {
    const stub = makeStubApi("midi");
    vi.mocked(stub.listSongs).mockResolvedValue({ songs: [] });
    vi.mocked(stub.listProfiles).mockResolvedValue({
      profiles: [
        {
          id: "genshin.harmonic_keys.v1",
          display_name: "谐律键琴",
          key_count: 21,
          calibration_status: "unverified",
        },
        {
          id: "genshin.windsong_lyre.v1",
          display_name: "风物之诗琴",
          key_count: 21,
          calibration_status: "unverified",
        },
      ],
    });
    vi.mocked(stub.getProfile).mockResolvedValue({
      id: "genshin.harmonic_keys.v1",
      display_name: "谐律键琴",
      key_count: 21,
      calibration: { status: "unverified" },
      keys: [
        { key_id: "high_1", row: "high", degree: 1, pitch: 72, binding: "Q" },
        { key_id: "mid_1", row: "mid", degree: 1, pitch: 60, binding: "A" },
        { key_id: "low_1", row: "low", degree: 1, pitch: 48, binding: "Z" },
      ],
    });
    const wrapper = mount(App, { props: { client: stub } });
    await flushPromises();
    await clickNav(wrapper, "编曲工作室");
    await flushPromises();
    expect((wrapper.find("#profile-select").element as HTMLSelectElement).value).toBe(
      "genshin.harmonic_keys.v1",
    );
  });
});
