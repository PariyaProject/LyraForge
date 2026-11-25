import type { PerformanceEventItem } from "../api";

export type PreviewTimbre = "auto" | "piano" | "lyre" | "zither" | "vintage";
export type ResolvedTimbre = "piano" | "lyre" | "zither" | "vintage";

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

/**
 * Low-latency browser-side instrument audition for Piano Roll note clicks, drags, and draft play.
 * Defaults to piano (Harmonic Keys) and supports lyre, zither, and vintage voices.
 * Safe no-op in headless/test environments without Web Audio API.
 */
export function auditionMidiNote(
  pitch: number,
  velocity = 96,
  holdMs = 260,
  ctxOverride?: AudioContext | null,
  timbre: ResolvedTimbre = "piano",
): void {
  const ctx = ctxOverride ?? resolveAudioContext();
  if (!ctx) return;
  const now = ctx.currentTime;
  const freq = midiToHz(pitch);
  const amp = Math.max(0.03, Math.min(0.22, (velocity / 127) * 0.16));

  let attack = 0.008;
  let dur = Math.max(0.14, Math.min(1.4, holdMs / 1000 + 0.25));
  let startCutoff = Math.min(4800, freq * 4.5);
  let endCutoff = Math.max(520, freq * 1.4);
  let osc1Type: OscillatorType = "triangle";
  let osc2Mult = 2;
  let osc2GainStart = 0.28;
  let osc2Detune = 0;
  let osc3GainStart = 0;

  if (timbre === "piano") {
    const pitchNorm = Math.max(0, Math.min(1, (pitch - 48) / 36));
    attack = 0.004;
    dur = Math.max(0.45, Math.min(1.55, holdMs / 1000 + 0.95 - pitchNorm * 0.42));
    startCutoff = Math.min(6200, Math.max(1400, freq * 5.2));
    endCutoff = Math.max(480, freq * 1.6);
    osc1Type = "triangle";
    osc2Mult = 2;
    osc2GainStart = 0.36;
    osc2Detune = 2.2;
    osc3GainStart = 0.14;
  } else if (timbre === "zither") {
    attack = 0.003;
    dur = Math.max(0.3, Math.min(1.35, holdMs / 1000 + 0.45));
    startCutoff = Math.min(7200, freq * 7.0);
    endCutoff = Math.max(640, freq * 1.8);
    osc1Type = "sawtooth";
    osc2Mult = 2;
    osc2GainStart = 0.34;
    osc3GainStart = 0.2;
  } else if (timbre === "vintage") {
    attack = 0.012;
    dur = Math.max(0.18, Math.min(1.1, holdMs / 1000 + 0.2));
    startCutoff = Math.min(2600, freq * 2.6);
    endCutoff = Math.max(360, freq * 1.1);
    osc1Type = "sine";
    osc2Mult = 2;
    osc2GainStart = 0.18;
  }

  const master = ctx.createGain();
  master.gain.setValueAtTime(0.0001, now);
  master.gain.exponentialRampToValueAtTime(amp, now + attack);
  master.gain.exponentialRampToValueAtTime(0.0001, now + dur);

  const filter = ctx.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.setValueAtTime(startCutoff, now);
  filter.frequency.exponentialRampToValueAtTime(endCutoff, now + dur);

  const osc1 = ctx.createOscillator();
  osc1.type = osc1Type;
  osc1.frequency.setValueAtTime(freq, now);

  const osc2 = ctx.createOscillator();
  osc2.type = "sine";
  osc2.frequency.setValueAtTime(freq * osc2Mult, now);
  if (osc2Detune !== 0 && osc2.detune) {
    osc2.detune.setValueAtTime(osc2Detune, now);
  }
  const gain2 = ctx.createGain();
  gain2.gain.setValueAtTime(osc2GainStart, now);
  gain2.gain.exponentialRampToValueAtTime(0.015, now + dur * 0.5);

  osc1.connect(filter);
  osc2.connect(gain2);
  gain2.connect(filter);

  let osc3: OscillatorNode | null = null;
  if (osc3GainStart > 0) {
    osc3 = ctx.createOscillator();
    osc3.type = "sine";
    osc3.frequency.setValueAtTime(freq * 3, now);
    const gain3 = ctx.createGain();
    gain3.gain.setValueAtTime(osc3GainStart, now);
    gain3.gain.exponentialRampToValueAtTime(0.008, now + dur * 0.35);
    osc3.connect(gain3);
    gain3.connect(filter);
  }

  filter.connect(master);
  master.connect(ctx.destination);

  osc1.start(now);
  osc2.start(now);
  osc1.stop(now + dur + 0.02);
  osc2.stop(now + dur + 0.02);
  if (osc3) {
    osc3.start(now);
    osc3.stop(now + dur + 0.02);
  }
}

export interface DraftSequencer {
  stop: () => void;
  seek: (ms: number) => void;
}

/**
 * Play Piano Roll draft events directly in Web Audio, reading live edits/track filters
 * across a sliding time window and supporting instant seek without restarting.
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
  },
): DraftSequencer {
  const ctx = resolveAudioContext();
  const getEvents =
    typeof eventsOrGetter === "function" ? eventsOrGetter : () => eventsOrGetter;
  const LOOKAHEAD_MS = 28;

  const initialEvents = getEvents();
  const initialEndMs =
    initialEvents.length > 0
      ? Math.max(...initialEvents.map((e) => e.at_ms + Math.max(200, e.hold_ms))) + 250
      : 0;

  if (initialEvents.length === 0 || startMs >= initialEndMs) {
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
        auditionMidiNote(ev.mapped_pitch, vel, ev.hold_ms, ctx, timbre);
      }
    }
    scheduledUntilMs = windowEnd;

    const liveEndMs =
      liveEvents.length > 0
        ? Math.max(...liveEvents.map((e) => e.at_ms + Math.max(200, e.hold_ms))) + 250
        : pos;

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
