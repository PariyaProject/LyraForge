import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import LyreKeyboard from "../components/LyreKeyboard.vue";

describe("LyreKeyboard", () => {
  it("renders 3 rows of keys and marks active counts", () => {
    const keys = [
      { key_id: "high_1", row: "high", degree: 1, pitch: 72, binding: "Q" },
      { key_id: "mid_1", row: "mid", degree: 1, pitch: 60, binding: "A" },
      { key_id: "low_1", row: "low", degree: 1, pitch: 48, binding: "Z" },
    ];
    const wrapper = mount(LyreKeyboard, {
      props: {
        keys,
        eventCounts: { mid_1: 4, high_1: 0 },
      },
    });
    const rendered = wrapper.findAll(".lyre-key");
    expect(rendered).toHaveLength(3);
    expect(rendered[0].classes()).not.toContain("active");
    expect(rendered[1].classes()).toContain("active");
    expect(rendered[1].text()).toContain("4 音");
  });
});
