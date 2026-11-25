import { describe, expect, it } from "vitest";
import {
  formatAdjustmentLabel,
  formatMidiPitchName,
  formatTrackPitchRange,
  formatTrackTooltip,
  localizeTrackName,
} from "../utils/trackNames";

describe("trackNames localization helpers", () => {
  it("translates standard stems, GM instruments, generic names, and percussion cleanly", () => {
    expect(localizeTrackName("Vocal Lead", 0)).toBe("人声主旋律");
    expect(localizeTrackName("Accompaniment", 1)).toBe("伴奏");
    expect(localizeTrackName("Acoustic Grand Piano", 0)).toBe("钢琴");
    expect(localizeTrackName("Fingered Bass", 2)).toBe("贝斯 / 低音");
    expect(localizeTrackName("Nylon Guitar", 3)).toBe("木吉他");
    expect(localizeTrackName("String Ensemble 1", 4)).toBe("弦乐");
    expect(localizeTrackName("track_0", 0)).toBe("音轨 1");
    expect(localizeTrackName("", 2)).toBe("音轨 3");
    expect(localizeTrackName("Drums", 9, true)).toBe("打击乐 / 鼓组");
    expect(localizeTrackName("自定义主音轨", 0)).toBe("自定义主音轨");
  });

  it("formats pitch ranges, tooltips, and adjustment badges", () => {
    expect(formatMidiPitchName(60)).toBe("C4");
    expect(formatMidiPitchName(76)).toBe("E5");
    expect(
      formatTrackPitchRange({ min_pitch: 60, max_pitch: 76, is_percussion: false }),
    ).toBe("C4–E5");
    expect(
      formatTrackPitchRange({ min_pitch: 36, max_pitch: 42, is_percussion: true }),
    ).toBe("");
    expect(
      formatTrackTooltip({
        index: 0,
        name: "Vocal Lead",
        note_count: 42,
        channels: [0],
        is_percussion: false,
        min_pitch: 60,
        max_pitch: 76,
      }),
    ).toContain("原轨名：Vocal Lead · 音域 C4–E5 · 42 音");
    expect(formatAdjustmentLabel("octave_folded")).toContain("八度");
  });
});
