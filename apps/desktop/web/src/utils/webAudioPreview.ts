import type { PerformanceEventItem } from "../api";

export type PreviewTimbre = "auto" | "piano" | "lyre" | "zither" | "vintage";
export type ResolvedTimbre = "piano" | "lyre" | "zither" | "vintage";

interface ActiveVoice {
  gain: GainNode;
  nodes: AudioNode[];
  oscs: OscillatorNode[];
  startSec: number;
  endSec: number;
  amp: number;
  decayDur: number;
  ended?: boolean;
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
  masterBus.gain.setValueAtTime(0.85, ctx.currentTime);

  // Transparent peak safety guard for heavy multi-track chords (zero gain pumping on solo phrases)
  if (typeof ctx.createDynamicsCompressor === "function") {
    try {
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.setValueAtTime(-2, ctx.currentTime);
      comp.knee.setValueAtTime(12, ctx.currentTime);
      comp.ratio.setValueAtTime(2.0, ctx.currentTime);
      comp.attack.setValueAtTime(0.006, ctx.currentTime);
      comp.release.setValueAtTime(0.14, ctx.currentTime);
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
  // Genshin instruments behave as one-shot plucks/strikes with rich natural sustain tails
  // even when key holds are brief, while same-pitch restrikes cut and restart cleanly.
  if (timbre === "piano") {
    return {
      attackS: 0.004,
      decayDur: Math.max(1.35, Math.min(2.25, 2.15 - pitchNorm * 0.72 + holdS * 0.25)),
      h2Gain: Math.max(0.14, 0.34 - pitchNorm * 0.14),
      h3Gain: Math.max(0.04, 0.12 - pitchNorm * 0.06),
      h4Gain: Math.max(0.0, 0.04 - pitchNorm * 0.03),
      startFilterMult: 3.6,
      endFilterMult: 1.3,
      baseLevel: 0.16,
    };
  }
  if (timbre === "zither") {
    return {
      attackS: 0.003,
      decayDur: Math.max(0.9, Math.min(1.45, 1.35 - pitchNorm * 0.36 + holdS * 0.18)),
      h2Gain: Math.max(0.16, 0.35 - pitchNorm * 0.12),
      h3Gain: Math.max(0.05, 0.14 - pitchNorm * 0.06),
      h4Gain: 0.045,
      startFilterMult: 3.9,
      endFilterMult: 1.4,
      baseLevel: 0.155,
    };
  }
  if (timbre === "vintage") {
    return {
      attackS: 0.007,
      decayDur: Math.max(0.85, Math.min(1.32, 1.24 - pitchNorm * 0.3 + holdS * 0.15)),
      h2Gain: 0.18,
      h3Gain: 0.04,
      h4Gain: 0.0,
      startFilterMult: 2.3,
      endFilterMult: 1.15,
      baseLevel: 0.155,
    };
  }
  // Windsong Lyre: clear crystal plucked strings with natural singing tail
  return {
    attackS: 0.005,
    decayDur: Math.max(1.0, Math.min(1.65, 1.55 - pitchNorm * 0.45 + holdS * 0.2)),
    h2Gain: 0.28 - pitchNorm * 0.08,
    h3Gain: 0.1 - pitchNorm * 0.04,
    h4Gain: 0.025,
    startFilterMult: 3.4,
    endFilterMult: 1.25,
    baseLevel: 0.155,
  };
}

function dampVoiceAt(voice: ActiveVoice, cutSec: number, fadeSec = 0.011): void {
  const g = voice.gain.gain as unknown as Record<string, unknown>;
  const startCut = Math.max(voice.startSec, cutSec);
  if (typeof g.cancelAndHoldAtTime === "function") {
    try {
      (g.cancelAndHoldAtTime as (t: number) => void)(startCut);
    } catch {
      // ignore if unsupported/out-of-range in test mock
    }
  } else if (typeof g.cancelScheduledValues === "function") {
    const elapsed = Math.max(0, startCut - voice.startSec);
    const decayFrac = Math.min(1, elapsed / Math.max(0.05, voice.decayDur));
    const est = Math.max(
      0.0002,
      voice.amp * Math.pow(0.0008 / Math.max(voice.amp, 0.001), decayFrac),
    );
    try {
      (g.cancelScheduledValues as (t: number) => void)(startCut);
      if (typeof g.setValueAtTime === "function") {
        (g.setValueAtTime as (v: number, t: number) => void)(est, startCut);
      }
    } catch {
      // ignore in minimal mock
    }
  }

  const dampEnd = startCut + fadeSec;
  if (typeof g.linearRampToValueAtTime === "function") {
    try {
      (g.linearRampToValueAtTime as (v: number, t: number) => void)(0, dampEnd);
    } catch {
      if (typeof g.exponentialRampToValueAtTime === "function") {
        (g.exponentialRampToValueAtTime as (v: number, t: number) => void)(0.0001, dampEnd);
      }
    }
  } else if (typeof g.exponentialRampToValueAtTime === "function") {
    (g.exponentialRampToValueAtTime as (v: number, t: number) => void)(0.0001, dampEnd);
  }

  for (const osc of voice.oscs) {
    if (typeof osc.stop === "function") {
      try {
        osc.stop(dampEnd + 0.004);
      } catch {
        // ignore already stopped/scheduled mock oscillators
      }
    }
  }
}

/** Smoothly fade out any currently ringing audition notes to prevent stop/seek clicks. */
export function stopAllAuditionVoices(ctxOverride?: AudioContext | null): void {
  const ctx = ctxOverride ?? sharedCtx;
  if (!ctx) return;
  const state = ctxCache.get(ctx);
  if (!state || state.activeVoices.size === 0) return;
  const nowSec = ctx.currentTime;
  for (const voice of state.activeVoices.values()) {
    if (!voice.ended) {
      dampVoiceAt(voice, nowSec, 0.018);
      voice.ended = true;
    }
  }
  state.activeVoices.clear();
}

/**
 * Low-latency browser-side instrument audition for Piano Roll note clicks, drags, and draft play.
 * Uses pure-tuned studio additive sine synthesis, click-free same-pitch replacement, and zero white noise.
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
  const leadSec = ctxOverride ? 0 : 0.008;
  const startTime =
    whenSec !== undefined ? Math.max(ctx.currentTime, whenSec) : ctx.currentTime + leadSec;
  const state = getContextState(ctx);
  const roundedPitch = Math.round(pitch);

  // Genshin same-key retrigger: prior note tail sings continuously until new onset, then damps click-free
  const prevVoice = state.activeVoices.get(roundedPitch);
  if (prevVoice && !prevVoice.ended && startTime < prevVoice.endSec) {
    dampVoiceAt(prevVoice, startTime, 0.011);
    prevVoice.ended = true;
  }

  const pitchNorm = Math.max(0, Math.min(1, (pitch - 48) / 36));
  const pitchLevel = 0.86 + 0.16 * pitchNorm;
  const spec = voiceSpecForTimbre(timbre, pitchNorm, holdMs);
  const freq = midiToHz(pitch);
  const amp = Math.max(0.03, Math.min(0.21, (velocity / 127) * spec.baseLevel * pitchLevel));
  const dur = spec.decayDur;

  const master = ctx.createGain();
  const masterGainParam = master.gain as unknown as Record<string, unknown>;
  if (typeof masterGainParam.linearRampToValueAtTime === "function") {
    master.gain.setValueAtTime(0, startTime);
    master.gain.linearRampToValueAtTime(amp, startTime + spec.attackS);
    master.gain.exponentialRampToValueAtTime(
      0.0008,
      startTime + Math.max(spec.attackS + 0.06, dur - 0.03),
    );
    master.gain.linearRampToValueAtTime(0, startTime + dur);
  } else {
    master.gain.setValueAtTime(0.0001, startTime);
    master.gain.exponentialRampToValueAtTime(amp, startTime + spec.attackS);
    master.gain.exponentialRampToValueAtTime(0.0001, startTime + dur);
  }

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

  const trackedNodes: AudioNode[] = [master, filter];
  const trackedOscs: OscillatorNode[] = [osc1];

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
    trackedNodes.push(g2);
    trackedOscs.push(osc2);
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
    trackedNodes.push(g3);
    trackedOscs.push(osc3);
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
    trackedNodes.push(g4);
    trackedOscs.push(osc4);
  }

  filter.connect(master);
  master.connect(state.masterInput);

  const voice: ActiveVoice = {
    gain: master,
    nodes: trackedNodes,
    oscs: trackedOscs,
    startSec: startTime,
    endSec: startTime + dur,
    amp,
    decayDur: dur,
  };
  state.activeVoices.set(roundedPitch, voice);

  try {
    osc1.onended = () => {
      voice.ended = true;
      if (state.activeVoices.get(roundedPitch) === voice) {
        state.activeVoices.delete(roundedPitch);
      }
      for (const node of voice.nodes) {
        const maybeDisconnect = (node as unknown as { disconnect?: () => void }).disconnect;
        if (typeof maybeDisconnect === "function") {
          try {
            maybeDisconnect.call(node);
          } catch {
            // already disconnected
          }
        }
      }
    };
  } catch {
    // ignore read-only mock properties
  }
}

export interface DraftSequencer {
  stop: () => void;
  seek: (ms: number) => void;
}

/**
 * Play Piano Roll draft events directly in Web Audio, reading live edits/track filters
 * across a hardware-clock-locked 120 ms lookahead window without UI-thread audio jitter.
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
  const LOOKAHEAD_MS = 120;
  const SAFETY_LEAD_SEC = 0.025;

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
  let audioStartSec = ctx ? ctx.currentTime : 0;
  let audioAnchorSec = audioStartSec + SAFETY_LEAD_SEC;
  let scheduledUntilMs = anchorMs - 0.001;

  const timer = window.setInterval(() => {
    if (stopped) return;
    const wallElapsed = performance.now() - wallStart;
    const audioElapsed = ctx ? (ctx.currentTime - audioStartSec) * 1000 : 0;
    // Prefer hardware AudioContext clock in real browsers; fall back cleanly for static-time test mocks
    const useAudioClock = Boolean(ctx && audioElapsed > 1);
    const elapsed = useAudioClock ? audioElapsed : wallElapsed;
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
        const whenSec = ctx
          ? useAudioClock
            ? Math.max(ctx.currentTime + 0.005, audioAnchorSec + (ev.at_ms - anchorMs) / 1000)
            : ctx.currentTime + Math.max(0.005, (ev.at_ms - pos) / 1000)
          : undefined;
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
  }, 25);

  return {
    stop: () => {
      if (stopped) return;
      stopped = true;
      window.clearInterval(timer);
      stopAllAuditionVoices(ctx);
    },
    seek: (ms: number) => {
      if (stopped) return;
      stopAllAuditionVoices(ctx);
      anchorMs = Math.max(0, ms);
      wallStart = performance.now();
      if (ctx) {
        audioStartSec = ctx.currentTime;
        audioAnchorSec = audioStartSec + SAFETY_LEAD_SEC;
      }
      scheduledUntilMs = anchorMs - 0.001;
      callbacks.onTick(Math.round(anchorMs));
    },
  };
}
