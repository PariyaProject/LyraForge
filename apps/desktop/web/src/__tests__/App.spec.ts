import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import App from "../App.vue";
import type { LyraForgeApi } from "../api";

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
});
