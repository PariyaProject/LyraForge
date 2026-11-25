import type { SongTrackInfo } from "../api";

const PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"] as const;
const CJK_RE = /[\u4e00-\u9fff]/;

const EXACT_TRACK_LABELS: Array<[RegExp, string]> = [
  [/^vocal\s*lead$/i, "人声主旋律"],
  [/^lead\s*vocal$/i, "人声主旋律"],
  [/^accompaniment$/i, "伴奏"],
  [/^accomp$/i, "伴奏"],
  [/^no[_\s-]*drums$/i, "无鼓伴奏"],
  [/^backing(\s+track)?$/i, "伴奏"],
  [/^other$/i, "伴奏声部"],
  [/^(right\s*hand|rh|piano\s*rh)$/i, "钢琴右手"],
  [/^(left\s*hand|lh|piano\s*lh)$/i, "钢琴左手"],
];

const KEYWORD_TRACK_LABELS: Array<[RegExp, string]> = [
  [/\bvocal|singing|singer\b/i, "人声"],
  [/\bmelody|main\s*theme\b/i, "主旋律"],
  [/\bchord(s)?\b/i, "和弦伴奏"],
  [/\belectric\s*piano|e[\s_-]?piano|rhodes\b/i, "电钢琴"],
  [/\bharpsichord\b/i, "羽管键琴"],
  [/\bpiano\b/i, "钢琴"],
  [/\bharp|lyre\b/i, "竖琴 / 诗琴"],
  [/\bzither|guzheng|koto\b/i, "古筝 / 拨弦"],
  [/\b(nylon|acoustic|steel)\s*guitar\b/i, "木吉他"],
  [/\b(electric|overdriven|distortion)\s*guitar\b/i, "电吉他"],
  [/\bguitar\b/i, "吉他"],
  [/\bbass\b/i, "贝斯 / 低音"],
  [/\bviolin\b/i, "小提琴"],
  [/\bviola\b/i, "中提琴"],
  [/\bcello\b/i, "大提琴"],
  [/\bstring(s)?\b/i, "弦乐"],
  [/\bflute\b/i, "长笛"],
  [/\bclarinet\b/i, "单簧管"],
  [/\bsax(ophone)?\b/i, "萨克斯"],
  [/\btrumpet\b/i, "小号"],
  [/\bbrass|horn\b/i, "铜管"],
  [/\bchoir|aah|ooh|voice\b/i, "合唱人声"],
  [/\bpad\b/i, "氛围铺底"],
  [/\bsynth(esizer)?\b/i, "合成器"],
  [/\borgan\b/i, "管风琴"],
  [/\b(music\s*box|celesta|glockenspiel|bell(s)?)\b/i, "八音盒 / 钟琴"],
  [/\b(drum(s)?|percussion|kit)\b/i, "打击乐 / 鼓组"],
  [/\blead\b/i, "领奏旋律"],
];

const ADJUSTMENT_LABELS: Record<string, string> = {
  octave_folded: "八度折半对齐到 21 键",
  semitone_substituted: "半音就近代偿",
  arpeggiated: "和弦错峰展开",
  phrase_shifted_up: "低音分句抬升 +1 八度",
  phrase_shifted_down: "高音分句回落 -1 八度",
  cross_stem_aligned: "跨轨微对齐",
  melody_retrigger_replaced: "同键让位主旋律",
  hold_shortened: "释放间隙微缩短",
};

export function formatMidiPitchName(pitch: number): string {
  if (!Number.isFinite(pitch) || pitch < 0 || pitch > 127) return "";
  const rounded = Math.round(pitch);
  const name = PITCH_NAMES[((rounded % 12) + 12) % 12];
  const octave = Math.floor(rounded / 12) - 1;
  return `${name}${octave}`;
}

export function formatTrackPitchRange(
  track: Pick<SongTrackInfo, "min_pitch" | "max_pitch" | "is_percussion">,
): string {
  if (track.is_percussion) return "";
  const lo = formatMidiPitchName(track.min_pitch);
  const hi = formatMidiPitchName(track.max_pitch);
  if (!lo || !hi) return "";
  return lo === hi ? lo : `${lo}–${hi}`;
}

export function localizeTrackName(
  rawName: string | null | undefined,
  trackIndex: number,
  isPercussion = false,
): string {
  const clean = (rawName ?? "").trim();
  if (isPercussion) {
    return CJK_RE.test(clean) ? clean : "打击乐 / 鼓组";
  }
  if (CJK_RE.test(clean)) {
    return clean;
  }
  if (!clean || /^(track|untitled|midi|channel)[\s_#-]*\d*$/i.test(clean)) {
    return `音轨 ${trackIndex + 1}`;
  }
  for (const [pattern, label] of EXACT_TRACK_LABELS) {
    if (pattern.test(clean)) return label;
  }
  for (const [pattern, label] of KEYWORD_TRACK_LABELS) {
    if (pattern.test(clean)) return label;
  }
  return clean;
}

export function formatTrackTooltip(track: SongTrackInfo): string {
  const range = formatTrackPitchRange(track);
  const parts: string[] = [];
  if (track.name?.trim()) {
    parts.push(`原轨名：${track.name.trim()}`);
  }
  if (range) {
    parts.push(`音域 ${range}`);
  }
  parts.push(`${track.note_count} 音`);
  return parts.join(" · ");
}

export function formatAdjustmentLabel(adj: string): string {
  return ADJUSTMENT_LABELS[adj] ?? adj;
}
