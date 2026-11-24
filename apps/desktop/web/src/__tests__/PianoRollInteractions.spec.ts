import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import PianoRollEditor from "../components/PianoRollEditor.vue";

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
    const wrapper = mount(PianoRollEditor, {
      props: { keys: KEYS, events: EVENTS },
    });

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
    const wrapper = mount(PianoRollEditor, {
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
    });

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
    const wrapper = mount(PianoRollEditor, {
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
    });

    const notes = wrapper.findAll(".pr-note");
    expect(notes).toHaveLength(2);
    // orderedKeys renders higher pitch (mid_2, track 2) first, then mid_1 (track 1)
    expect(notes[0].classes()).toContain("track-c-1");
    expect(notes[0].classes()).toContain("is-adjusted");
    expect(notes[1].classes()).toContain("track-c-0");

    // Focus track 1 (Vocal) -> track 2 (Piano, notes[0]) dims
    const legendBtns = wrapper.findAll(".pr-legend-btn");
    const vocalLegend = legendBtns.find((b) => b.text().includes("Vocal"))!;
    await vocalLegend.trigger("click");
    expect(wrapper.findAll(".pr-note")[0].classes()).toContain("is-dimmed");

    // Restore all tracks
    await legendBtns[0].trigger("click");
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
});
