import type { PerformanceEventItem } from "../api";

let sharedCtx: AudioContext | null = null;

function resolveAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (!sharedCtx || sharedCtx.state === "closed") {
    sharedCtx = new Ctor();
  }
  if (sharedCtx.state === "suspended") {
    void sharedCtx.resume().catch(() => {});
  }
  return sharedCtx;
}

function midiToHz(pitch: number): number {
  return 440 * Math.pow(2, (pitch - 69) / 12);
}

/**
 * Low-latency browser-side plucked lyre audition for Piano Roll note clicks, drags, and keys.
 * Safe no-op in headless/test environments without Web Audio API.
 */
export function auditionMidiNote(pitch: number, velocity = 96, holdMs = 260, ctxOverride?: AudioContext | null): void {
  const ctx = ctxOverride ?? resolveAudioContext();
  if (!ctx) return;
  const now = ctx.currentTime;
  const dur = Math.max(0.14, Math.min(1.4, holdMs / 1000 + 0.25));
  const amp = Math.max(0.03, Math.min(0.22, (velocity / 127) * 0.16));

  const master = ctx.createGain();
  master.gain.setValueAtTime(0.0001, now);
  master.gain.exponentialRampToValueAtTime(amp, now + 0.008);
  master.gain.exponentialRampToValueAtTime(0.0001, now + dur);

  const filter = ctx.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.setValueAtTime(Math.min(4800, midiToHz(pitch) * 4.5), now);
  filter.frequency.exponentialRampToValueAtTime(Math.max(520, midiToHz(pitch) * 1.4), now + dur);

  const osc1 = ctx.createOscillator();
  osc1.type = "triangle";
  osc1.frequency.setValueAtTime(midiToHz(pitch), now);

  const osc2 = ctx.createOscillator();
  osc2.type = "sine";
  osc2.frequency.setValueAtTime(midiToHz(pitch) * 2, now);
  const gain2 = ctx.createGain();
  gain2.gain.setValueAtTime(0.28, now);
  gain2.gain.exponentialRampToValueAtTime(0.02, now + dur * 0.5);

  osc1.connect(filter);
  osc2.connect(gain2);
  gain2.connect(filter);
  filter.connect(master);
  master.connect(ctx.destination);

  osc1.start(now);
  osc2.start(now);
  osc1.stop(now + dur + 0.02);
  osc2.stop(now + dur + 0.02);
}

export interface DraftSequencer {
  stop: () => void;
}

/**
 * Play unsaved Piano Roll draft events directly in Web Audio with a live playhead callback.
 */
export function startDraftSequencer(
  events: PerformanceEventItem[],
  startMs: number,
  callbacks: {
    onTick: (posMs: number) => void;
    onEnded: () => void;
  },
): DraftSequencer {
  const ctx = resolveAudioContext();
  const sorted = [...events].sort((a, b) => a.at_ms - b.at_ms);
  const endMs =
    sorted.length > 0 ? Math.max(...sorted.map((e) => e.at_ms + Math.max(200, e.hold_ms))) + 250 : 0;

  if (sorted.length === 0 || startMs >= endMs) {
    callbacks.onEnded();
    return { stop: () => {} };
  }

  let stopped = false;
  let cursor = sorted.findIndex((e) => e.at_ms >= Math.max(0, startMs));
  if (cursor < 0) cursor = sorted.length;

  const wallStart = performance.now();
  const timer = window.setInterval(() => {
    if (stopped) return;
    const elapsed = performance.now() - wallStart;
    const pos = Math.max(0, startMs) + elapsed;
    while (cursor < sorted.length && sorted[cursor].at_ms <= pos + 35) {
      const ev = sorted[cursor];
      auditionMidiNote(ev.mapped_pitch, ev.velocity ?? 92, ev.hold_ms, ctx);
      cursor += 1;
    }
    callbacks.onTick(Math.round(pos));
    if (pos >= endMs) {
      stopped = true;
      window.clearInterval(timer);
      callbacks.onEnded();
    }
  }, 25);

  return {
    stop: () => {
      if (stopped) return;
      stopped = true;
      window.clearInterval(timer);
    },
  };
}
