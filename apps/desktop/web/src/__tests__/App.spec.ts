import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import App from "../App.vue";
import type { ArrangementRecord, LyraForgeApi, TranscriptionRecord } from "../api";

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
});
