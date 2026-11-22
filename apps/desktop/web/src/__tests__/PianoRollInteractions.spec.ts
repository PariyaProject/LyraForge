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
});
