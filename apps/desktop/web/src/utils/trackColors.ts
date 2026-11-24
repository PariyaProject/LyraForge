import type { SongTrackInfo } from "../api";

export const TRACK_COLOR_SLOT_COUNT = 6;

/**
 * Deterministic color slot assignment per MIDI track index.
 * Melody/vocal track is pinned to slot 0 (warm amber); accompaniment tracks cycle through slots 1..5.
 */
export function buildTrackColorMap(
  tracks: SongTrackInfo[],
  melodyTrack: number | null,
  eventTrackIds: number[] = [],
): Map<number, number> {
  const map = new Map<number, number>();
  const pitchedIds = tracks.filter((t) => !t.is_percussion).map((t) => t.index);
  const allIds = Array.from(new Set([...pitchedIds, ...eventTrackIds])).sort((a, b) => a - b);

  if (melodyTrack !== null && melodyTrack !== undefined) {
    map.set(melodyTrack, 0);
  }
  let slotCursor = 1;
  for (const idx of allIds) {
    if (map.has(idx)) continue;
    map.set(idx, slotCursor);
    slotCursor = slotCursor >= TRACK_COLOR_SLOT_COUNT - 1 ? 1 : slotCursor + 1;
  }
  return map;
}

export function trackColorClass(slot: number): string {
  const safe = Number.isFinite(slot) ? ((Math.trunc(slot) % TRACK_COLOR_SLOT_COUNT) + TRACK_COLOR_SLOT_COUNT) % TRACK_COLOR_SLOT_COUNT : 0;
  return `track-c-${safe}`;
}
