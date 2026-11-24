import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import AboutDialog from "../components/AboutDialog.vue";
import LyreKeyboard from "../components/LyreKeyboard.vue";
import PianoRollEditor from "../components/PianoRollEditor.vue";
import QueueDrawer from "../components/QueueDrawer.vue";
import type { LyraStore } from "../composables/useLyraStore";

describe("Redesigned DAW & Overlay Components", () => {
  it("renders playhead, emits seek on ruler click, and supports context menu duplicate", async () => {
    const keys = [
      { key_id: "high_1", row: "high", degree: 1, pitch: 72, binding: "Q" },
      { key_id: "mid_1", row: "mid", degree: 1, pitch: 60, binding: "A" },
      { key_id: "low_1", row: "low", degree: 1, pitch: 48, binding: "Z" },
    ];
    const events = [
      { at_ms: 0, key_id: "mid_1", mapped_pitch: 60, hold_ms: 80, adjustments: ["octave_folded"] },
    ];
    const wrapper = mount(PianoRollEditor, {
      props: { keys, events, playheadMs: 400, isPlaying: true },
    });

    expect(wrapper.find(".pr-playhead").exists()).toBe(true);
    expect(wrapper.find(".pr-note.is-adjusted").exists()).toBe(true);
    expect(wrapper.find(".pr-key-label.zone-high").exists()).toBe(true);
    expect(wrapper.find(".pr-key-label.zone-low").exists()).toBe(true);

    const rulerTrack = wrapper.find(".pr-ruler-track");
    await rulerTrack.trigger("click", { clientX: 80 });
    const seekEmitted = wrapper.emitted("seek");
    expect(seekEmitted).toBeTruthy();

    await wrapper.find(".pr-note").trigger("contextmenu", { clientX: 120, clientY: 120 });
    expect(wrapper.find(".pr-context-menu").exists()).toBe(true);

    const dupBtn = wrapper
      .findAll(".pr-context-menu button")
      .find((b) => b.text().includes("向后复制"))!;
    await dupBtn.trigger("click");
    expect(wrapper.text()).toContain("2 音符");
    expect(wrapper.text()).toContain("有未保存修改");
  });

  it("highlights sounding keys in LyreKeyboard", () => {
    const keys = [
      { key_id: "high_1", row: "high", degree: 1, pitch: 72, binding: "Q" },
      { key_id: "mid_1", row: "mid", degree: 1, pitch: 60, binding: "A" },
    ];
    const wrapper = mount(LyreKeyboard, {
      props: {
        keys,
        eventCounts: { mid_1: 2, high_1: 1 },
        activeKeyIds: ["high_1"],
      },
    });
    const cells = wrapper.findAll(".lyre-key");
    expect(cells[0].classes()).toContain("sounding");
    expect(cells[1].classes()).not.toContain("sounding");
  });

  it("handles QueueDrawer navigation and Escape dismissal", async () => {
    const storeStub = {
      queue: {
        value: {
          items: [
            { arrangement_id: "arr-1", song_id: "s-1", song_title: "Song 1", label: "Track 1" },
          ],
          index: 0,
          mode: "dry-run",
          realtime: false,
        },
      },
      selectArrangement: vi.fn().mockResolvedValue(undefined),
      handleQueueStep: vi.fn(),
      handleClearQueue: vi.fn(),
    } as unknown as LyraStore;

    const wrapper = mount(QueueDrawer, {
      props: { open: true, store: storeStub },
    });
    expect(wrapper.find(".queue-drawer").exists()).toBe(true);
    expect(wrapper.text()).toContain("Track 1");

    const nextBtn = wrapper.findAll("button").find((b) => b.text().includes("下一首"))!;
    await nextBtn.trigger("click");
    expect(storeStub.handleQueueStep).toHaveBeenCalledWith(1);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(wrapper.emitted("update:open")?.[0]).toEqual([false]);
  });

  it("renders AboutDialog license disclosures and closes cleanly", async () => {
    const wrapper = mount(AboutDialog, {
      props: { open: true, version: "0.1.0" },
    });
    expect(wrapper.text()).toContain("GNU GPL-3.0");
    expect(wrapper.text()).toContain("PyWebView");
    const closeBtn = wrapper.findAll("button").find((b) => b.text().includes("关闭"))!;
    await closeBtn.trigger("click");
    expect(wrapper.emitted("update:open")?.[0]).toEqual([false]);
  });
});
