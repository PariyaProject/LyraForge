import type { PerformanceEventItem } from "../api";

export type PreviewTimbre = "auto" | "piano" | "lyre" | "zither" | "vintage";
export type ResolvedTimbre = "piano" | "lyre" | "zither" | "vintage";

interface ActiveVoice {
  gain: GainNode;
  endSec: number;
}

interface ContextAudioState {
  masterInput: AudioNode;
  activeVoices: Map<number, ActiveVoice>;
}

interface TimbreVoiceSpec {
  attackS: number;
  decayDur: number;
  h2Gain: number;
  h3Gain: number;
  h4Gain: number;
  startFilterMult: number;
  endFilterMult: number;
  baseLevel: number;
}

let sharedCtx: AudioContext | null = null;
let sharedCtxCtor: unknown = null;
const ctxCache = new WeakMap<AudioContext, ContextAudioState>();

function resolveAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (!sharedCtx || sharedCtx.state === "closed" || sharedCtxCtor !== Ctor) {
    sharedCtx = new Ctor();
    sharedCtxCtor = Ctor;
  }
  if (sharedCtx.state === "suspended") {
    void sharedCtx.resume().catch(() => {});
  }
  return sharedCtx;
}

function getContextState(ctx: AudioContext): ContextAudioState {
  const existing = ctxCache.get(ctx);
  if (existing) return existing;

  const masterBus = ctx.createGain();
  masterBus.gain.setValueAtTime(0.86, ctx.currentTime);

  // Transparent safety limiter only for heavy chords (never crushes solo notes or adds white noise)
  if (typeof ctx.createDynamicsCompressor === "function") {
    try {
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.setValueAtTime(-6, ctx.currentTime);
      comp.knee.setValueAtTime(14, ctx.currentTime);
      comp.ratio.setValueAtTime(2.2, ctx.currentTime);
      comp.attack.setValueAtTime(0.01, ctx.currentTime);
      comp.release.setValueAtTime(0.18, ctx.currentTime);
      masterBus.connect(comp);
      comp.connect(ctx.destination);
    } catch {
      masterBus.connect(ctx.destination);
    }
  } else {
    masterBus.connect(ctx.destination);
  }

  const state: ContextAudioState = {
    masterInput: masterBus,
    activeVoices: new Map(),
  };
  ctxCache.set(ctx, state);
  return state;
}

function midiToHz(pitch: number): number {
  return 440 * Math.pow(2, (pitch - 69) / 12);
}

export function resolvePreviewTimbre(
  profileId?: string | null,
  timbre: PreviewTimbre = "auto",
): ResolvedTimbre {
  if (timbre && timbre !== "auto") {
    return timbre;
  }
  const pid = (profileId ?? "").toLowerCase();
  if (pid.includes("harmonic_keys") || pid.includes("piano")) return "piano";
  if (pid.includes("floral_zither") || pid.includes("zither")) return "zither";
  if (pid.includes("vintage")) return "vintage";
  return "lyre";
}

function voiceSpecForTimbre(timbre: ResolvedTimbre, pitchNorm: number, holdMs: number): TimbreVoiceSpec {
  const holdS = holdMs / 1000;
  if (timbre === "piano") {
    return {
      attackS: 0.004,
      decayDur: Math.max(0.75, Math.min(1.65, holdS + 1.05 - pitchNorm * 0.35)),
      h2Gain: Math.max(0.16, 0.36 - pitchNorm * 0.14),
      h3Gain: Math.max(0.05, 0.14 - pitchNorm * 0.07),
      h4Gain: Math.max(0.0, 0.05 - pitchNorm * 0.04),
      startFilterMult: 3.8,
      endFilterMult: 1.35,
      baseLevel: 0.19,
    };
  }
  if (timbre === "zither") {
    return {
      attackS: 0.003,
      decayDur: Math.max(0.45, Math.min(1.1, holdS + 0.55 - pitchNorm * 0.18)),
      h2Gain: Math.max(0.18, 0.38 - pitchNorm * 0.12),
      h3Gain: Math.max(0.06, 0.16 - pitchNorm * 0.07),
      h4Gain: 0.06,
      startFilterMult: 4.2,
      endFilterMult: 1.45,
      baseLevel: 0.18,
    };
  }
  if (timbre === "vintage") {
    return {
      attackS: 0.008,
      decayDur: Math.max(0.32, Math.min(0.95, holdS + 0.42)),
      h2Gain: 0.18,
      h3Gain: 0.04,
      h4Gain: 0.0,
      startFilterMult: 2.3,
      endFilterMult: 1.15,
      baseLevel: 0.18,
    };
  }
  // Refined Windsong Lyre: pure crystal harp harmonics, zero grit
  return {
    attackS: 0.005,
    decayDur: Math.max(0.42, Math.min(1.2, holdS + 0.62 - pitchNorm * 0.2)),
    h2Gain: 0.30 - pitchNorm * 0.08,
    h3Gain: 0.11 - pitchNorm * 0.04,
    h4Gain: 0.03,
    startFilterMult: 3.6,
    endFilterMult: 1.3,
    baseLevel: 0.18,
  };
}

/**
 * Low-latency browser-side instrument audition for Piano Roll note clicks, drags, and draft play.
 * Uses pure-tuned studio additive sine synthesis with smooth same-pitch damping and zero white noise.
 */
export function auditionMidiNote(
  pitch: number,
  velocity = 96,
  holdMs = 260,
  ctxOverride?: AudioContext | null,
  timbre: ResolvedTimbre = "piano",
  whenSec?: number,
): void {
  const ctx = ctxOverride ?? resolveAudioContext();
  if (!ctx) return;
  const startTime = whenSec !== undefined ? Math.max(ctx.currentTime, whenSec) : ctx.currentTime;
  const state = getContextState(ctx);
  const roundedPitch = Math.round(pitch);

  // Cleanly damp previous note on the same pitch so repeated keys stay distinct and crisp
  const prevVoice = state.activeVoices.get(roundedPitch);
  if (prevVoice && startTime < prevVoice.endSec) {
    const dampEnd = startTime + 0.018;
    if (typeof prevVoice.gain.gain.cancelScheduledValues === "function") {
      prevVoice.gain.gain.cancelScheduledValues(startTime);
    }
    if (typeof prevVoice.gain.gain.exponentialRampToValueAtTime === "function") {
      prevVoice.gain.gain.exponentialRampToValueAtTime(0.0001, dampEnd);
    }
  }

  const pitchNorm = Math.max(0, Math.min(1, (pitch - 48) / 36));
  const pitchLevel = 0.86 + 0.16 * pitchNorm;
  const spec = voiceSpecForTimbre(timbre, pitchNorm, holdMs);
  const freq = midiToHz(pitch);
  const amp = Math.max(0.03, Math.min(0.24, (velocity / 127) * spec.baseLevel * pitchLevel));
  const dur = spec.decayDur;

  const master = ctx.createGain();
  master.gain.setValueAtTime(0.0001, startTime);
  master.gain.exponentialRampToValueAtTime(amp, startTime + spec.attackS);
  master.gain.exponentialRampToValueAtTime(0.0001, startTime + dur);

  const filter = ctx.createBiquadFilter();
  filter.type = "lowpass";
  const startCutoff = Math.min(5200, Math.max(900, freq * spec.startFilterMult));
  const endCutoff = Math.max(420, Math.min(3600, freq * spec.endFilterMult));
  filter.frequency.setValueAtTime(startCutoff, startTime);
  filter.frequency.exponentialRampToValueAtTime(endCutoff, startTime + dur);

  const osc1 = ctx.createOscillator();
  osc1.type = "sine";
  osc1.frequency.setValueAtTime(freq, startTime);
  osc1.connect(filter);
  osc1.start(startTime);
  osc1.stop(startTime + dur + 0.02);

  if (spec.h2Gain > 0.005) {
    const osc2 = ctx.createOscillator();
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(freq * 2, startTime);
    const g2 = ctx.createGain();
    g2.gain.setValueAtTime(spec.h2Gain, startTime);
    g2.gain.exponentialRampToValueAtTime(0.008, startTime + dur * 0.45);
    osc2.connect(g2);
    g2.connect(filter);
    osc2.start(startTime);
    osc2.stop(startTime + dur + 0.02);
  }

  if (spec.h3Gain > 0.005) {
    const osc3 = ctx.createOscillator();
    osc3.type = "sine";
    osc3.frequency.setValueAtTime(freq * 3, startTime);
    const g3 = ctx.createGain();
    g3.gain.setValueAtTime(spec.h3Gain, startTime);
    g3.gain.exponentialRampToValueAtTime(0.004, startTime + dur * 0.28);
    osc3.connect(g3);
    g3.connect(filter);
    osc3.start(startTime);
    osc3.stop(startTime + dur + 0.02);
  }

  if (spec.h4Gain > 0.005) {
    const osc4 = ctx.createOscillator();
    osc4.type = "sine";
    osc4.frequency.setValueAtTime(freq * 4, startTime);
    const g4 = ctx.createGain();
    g4.gain.setValueAtTime(spec.h4Gain, startTime);
    g4.gain.exponentialRampToValueAtTime(0.003, startTime + dur * 0.18);
    osc4.connect(g4);
    g4.connect(filter);
    osc4.start(startTime);
    osc4.stop(startTime + dur + 0.02);
  }

  filter.connect(master);
  master.connect(state.masterInput);
  state.activeVoices.set(roundedPitch, { gain: master, endSec: startTime + dur });
}

export interface DraftSequencer {
  stop: () => void;
  seek: (ms: number) => void;
}

/**
 * Play Piano Roll draft events directly in Web Audio, reading live edits/track filters
 * across a sliding lookahead window and never stopping prematurely before total duration.
 */
export function startDraftSequencer(
  eventsOrGetter: PerformanceEventItem[] | (() => PerformanceEventItem[]),
  startMs: number,
  callbacks: {
    onTick: (posMs: number) => void;
    onEnded: () => void;
  },
  options?: {
    fixedVelocity?: boolean;
    timbre?: ResolvedTimbre;
    getFixedVelocity?: () => boolean;
    getTimbre?: () => ResolvedTimbre;
    getTotalDurationMs?: () => number;
  },
): DraftSequencer {
  const ctx = resolveAudioContext();
  const getEvents =
    typeof eventsOrGetter === "function" ? eventsOrGetter : () => eventsOrGetter;
  const LOOKAHEAD_MS = 32;

  const resolveEndMs = (evs: PerformanceEventItem[]): number => {
    if (options?.getTotalDurationMs) {
      return Math.max(0, options.getTotalDurationMs());
    }
    return evs.length > 0
      ? Math.max(...evs.map((e) => e.at_ms + Math.max(200, e.hold_ms))) + 250
      : 0;
  };

  const initialEvents = getEvents();
  const initialEndMs = resolveEndMs(initialEvents);

  if (initialEndMs <= 0 || startMs >= initialEndMs) {
    callbacks.onEnded();
    return { stop: () => {}, seek: () => {} };
  }

  let stopped = false;
  let anchorMs = Math.max(0, startMs);
  let wallStart = performance.now();
  let scheduledUntilMs = anchorMs - 0.001;

  const timer = window.setInterval(() => {
    if (stopped) return;
    const elapsed = performance.now() - wallStart;
    const pos = anchorMs + elapsed;
    const windowEnd = pos + LOOKAHEAD_MS;
    const liveEvents = getEvents();
    const fixedVel = options?.getFixedVelocity
      ? options.getFixedVelocity()
      : Boolean(options?.fixedVelocity);
    const timbre: ResolvedTimbre = options?.getTimbre
      ? options.getTimbre()
      : options?.timbre ?? "piano";

    for (const ev of liveEvents) {
      if (ev.at_ms > scheduledUntilMs && ev.at_ms <= windowEnd) {
        const vel = fixedVel ? 96 : (ev.velocity ?? 92);
        const whenSec = ctx ? ctx.currentTime + Math.max(0, (ev.at_ms - pos) / 1000) : undefined;
        auditionMidiNote(ev.mapped_pitch, vel, ev.hold_ms, ctx, timbre, whenSec);
      }
    }
    scheduledUntilMs = windowEnd;

    const liveEndMs = resolveEndMs(liveEvents);
    callbacks.onTick(Math.round(pos));
    if (pos >= liveEndMs) {
      stopped = true;
      window.clearInterval(timer);
      callbacks.onEnded();
    }
  }, 20);

  return {
    stop: () => {
      if (stopped) return;
      stopped = true;
      window.clearInterval(timer);
    },
    seek: (ms: number) => {
      if (stopped) return;
      anchorMs = Math.max(0, ms);
      wallStart = performance.now();
      scheduledUntilMs = anchorMs - 0.001;
      callbacks.onTick(Math.round(anchorMs));
    },
  };
}
