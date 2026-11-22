import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import PianoRollEditor from "../components/PianoRollEditor.vue";
import type { PerformanceEventItem, ProfileKeyDef } from "../api";

const KEYS: ProfileKeyDef[] = [
  { key_id: "low_1", row: "low", degree: 1, pitch: 48, binding: "Z" },
  { key_id: "mid_1", row: "mid", degree: 1, pitch: 60, binding: "A" },
  { key_id: "high_1", row: "high", degree: 1, pitch: 72, binding: "Q" },
];

const INITIAL_EVENTS: PerformanceEventItem[] = [
  { at_ms: 0, key_id: "mid_1", mapped_pitch: 60, hold_ms: 40 },
  { at_ms: 500, key_id: "high_1", mapped_pitch: 72, hold_ms: 40 },
];

describe("PianoRollEditor", () => {
  it("supports note editing, undo/redo, adding notes, and emitting save", async () => {
    const wrapper = mount(PianoRollEditor, {
      props: { keys: KEYS, events: INITIAL_EVENTS },
    });

    expect(wrapper.text()).toContain("2 音符");

    // Nudge selected (first note @ 0ms) +50ms
    const plusBtn = wrapper.findAll("button").find((b) => b.text().trim() === "+50ms")!;
    await plusBtn.trigger("click");
    expect(wrapper.text()).toContain("有未保存修改");
    expect(wrapper.text()).toContain("mid_1 @ 50 ms");

    // Delete selected note -> down to 1 note
    const delBtn = wrapper.findAll("button").find((b) => b.text().includes("删除音符"))!;
    await delBtn.trigger("click");
    expect(wrapper.text()).toContain("1 音符");

    // Undo restores 2 notes
    const undoBtn = wrapper.findAll("button").find((b) => b.text().trim() === "撤销")!;
    await undoBtn.trigger("click");
    expect(wrapper.text()).toContain("2 音符");

    // Redo removes again
    const redoBtn = wrapper.findAll("button").find((b) => b.text().trim() === "重做")!;
    await redoBtn.trigger("click");
    expect(wrapper.text()).toContain("1 音符");

    // Add a new note
    await wrapper.find("#pr-new-key").setValue("low_1");
    await wrapper.find("#pr-new-time").setValue(250);
    const addBtn = wrapper.findAll("button").find((b) => b.text().includes("添加音符"))!;
    await addBtn.trigger("click");
    expect(wrapper.text()).toContain("2 音符");

    // Save emits updated sorted events + label
    await wrapper.find("#pr-version-label").setValue("自定义指法");
    const saveBtn = wrapper.findAll("button").find((b) => b.text().includes("保存为新版本"))!;
    await saveBtn.trigger("click");

    const emitted = wrapper.emitted("save");
    expect(emitted).toBeTruthy();
    const payload = emitted![0][0] as { events: PerformanceEventItem[]; label: string };
    expect(payload.label).toBe("自定义指法");
    expect(payload.events).toHaveLength(2);
    expect(payload.events[0].at_ms).toBe(250);
    expect(payload.events[0].key_id).toBe("low_1");
    expect(payload.events[1].at_ms).toBe(500);
  });
});
