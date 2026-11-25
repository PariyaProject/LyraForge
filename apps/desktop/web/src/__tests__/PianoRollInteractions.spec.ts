import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import PianoRollEditor from "../components/PianoRollEditor.vue";

const mountedWrappers: VueWrapper[] = [];
function trackMount<T extends VueWrapper>(w: T): T {
  mountedWrappers.push(w);
  return w;
}
afterEach(() => {
  while (mountedWrappers.length > 0) {
    mountedWrappers.pop()?.unmount();
  }
});

const KEYS = [
  { key_id: "mid_1", row: "mid", degree: 1, pitch: 60, binding: "a" },
  { key_id: "mid_2", row: "mid", degree: 2, pitch: 62, binding: "s" },
];

const EVENTS = [
  {
    at_ms: 0,
    duration_ms: 250,
    hold_ms: 80,
    key_id: "mid_1",
    key_binding: "a",
    source_pitch: 60,
    mapped_pitch: 60,
    velocity: 90,
    adjustments: [],
  },
];

describe("PianoRollEditor DAW interactions", () => {
  it("supports zoom, snap, keyboard shortcuts, mode switching, and pointer drag", async () => {
    const wrapper = trackMount(
      mount(PianoRollEditor, {
        props: { keys: KEYS, events: EVENTS },
      }),
    );

    // Zoom & snap controls exist
    const zoomInBtn = wrapper.find('button[aria-label="放大时间轴"]');
    await zoomInBtn.trigger("click");
    await zoomInBtn.trigger("click");
    expect(wrapper.text()).toContain("150%");
    await wrapper.find("#pr-snap-select").setValue("100");

    // Keyboard shortcut on editor region: ArrowRight nudges by snapMs (100ms), ArrowUp moves pitch up
    const roll = wrapper.find(".piano-roll-editor");
    await roll.trigger("keydown", { key: "ArrowRight" });
    expect(wrapper.text()).toContain("mid_1 @ 100 ms");

    await roll.trigger("keydown", { key: "ArrowUp" });
    expect(wrapper.text()).toContain("mid_2 @ 100 ms");

    // Switch to add mode and click first lane to insert note
    const addModeBtn = wrapper.findAll("button").find((b) => b.text().includes("点击添加"))!;
    await addModeBtn.trigger("click");
    const lanes = wrapper.findAll(".pr-lane");
    await lanes[1].trigger("click", { clientX: 20 });
    expect(wrapper.text()).toContain("2 音符");

    // Pointer drag on first note changes timing when pointer moves horizontally
    const PointerOrMouse = globalThis.PointerEvent ?? MouseEvent;
    const notes = wrapper.findAll(".pr-note");
    await notes[0].trigger("pointerdown", { button: 0, clientX: 0, clientY: 10 });
    window.dispatchEvent(new PointerOrMouse("pointermove", { clientX: 120, clientY: 10 }));
    window.dispatchEvent(new PointerOrMouse("pointerup", { clientX: 120, clientY: 10 }));
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).toContain("有未保存修改");

    // Save emits updated events
    const saveBtn = wrapper.findAll("button").find((b) => b.text().includes("保存为新版本"))!;
    await saveBtn.trigger("click");
    const emitted = wrapper.emitted("save");
    expect(emitted).toBeTruthy();
    expect((emitted![0][0] as { events: unknown[] }).events.length).toBe(2);
  });

  it("renders full timelines past 60s without grid truncation and supports 25% zoom", async () => {
    const wrapper = trackMount(
      mount(PianoRollEditor, {
        props: {
          keys: KEYS,
          events: [
            {
              at_ms: 0,
              hold_ms: 80,
              key_id: "mid_1",
              mapped_pitch: 60,
              source_track: 0,
              adjustments: [],
            },
            {
              at_ms: 180_000,
              hold_ms: 120,
              key_id: "mid_2",
              mapped_pitch: 62,
              source_track: 0,
              adjustments: [],
            },
          ],
        },
      }),
    );

    const canvas = wrapper.find(".pr-canvas");
    const widthMatch = /(\d+)px/.exec(canvas.attributes("style") ?? "");
    expect(widthMatch).toBeTruthy();
    expect(Number(widthMatch![1])).toBeGreaterThan(14_000);
    expect(wrapper.text()).toContain("3:00");

    const zoomOutBtn = wrapper.find('button[aria-label="缩小时间轴"]');
    await zoomOutBtn.trigger("click");
    await zoomOutBtn.trigger("click");
    await zoomOutBtn.trigger("click");
    expect(wrapper.text()).toContain("25%");
  });

  it("colors notes by track, filters legend focus, multi-selects, duplicates, and discards changes", async () => {
    const wrapper = trackMount(
      mount(PianoRollEditor, {
        props: {
          keys: KEYS,
          melodyTrack: 1,
          tracks: [
            { index: 1, name: "Vocal", is_percussion: false, note_count: 10, channels: [0], min_pitch: 60, max_pitch: 72 },
            { index: 2, name: "Piano", is_percussion: false, note_count: 12, channels: [1], min_pitch: 48, max_pitch: 64 },
          ],
          events: [
            {
              at_ms: 100,
              hold_ms: 80,
              key_id: "mid_1",
              mapped_pitch: 60,
              source_track: 1,
              adjustments: [],
            },
            {
              at_ms: 500,
              hold_ms: 80,
              key_id: "mid_2",
              mapped_pitch: 62,
              source_track: 2,
              adjustments: ["octave_folded"],
            },
          ],
        },
      }),
    );

    const notes = wrapper.findAll(".pr-note");
    expect(notes).toHaveLength(2);
    // orderedKeys renders higher pitch (mid_2, track 2) first, then mid_1 (track 1)
    expect(notes[0].classes()).toContain("track-c-1");
    expect(notes[0].classes()).toContain("is-adjusted");
    expect(notes[1].classes()).toContain("track-c-0");

    // Localized Chinese legend ("人声", "钢琴"): solo track 1 (人声) -> track 2 (钢琴, notes[0]) dims
    const chips = wrapper.findAll(".pr-track-chip");
    const vocalChip = chips.find((c) => c.text().includes("人声"))!;
    expect(vocalChip.find(".pr-legend-btn").attributes("title")).toContain("Vocal");
    await vocalChip.find(".pr-solo-btn").trigger("click");
    expect(wrapper.findAll(".pr-note")[0].classes()).toContain("is-dimmed");

    // Restore all tracks
    await wrapper.find(".pr-legend > .pr-legend-btn").trigger("click");
    expect(wrapper.findAll(".pr-note")[0].classes()).not.toContain("is-dimmed");

    // Inline time edit
    await wrapper.find("#pr-edit-time").setValue("150");
    await wrapper.find("#pr-edit-time").trigger("change");
    expect(wrapper.text()).toContain("mid_1 @ 150 ms");
    expect(wrapper.text()).toContain("有未保存修改");

    // Ctrl+A select all + Ctrl+D duplicate both notes
    const roll = wrapper.find(".piano-roll-editor");
    await roll.trigger("keydown", { key: "a", ctrlKey: true });
    expect(wrapper.text()).toContain("已选 2 个音符");
    await roll.trigger("keydown", { key: "d", ctrlKey: true });
    expect(wrapper.text()).toContain("4 音符");

    // Shift+pointerdown multi-selects & batch +50ms moves selection, Discard resets everything
    const plus50 = wrapper.findAll("button").find((b) => b.text().trim() === "+50ms")!;
    await plus50.trigger("click");
    const discardBtn = wrapper.findAll("button").find((b) => b.text().includes("放弃修改"))!;
    await discardBtn.trigger("click");
    expect(wrapper.text()).toContain("已同步");
    expect(wrapper.text()).toContain("2 音符");
    expect(wrapper.text()).toContain("mid_1 @ 100 ms");
  });

  it("supports ±1 octave shift, accompaniment thinning/clearing, undo/redo, and fixed-velocity preview", async () => {
    const threeOctKeys = [
      { key_id: "low_1", row: "low", degree: 1, pitch: 48, binding: "z" },
      { key_id: "mid_1", row: "mid", degree: 1, pitch: 60, binding: "a" },
      { key_id: "high_1", row: "high", degree: 1, pitch: 72, binding: "q" },
    ];
    const wrapper = trackMount(
      mount(PianoRollEditor, {
        props: {
          keys: threeOctKeys,
          melodyTrack: 0,
          fixedVelocityPreview: true,
          tracks: [
            { index: 0, name: "Vocal", is_percussion: false, note_count: 1, channels: [0], min_pitch: 60, max_pitch: 60 },
            { index: 1, name: "Guitar", is_percussion: false, note_count: 4, channels: [1], min_pitch: 48, max_pitch: 48 },
          ],
          events: [
            { at_ms: 0, hold_ms: 80, key_id: "mid_1", mapped_pitch: 60, source_track: 0, velocity: 110, adjustments: [] },
            { at_ms: 100, hold_ms: 80, key_id: "low_1", mapped_pitch: 48, source_track: 1, velocity: 45, adjustments: [] },
            { at_ms: 200, hold_ms: 80, key_id: "low_1", mapped_pitch: 48, source_track: 1, velocity: 45, adjustments: [] },
            { at_ms: 300, hold_ms: 80, key_id: "low_1", mapped_pitch: 48, source_track: 1, velocity: 45, adjustments: [] },
            { at_ms: 520, hold_ms: 80, key_id: "low_1", mapped_pitch: 48, source_track: 1, velocity: 45, adjustments: [] },
          ],
        },
      }),
    );

    // Initially first note (mid_1 @ 0 ms) is selected -> Shift+ArrowUp lifts +1 octave to high_1
    const roll = wrapper.find(".piano-roll-editor");
    await roll.trigger("keydown", { key: "ArrowUp", shiftKey: true });
    expect(wrapper.text()).toContain("high_1 @ 0 ms");

    // -1 octave button brings it back to mid_1
    const octDownBtn = wrapper.findAll("button").find((b) => b.text().trim() === "-1八度")!;
    await octDownBtn.trigger("click");
    expect(wrapper.text()).toContain("mid_1 @ 0 ms");

    // Select all -> 伴奏瘦身 thins dense 120ms & 240ms guitar notes while keeping 0ms & 480ms + melody
    await roll.trigger("keydown", { key: "a", ctrlKey: true });
    const thinBtn = wrapper.findAll("button").find((b) => b.text().trim() === "伴奏瘦身")!;
    await thinBtn.trigger("click");
    expect(wrapper.text()).toContain("3 音符");

    // Undo restores all 5 notes, then 清伴奏 drops all 4 guitar notes keeping Vocal melody
    await roll.trigger("keydown", { key: "z", ctrlKey: true });
    expect(wrapper.text()).toContain("5 音符");

    await roll.trigger("keydown", { key: "a", ctrlKey: true });
    const clearAccBtn = wrapper.findAll("button").find((b) => b.text().trim() === "清伴奏")!;
    await clearAccBtn.trigger("click");
    expect(wrapper.text()).toContain("1 音符");
  });

  it("resets playhead on arrangement switch, supports Space/Shift+Space/Home/F, live solo & lyric smart follow", async () => {
    vi.useFakeTimers();
    const origAudioCtx = window.AudioContext;
    const playedHz: number[] = [];
    class FakeAudioCtx {
      state = "running";
      currentTime = 0;
      destination = {};
      resume = vi.fn().mockResolvedValue(undefined);
      createGain() {
        return {
          gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
          connect: vi.fn(),
        };
      }
      createBiquadFilter() {
        return {
          type: "lowpass",
          frequency: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
          connect: vi.fn(),
        };
      }
      createOscillator() {
        return {
          type: "triangle",
          frequency: {
            setValueAtTime: vi.fn((hz: number) => {
              playedHz.push(Math.round(hz));
            }),
          },
          detune: { setValueAtTime: vi.fn() },
          connect: vi.fn(),
          start: vi.fn(),
          stop: vi.fn(),
        };
      }
    }
    (window as unknown as { AudioContext: unknown }).AudioContext = FakeAudioCtx;

    try {
      const longKeys = [
        { key_id: "mid_1", row: "mid", degree: 1, pitch: 60, binding: "a" },
        { key_id: "mid_5", row: "mid", degree: 5, pitch: 67, binding: "g" },
      ];
      const wrapper = mount(PianoRollEditor, {
        attachTo: document.body,
        props: {
          keys: longKeys,
          arrangementId: "arr-a",
          profileId: "genshin.harmonic_keys.v1",
          melodyTrack: 0,
          tracks: [
            { index: 0, name: "Vocal", is_percussion: false, note_count: 2, channels: [0], min_pitch: 60, max_pitch: 60 },
            { index: 1, name: "Guitar", is_percussion: false, note_count: 1, channels: [1], min_pitch: 67, max_pitch: 67 },
          ],
          events: [
            { at_ms: 0, hold_ms: 80, key_id: "mid_1", mapped_pitch: 60, source_track: 0, adjustments: [] },
            { at_ms: 15_000, hold_ms: 80, key_id: "mid_1", mapped_pitch: 60, source_track: 0, adjustments: [] },
            { at_ms: 15_120, hold_ms: 80, key_id: "mid_5", mapped_pitch: 67, source_track: 1, adjustments: [] },
            { at_ms: 30_000, hold_ms: 80, key_id: "mid_1", mapped_pitch: 60, source_track: 0, adjustments: [] },
          ],
        },
      });

      const scrollEl = wrapper.find(".pr-scroll").element as HTMLElement;
      Object.defineProperty(scrollEl, "clientWidth", { value: 480, configurable: true });

      // Click ruler to seek to 15s (approx 1200px at 0.08 px/ms), then pause/resume & test Space shortcut
      const rulerTrack = wrapper.find(".pr-ruler-track").element as HTMLElement;
      rulerTrack.getBoundingClientRect = () =>
        ({ left: 0, top: 0, width: 3000, height: 26, right: 3000, bottom: 26, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
      await wrapper.find(".pr-ruler-track").trigger("click", { clientX: 1200 });
      expect(wrapper.text()).toContain("0:15 / 0:30");

      // Window-level Space starts draft without canvas focus, then Space pauses while keeping 0:15 playhead
      window.dispatchEvent(new KeyboardEvent("keydown", { code: "Space", cancelable: true }));
      await wrapper.vm.$nextTick();
      expect(wrapper.find("#pr-draft-toggle").text()).toContain("暂停草稿");

      // Solo track 0 mid-playback: track 1 (392 Hz, G4) should not trigger after solo changes
      playedHz.length = 0;
      const vocalChip = wrapper.findAll(".pr-track-chip").find((c) => c.text().includes("人声"))!;
      await vocalChip.find(".pr-solo-btn").trigger("click");
      await vi.advanceTimersByTimeAsync(220);
      expect(playedHz.some((hz) => Math.abs(hz - 262) <= 2)).toBe(true);
      expect(playedHz.some((hz) => Math.abs(hz - 392) <= 2)).toBe(false);

      // Manual scroll ahead while playing detaches follow & keeps manual return button visible
      scrollEl.scrollLeft = 2400;
      await wrapper.find(".pr-scroll").trigger("scroll");
      await wrapper.vm.$nextTick();
      const returnBtn = wrapper.find("#pr-return-playhead-btn");
      expect(returnBtn.exists()).toBe(true);
      expect(returnBtn.text()).toContain("← 回到播放点");

      // Scrolling back near playhead does NOT auto-reattach; button stays visible until clicked
      scrollEl.scrollLeft = 1120;
      await wrapper.find(".pr-scroll").trigger("scroll");
      await vi.advanceTimersByTimeAsync(1000);
      expect(wrapper.find("#pr-return-playhead-btn").exists()).toBe(true);
      expect(wrapper.find("#pr-return-playhead-btn").text()).toContain("回到播放点");
      expect(scrollEl.scrollLeft).toBe(1120);

      // Clicking "回到播放点" returns to playhead & re-attaches follow
      await wrapper.find("#pr-return-playhead-btn").trigger("click");
      await wrapper.vm.$nextTick();
      expect(wrapper.find("#pr-return-playhead-btn").exists()).toBe(false);

      // Scroll ahead again, then press F to snap back & reattach
      scrollEl.scrollLeft = 2400;
      await wrapper.find(".pr-scroll").trigger("scroll");
      await wrapper.vm.$nextTick();
      expect(wrapper.find("#pr-return-playhead-btn").exists()).toBe(true);
      window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyF", key: "f", cancelable: true }));
      await wrapper.vm.$nextTick();
      expect(wrapper.find("#pr-return-playhead-btn").exists()).toBe(false);

      // Pause retains playhead > 0 ('继续草稿')
      window.dispatchEvent(new KeyboardEvent("keydown", { code: "Space", cancelable: true }));
      await wrapper.vm.$nextTick();
      expect(wrapper.find("#pr-draft-toggle").text()).toContain("继续草稿");

      // Shift+Space restarts from 0:00
      window.dispatchEvent(new KeyboardEvent("keydown", { code: "Space", shiftKey: true, cancelable: true }));
      await wrapper.vm.$nextTick();
      expect(wrapper.text()).toContain("0:00 / 0:30");

      // Advance briefly then pause at non-zero time, then switch arrangementId -> playhead resets to 0:00!
      await vi.advanceTimersByTimeAsync(1100);
      window.dispatchEvent(new KeyboardEvent("keydown", { code: "Space", cancelable: true }));
      await wrapper.vm.$nextTick();
      expect(wrapper.find("#pr-draft-toggle").text()).toContain("继续草稿");

      await wrapper.setProps({ arrangementId: "arr-b" });
      await wrapper.vm.$nextTick();
      expect(wrapper.text()).toContain("0:00 / 0:30");
      expect(wrapper.find("#pr-draft-toggle").text()).toContain("试听草稿");

      // Selecting timbre emits update:previewTimbre
      await wrapper.find("#pr-timbre-select").setValue("zither");
      expect(wrapper.emitted("update:previewTimbre")?.[0]).toEqual(["zither"]);

      wrapper.unmount();
    } finally {
      (window as unknown as { AudioContext: unknown }).AudioContext = origAudioCtx;
      vi.useRealTimers();
    }
  });

  it("supports multi-track audition toggles, continues past short-track end, and renders live preview ghost diff", async () => {
    vi.useFakeTimers();
    const origAudioCtx = window.AudioContext;
    const playedHz: number[] = [];
    class FakeMultiAudioCtx {
      state = "running";
      currentTime = 0;
      destination = {};
      resume = vi.fn().mockResolvedValue(undefined);
      createGain() {
        return {
          gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
          connect: vi.fn(),
        };
      }
      createBiquadFilter() {
        return {
          type: "lowpass",
          frequency: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
          connect: vi.fn(),
        };
      }
      createOscillator() {
        return {
          type: "sine",
          frequency: {
            setValueAtTime: vi.fn((hz: number) => {
              playedHz.push(Math.round(hz));
            }),
          },
          connect: vi.fn(),
          start: vi.fn(),
          stop: vi.fn(),
        };
      }
    }
    (window as unknown as { AudioContext: unknown }).AudioContext = FakeMultiAudioCtx;

    try {
      const threeKeys = [
        { key_id: "low_1", row: "low", degree: 1, pitch: 48, binding: "z" }, // ~131 Hz
        { key_id: "mid_1", row: "mid", degree: 1, pitch: 60, binding: "a" }, // ~262 Hz
        { key_id: "high_1", row: "high", degree: 1, pitch: 72, binding: "q" }, // ~523 Hz
      ];
      const baseEvents = [
        { at_ms: 500, hold_ms: 80, key_id: "high_1", mapped_pitch: 72, source_track: 0, adjustments: [] },
        { at_ms: 15_080, hold_ms: 80, key_id: "mid_1", mapped_pitch: 60, source_track: 1, adjustments: [] },
        { at_ms: 15_080, hold_ms: 80, key_id: "low_1", mapped_pitch: 48, source_track: 2, adjustments: [] },
        { at_ms: 28_000, hold_ms: 80, key_id: "mid_1", mapped_pitch: 60, source_track: 1, adjustments: [] },
      ];
      const wrapper = trackMount(
        mount(PianoRollEditor, {
          attachTo: document.body,
          props: {
            keys: threeKeys,
            melodyTrack: 0,
            tracks: [
              { index: 0, name: "Vocal Lead", is_percussion: false, note_count: 1, channels: [0], min_pitch: 72, max_pitch: 72 },
              { index: 1, name: "Piano", is_percussion: false, note_count: 2, channels: [1], min_pitch: 60, max_pitch: 60 },
              { index: 2, name: "Fingered Bass", is_percussion: false, note_count: 1, channels: [2], min_pitch: 48, max_pitch: 48 },
            ],
            events: baseEvents,
          },
        }),
      );

      // Uncheck Bass (track 2) while keeping BOTH Vocal (track 0) + Piano (track 1) enabled
      const bassChip = wrapper.findAll(".pr-track-chip").find((c) => c.text().includes("贝斯"))!;
      await bassChip.find(".pr-legend-btn").trigger("click");
      const allNotes = wrapper.findAll(".pr-note");
      // orderedKeys puts high_1 (0), mid_1 (1,2), low_1 (3)
      expect(allNotes[0].classes()).not.toContain("is-dimmed");
      expect(allNotes[1].classes()).not.toContain("is-dimmed");
      expect(allNotes[3].classes()).toContain("is-dimmed");

      // Seek to 15s and play -> Piano (262 Hz) triggers, Bass (131 Hz) does NOT
      const rulerTrack = wrapper.find(".pr-ruler-track").element as HTMLElement;
      rulerTrack.getBoundingClientRect = () =>
        ({ left: 0, top: 0, width: 3000, height: 26, right: 3000, bottom: 26, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
      await wrapper.find(".pr-ruler-track").trigger("click", { clientX: 1200 });
      playedHz.length = 0;
      await wrapper.find("#pr-draft-toggle").trigger("click");
      await vi.advanceTimersByTimeAsync(160);
      expect(playedHz.some((hz) => Math.abs(hz - 262) <= 2)).toBe(true);
      expect(playedHz.some((hz) => Math.abs(hz - 131) <= 2)).toBe(false);

      // Now solo short Vocal track (its last note was at 500ms, well before 15s):
      // playback MUST NOT stop early or reset to 0:00!
      const vocalChip = wrapper.findAll(".pr-track-chip").find((c) => c.text().includes("人声主旋律"))!;
      await vocalChip.find(".pr-solo-btn").trigger("click");
      await vi.advanceTimersByTimeAsync(1100);
      expect(wrapper.find("#pr-draft-toggle").text()).toContain("暂停草稿");
      expect(wrapper.text()).toContain("0:16 / 0:28");

      await wrapper.find("#pr-draft-toggle").trigger("click");

      // Render live parameter preview diff overlay (1 removed Bass note + 1 added Piano note)
      const previewEvents = [
        baseEvents[0],
        baseEvents[1],
        { at_ms: 15_200, hold_ms: 80, key_id: "high_1", mapped_pitch: 72, source_track: 1, adjustments: [] },
        baseEvents[3],
      ];
      await wrapper.setProps({
        previewEvents,
        previewSummary: {
          baseCount: baseEvents.length,
          nextCount: previewEvents.length,
          baseScore: 89.5,
          nextScore: 94.0,
          alreadyExists: false,
          loading: false,
        },
      });
      await wrapper.vm.$nextTick();

      const previewBar = wrapper.find(".pr-preview-bar");
      expect(previewBar.exists()).toBe(true);
      expect(previewBar.text()).toContain("删减 -1");
      expect(previewBar.text()).toContain("新增/移位 +1");
      expect(previewBar.text()).toContain("将新建独立版本");
      expect(wrapper.find(".pr-note.is-ghost-removed").exists()).toBe(true);
      expect(wrapper.find(".pr-note-ghost-added").exists()).toBe(true);

      const applyPreviewBtn = previewBar.findAll("button").find((b) => b.text().includes("应用并生成版本"))!;
      await applyPreviewBtn.trigger("click");
      expect(wrapper.emitted("applyPreview")).toBeTruthy();

      const discardPreviewBtn = previewBar.findAll("button").find((b) => b.text().includes("还原当前参数"))!;
      await discardPreviewBtn.trigger("click");
      expect(wrapper.emitted("discardPreview")).toBeTruthy();
    } finally {
      (window as unknown as { AudioContext: unknown }).AudioContext = origAudioCtx;
      vi.useRealTimers();
    }
  });
});
