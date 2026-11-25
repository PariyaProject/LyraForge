import type { PerformanceEventItem } from "../api";

export type PreviewTimbre = "auto" | "piano" | "lyre" | "zither" | "vintage";
export type ResolvedTimbre = "piano" | "lyre" | "zither" | "vintage";

interface SampleManifestEntry {
  pitch: number;
  note: string;
  file: string;
  duration_ms?: number;
}

interface SampleManifest {
  packs: Record<string, SampleManifestEntry[]>;
}

interface DecodedAnchor {
  pitch: number;
  buffer: AudioBuffer;
}

interface ContextAudioState {
  masterInput: AudioNode;
  loadedPacks: Map<string, DecodedAnchor[]>;
  pendingPacks: Map<string, Promise<void>>;
}

let sharedCtx: AudioContext | null = null;
let sharedCtxCtor: unknown = null;
let sampleConfig: { base: string; token: string } | null = null;
let manifestPromise: Promise<SampleManifest | null> | null = null;
const ctxCache = new WeakMap<AudioContext, ContextAudioState>();

export function configurePreviewSampleBase(apiBase: string, token = ""): void {
  const normalizedBase = (apiBase ?? "").replace(/\/+$/, "");
  if (
    sampleConfig &&
    sampleConfig.base === normalizedBase &&
    sampleConfig.token === token
  ) {
    return;
  }
  sampleConfig = { base: normalizedBase, token };
  manifestPromise = null;
}

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

function createRoomImpulse(ctx: AudioContext): AudioBuffer | null {
  if (typeof ctx.createBuffer !== "function") return null;
  const sr = typeof ctx.sampleRate === "number" && ctx.sampleRate > 0 ? ctx.sampleRate : 44100;
  const length = Math.max(256, Math.round(sr * 0.34));
  const buf = ctx.createBuffer(2, length, sr);
  for (let ch = 0; ch < 2; ch += 1) {
    const data = buf.getChannelData(ch);
    let seed = 0x12345678 ^ (ch * 0x9e3779b9);
    for (let i = 0; i < length; i += 1) {
      // Deterministic PRNG warm hall tail (zero network or audio glitches)
      seed = (seed * 1664525 + 1013904223) >>> 0;
      const white = (seed / 0x100000000) * 2 - 1;
      const env = Math.exp((-6.8 * i) / length);
      const earlyBoost = i < sr * 0.025 ? 0.55 : 0.35;
      data[i] = white * env * earlyBoost;
    }
  }
  return buf;
}

function getContextState(ctx: AudioContext): ContextAudioState {
  const existing = ctxCache.get(ctx);
  if (existing) return existing;

  const masterBus = ctx.createGain();
  masterBus.gain.setValueAtTime(0.88, ctx.currentTime);

  let outputNode: AudioNode = masterBus;
  if (typeof ctx.createDynamicsCompressor === "function") {
    try {
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.setValueAtTime(-14, ctx.currentTime);
      comp.knee.setValueAtTime(18, ctx.currentTime);
      comp.ratio.setValueAtTime(3.8, ctx.currentTime);
      comp.attack.setValueAtTime(0.004, ctx.currentTime);
      comp.release.setValueAtTime(0.14, ctx.currentTime);
      masterBus.connect(comp);
      comp.connect(ctx.destination);
      outputNode = masterBus;
    } catch {
      masterBus.connect(ctx.destination);
    }
  } else {
    masterBus.connect(ctx.destination);
  }

  // Subtle room warmth so chords blend naturally instead of sounding dry/choked
  if (
    typeof ctx.createConvolver === "function" &&
    typeof ctx.createBuffer === "function"
  ) {
    try {
      const impulse = createRoomImpulse(ctx);
      if (impulse) {
        const convolver = ctx.createConvolver();
        convolver.buffer = impulse;
        const wet = ctx.createGain();
        wet.gain.setValueAtTime(0.13, ctx.currentTime);
        const inputSplitter = ctx.createGain();
        inputSplitter.gain.setValueAtTime(1.0, ctx.currentTime);
        inputSplitter.connect(outputNode);
        inputSplitter.connect(wet);
        wet.connect(convolver);
        convolver.connect(outputNode);
        outputNode = inputSplitter;
      }
    } catch {
      // Ignore convolver failures on constrained webviews
    }
  }

  const state: ContextAudioState = {
    masterInput: outputNode,
    loadedPacks: new Map(),
    pendingPacks: new Map(),
  };
  ctxCache.set(ctx, state);
  return state;
}

function packForTimbre(timbre: ResolvedTimbre): "piano" | "lyre" | "zither" {
  if (timbre === "piano") return "piano";
  if (timbre === "zither") return "zither";
  return "lyre";
}

async function fetchManifest(): Promise<SampleManifest | null> {
  if (!sampleConfig || typeof fetch !== "function") return null;
  if (manifestPromise) return manifestPromise;
  const headers: Record<string, string> = {};
  if (sampleConfig.token) {
    headers["X-LyraForge-Token"] = sampleConfig.token;
  }
  manifestPromise = fetch(`${sampleConfig.base}/v1/preview/samples/manifest`, { headers })
    .then(async (resp) => {
      if (!resp.ok) return null;
      return (await resp.json()) as SampleManifest;
    })
    .catch(() => null);
  return manifestPromise;
}

export async function preloadPreviewSamples(
  timbre: ResolvedTimbre = "piano",
  ctxOverride?: AudioContext | null,
): Promise<void> {
  const ctx = ctxOverride ?? resolveAudioContext();
  if (!ctx || !sampleConfig || typeof fetch !== "function" || typeof ctx.decodeAudioData !== "function") {
    return;
  }
  const pack = packForTimbre(timbre);
  const state = getContextState(ctx);
  if (state.loadedPacks.has(pack)) return;
  const inflight = state.pendingPacks.get(pack);
  if (inflight) {
    await inflight;
    return;
  }

  const cfg = sampleConfig;
  const job = (async () => {
    const manifest = await fetchManifest();
    const entries = manifest?.packs?.[pack];
    if (!Array.isArray(entries) || entries.length === 0) return;

    const headers: Record<string, string> = {};
    if (cfg.token) {
      headers["X-LyraForge-Token"] = cfg.token;
    }

    const decoded: DecodedAnchor[] = [];
    await Promise.all(
      entries.map(async (entry) => {
        const segs = String(entry.file).split("/");
        const packSeg = encodeURIComponent(segs[0] ?? pack);
        const fileSeg = encodeURIComponent(segs[segs.length - 1] ?? "");
        if (!fileSeg) return;
        try {
          const resp = await fetch(`${cfg.base}/v1/preview/samples/${packSeg}/${fileSeg}`, { headers });
          if (!resp.ok) return;
          const rawBuf = await resp.arrayBuffer();
          const audioBuf = await ctx.decodeAudioData(rawBuf);
          decoded.push({ pitch: entry.pitch, buffer: audioBuf });
        } catch {
          // Non-fatal: partial anchors still shift cleanly
        }
      }),
    );

    if (decoded.length > 0) {
      decoded.sort((a, b) => a.pitch - b.pitch);
      state.loadedPacks.set(pack, decoded);
    }
  })();

  state.pendingPacks.set(pack, job);
  try {
    await job;
  } finally {
    state.pendingPacks.delete(pack);
  }
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

function auditionWithSampleBuffer(
  ctx: AudioContext,
  state: ContextAudioState,
  anchors: DecodedAnchor[],
  pitch: number,
  velocity: number,
  holdMs: number,
  timbre: ResolvedTimbre,
  startTime: number,
): boolean {
  if (anchors.length === 0 || typeof ctx.createBufferSource !== "function") return false;
  let best = anchors[0];
  let bestDist = Math.abs(pitch - best.pitch);
  for (let i = 1; i < anchors.length; i += 1) {
    const dist = Math.abs(pitch - anchors[i].pitch);
    if (dist < bestDist) {
      best = anchors[i];
      bestDist = dist;
    }
  }

  const src = ctx.createBufferSource();
  src.buffer = best.buffer;
  const rate = Math.pow(2, (pitch - best.pitch) / 12);
  src.playbackRate.setValueAtTime(rate, startTime);

  const naturalDurS = Math.min(
    best.buffer.duration / Math.max(0.25, rate),
    timbre === "piano"
      ? Math.max(1.25, holdMs / 1000 + 1.0)
      : timbre === "lyre"
        ? Math.max(1.05, holdMs / 1000 + 0.8)
        : Math.max(0.88, holdMs / 1000 + 0.62),
  );

  const noteGain = ctx.createGain();
  const amp = Math.max(0.08, Math.min(0.62, (velocity / 127) * 0.48));
  noteGain.gain.setValueAtTime(amp, startTime);
  const fadeStart = Math.max(startTime + 0.04, startTime + naturalDurS - 0.12);
  noteGain.gain.setValueAtTime(amp, fadeStart);
  noteGain.gain.exponentialRampToValueAtTime(0.0005, startTime + naturalDurS);

  if (timbre === "vintage" && typeof ctx.createBiquadFilter === "function") {
    const warmFilter = ctx.createBiquadFilter();
    warmFilter.type = "lowpass";
    warmFilter.frequency.setValueAtTime(1850, startTime);
    src.connect(warmFilter);
    warmFilter.connect(noteGain);
  } else {
    src.connect(noteGain);
  }

  noteGain.connect(state.masterInput);
  src.start(startTime);
  src.stop(startTime + naturalDurS + 0.03);
  return true;
}

/**
 * Low-latency browser-side instrument audition for Piano Roll note clicks, drags, and draft play.
 * Uses real bundled CC0 acoustic samples (Steinway B Grand Piano, Concert Harp, Dan Tranh Zither)
 * through a soft compressor + room ambience bus, with a clean sine-harmonic fallback for tests.
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
  const pack = packForTimbre(timbre);
  const anchors = state.loadedPacks.get(pack);

  if (anchors && auditionWithSampleBuffer(ctx, state, anchors, pitch, velocity, holdMs, timbre, startTime)) {
    return;
  }

  if (sampleConfig && typeof ctx.decodeAudioData === "function" && typeof fetch === "function") {
    void preloadPreviewSamples(timbre, ctx);
  }

  // Clean, warm sine-harmonic fallback (no harsh sawtooth buzzers) for test mocks & pre-load ticks
  const freq = midiToHz(pitch);
  const amp = Math.max(0.03, Math.min(0.24, (velocity / 127) * 0.17));
  const pitchNorm = Math.max(0, Math.min(1, (pitch - 48) / 36));
  const attack = timbre === "piano" ? 0.004 : timbre === "vintage" ? 0.01 : 0.006;
  const dur =
    timbre === "piano"
      ? Math.max(0.45, Math.min(1.5, holdMs / 1000 + 0.9 - pitchNorm * 0.38))
      : timbre === "vintage"
        ? Math.max(0.24, Math.min(1.1, holdMs / 1000 + 0.35))
        : Math.max(0.26, Math.min(1.25, holdMs / 1000 + 0.45));
  const startCutoff =
    timbre === "vintage"
      ? Math.min(2200, freq * 2.4)
      : Math.min(5400, Math.max(1200, freq * 4.4));
  const endCutoff = Math.max(380, freq * 1.25);

  const master = ctx.createGain();
  master.gain.setValueAtTime(0.0001, startTime);
  master.gain.exponentialRampToValueAtTime(amp, startTime + attack);
  master.gain.exponentialRampToValueAtTime(0.0001, startTime + dur);

  const filter = ctx.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.setValueAtTime(startCutoff, startTime);
  filter.frequency.exponentialRampToValueAtTime(endCutoff, startTime + dur);

  const osc1 = ctx.createOscillator();
  osc1.type = "sine";
  osc1.frequency.setValueAtTime(freq, startTime);

  const osc2 = ctx.createOscillator();
  osc2.type = "sine";
  osc2.frequency.setValueAtTime(freq * 2, startTime);
  const gain2 = ctx.createGain();
  gain2.gain.setValueAtTime(timbre === "piano" ? 0.28 : 0.22, startTime);
  gain2.gain.exponentialRampToValueAtTime(0.01, startTime + dur * 0.45);

  const osc3 = ctx.createOscillator();
  osc3.type = "sine";
  osc3.frequency.setValueAtTime(freq * 3, startTime);
  const gain3 = ctx.createGain();
  gain3.gain.setValueAtTime(timbre === "vintage" ? 0.04 : 0.1, startTime);
  gain3.gain.exponentialRampToValueAtTime(0.005, startTime + dur * 0.3);

  osc1.connect(filter);
  osc2.connect(gain2);
  gain2.connect(filter);
  osc3.connect(gain3);
  gain3.connect(filter);

  filter.connect(master);
  master.connect(state.masterInput);

  osc1.start(startTime);
  osc2.start(startTime);
  osc3.start(startTime);
  osc1.stop(startTime + dur + 0.02);
  osc2.stop(startTime + dur + 0.02);
  osc3.stop(startTime + dur + 0.02);
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

  const initialTimbre: ResolvedTimbre = options?.getTimbre
    ? options.getTimbre()
    : options?.timbre ?? "piano";
  if (ctx && sampleConfig && typeof ctx.decodeAudioData === "function" && typeof fetch === "function") {
    void preloadPreviewSamples(initialTimbre, ctx);
  }

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
