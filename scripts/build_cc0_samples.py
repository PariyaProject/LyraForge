"""Build compact CC0-1.0 acoustic preview samples from pinned VCSL commits.

Usage:
    uv run python scripts/build_cc0_samples.py
"""

from __future__ import annotations

import array
import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Any

VCSL_REPO = "https://github.com/sgossner/VCSL"
VCSL_COMMIT = "c1ea7bcc3c7309650ab0da9d15c9cd1fbc4a4c7e"
TARGET_SR = 22_050

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "src" / "lyraforge" / "preview" / "samples"

SampleSpec = tuple[int, str, str, str]  # (midi_pitch, note_name, out_filename, repo_rel_path)

_PIANO_BASE = "Chordophones/Zithers/Grand Piano, Steinway B/Sus"
_HARP_BASE = "Chordophones/Composite Chordophones/Concert Harp"
_DAN_BASE = "Chordophones/Zithers/Dan Tranh/Normal"

PACK_SPECS: dict[str, tuple[float, float, tuple[SampleSpec, ...]]] = {
    # (duration_s, target_peak, anchors)
    "piano": (
        1.80,
        0.85,
        (
            (48, "C3", "48_C3.wav", f"{_PIANO_BASE}/JHPiano_Sus_Close_C3_vl3_rr1.wav"),
            (52, "E3", "52_E3.wav", f"{_PIANO_BASE}/JHPiano_Sus_Close_E3_vl3_rr1.wav"),
            (56, "G#3", "56_Gs3.wav", f"{_PIANO_BASE}/JHPiano_Sus_Close_G#3_vl3_rr1.wav"),
            (60, "C4", "60_C4.wav", f"{_PIANO_BASE}/JHPiano_Sus_Close_C4_vl3_rr1.wav"),
            (64, "E4", "64_E4.wav", f"{_PIANO_BASE}/JHPiano_Sus_Close_E4_vl3_rr1.wav"),
            (68, "G#4", "68_Gs4.wav", f"{_PIANO_BASE}/JHPiano_Sus_Close_G#4_vl3_rr1.wav"),
            (72, "C5", "72_C5.wav", f"{_PIANO_BASE}/JHPiano_Sus_Close_C5_vl3_rr1.wav"),
            (76, "E5", "76_E5.wav", f"{_PIANO_BASE}/JHPiano_Sus_Close_E5_vl3_rr1.wav"),
            (82, "A#5", "82_As5.wav", f"{_PIANO_BASE}/JHPiano_Sus_Close_A#5_vl3_rr1.wav"),
        ),
    ),
    "lyre": (
        1.60,
        0.85,
        (
            (48, "C3", "48_C3.wav", f"{_HARP_BASE}/KSHarp_C3_mf3.wav"),
            (55, "G3", "55_G3.wav", f"{_HARP_BASE}/KSHarp_G3_mf1.wav"),
            (62, "D4", "62_D4.wav", f"{_HARP_BASE}/KSHarp_D4_mf1.wav"),
            (69, "A4", "69_A4.wav", f"{_HARP_BASE}/KSHarp_A4_mf1.wav"),
            (76, "E5", "76_E5.wav", f"{_HARP_BASE}/KSHarp_E5_mf1.wav"),
            (83, "B5", "83_B5.wav", f"{_HARP_BASE}/KSHarp_B5_mf1.wav"),
        ),
    ),
    "zither": (
        1.30,
        0.82,
        (
            (49, "C#3", "49_Cs3.wav", f"{_DAN_BASE}/C#3_mf_1.wav"),
            (54, "F#3", "54_Fs3.wav", f"{_DAN_BASE}/F#3_mf_1.wav"),
            (59, "B3", "59_B3.wav", f"{_DAN_BASE}/B3_mf_1.wav"),
            (63, "D#4", "63_Ds4.wav", f"{_DAN_BASE}/D#4_mf_1.wav"),
            (68, "G#4", "68_Gs4.wav", f"{_DAN_BASE}/G#4_mf_1.wav"),
        ),
    ),
}


def _raw_url(rel_path: str) -> str:
    quoted = "/".join(urllib.parse.quote(seg, safe="") for seg in rel_path.split("/"))
    owner_repo = VCSL_REPO.split("github.com/")[1]
    return f"https://raw.githubusercontent.com/{owner_repo}/{VCSL_COMMIT}/{quoted}"


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "LyraForge-SampleBuilder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        dest.write_bytes(resp.read())


def _read_wav_mono_float(path: Path, tmp_dir: Path) -> list[float]:
    """Decode arbitrary WAV (including 24-bit PCM / float32) to mono float at TARGET_SR."""
    converted = tmp_dir / f"{path.stem}.pcm16.wav"
    afconvert = shutil.which("afconvert")
    src = path
    if afconvert:
        cmd = [
            afconvert,
            "-f",
            "WAVE",
            "-d",
            f"LEI16@{TARGET_SR}",
            "-c",
            "1",
            str(path),
            str(converted),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        src = converted

    with wave.open(str(src), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if sw == 2:
        arr = array.array("h")
        arr.frombytes(raw)
        if sys.byteorder != "little":
            arr.byteswap()
        mono: list[float] = []
        if ch == 1:
            mono = [s / 32768.0 for s in arr]
        else:
            for i in range(0, len(arr), ch):
                mono.append(sum(arr[i : i + ch]) / (ch * 32768.0))
    elif sw == 3:
        mono = []
        step = 3 * ch
        for i in range(0, len(raw) - step + 1, step):
            acc = 0.0
            for c in range(ch):
                b0, b1, b2 = raw[i + c * 3 : i + c * 3 + 3]
                val = b0 | (b1 << 8) | (b2 << 16)
                if val & 0x800000:
                    val -= 0x1000000
                acc += val / 8388608.0
            mono.append(acc / ch)
    elif sw == 4:
        mono = []
        vals = struct.unpack(f"<{len(raw) // 4}i", raw)
        for i in range(0, len(vals), ch):
            mono.append(sum(vals[i : i + ch]) / (ch * 2147483648.0))
    else:
        raise RuntimeError(f"Unsupported WAV sample width {sw} bytes in {path}")

    if sr != TARGET_SR and len(mono) > 1:
        ratio = sr / TARGET_SR
        out_len = max(1, int(round(len(mono) / ratio)))
        resampled = [0.0] * out_len
        for idx in range(out_len):
            pos = idx * ratio
            i0 = int(pos)
            frac = pos - i0
            i1 = min(i0 + 1, len(mono) - 1)
            resampled[idx] = mono[i0] * (1.0 - frac) + mono[i1] * frac
        mono = resampled

    return mono


def _process_sample(samples: list[float], duration_s: float, target_peak: float) -> list[int]:
    if not samples:
        raise ValueError("Empty sample buffer")
    peak_raw = max(abs(x) for x in samples)
    if peak_raw <= 1e-6:
        raise ValueError("Silent sample buffer")

    # Trim leading silence at -42 dB relative to sample peak, preserving 1.5 ms pre-roll
    thresh = peak_raw * (10.0 ** (-42.0 / 20.0))
    onset_idx = 0
    for idx, val in enumerate(samples):
        if abs(val) >= thresh:
            onset_idx = idx
            break
    preroll = int(round(0.0015 * TARGET_SR))
    start_idx = max(0, onset_idx - preroll)

    max_len = int(round(duration_s * TARGET_SR))
    trimmed = samples[start_idx : start_idx + max_len]
    if len(trimmed) < 128:
        raise ValueError(f"Trimmed sample too short ({len(trimmed)} frames)")

    # Remove small DC offset
    dc = sum(trimmed) / len(trimmed)
    trimmed = [x - dc for x in trimmed]

    # Normalize peak consistently
    peak = max(abs(x) for x in trimmed)
    scale = (target_peak / peak) if peak > 1e-9 else 1.0
    out = [x * scale for x in trimmed]

    # 1.5 ms smooth cosine fade-in
    fade_in = min(len(out) // 8, max(8, int(round(0.0015 * TARGET_SR))))
    for i in range(fade_in):
        out[i] *= 0.5 * (1.0 - math.cos(math.pi * i / fade_in))

    # 220 ms smooth cosine fade-out at end of slice
    fade_out = min(len(out) // 2, int(round(0.220 * TARGET_SR)))
    tail_start = len(out) - fade_out
    for i in range(fade_out):
        out[tail_start + i] *= 0.5 * (1.0 + math.cos(math.pi * i / fade_out))

    return [max(-32767, min(32767, int(round(x * 32767.0)))) for x in out]


def _write_pcm16_wav(path: Path, pcm_ints: list[int]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = array.array("h", pcm_ints)
    if sys.byteorder != "little":
        arr.byteswap()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TARGET_SR)
        wf.writeframes(arr.tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    packs_manifest: dict[str, list[dict[str, Any]]] = {}
    total_bytes = 0

    with tempfile.TemporaryDirectory(prefix="vcsl_dl_") as tmp_str:
        tmp_dir = Path(tmp_str)
        for pack_name, (duration_s, target_peak, specs) in PACK_SPECS.items():
            pack_entries: list[dict[str, Any]] = []
            for pitch, note_name, out_name, rel_path in specs:
                url = _raw_url(rel_path)
                raw_dl = tmp_dir / f"{pack_name}_{out_name}"
                print(f"Downloading {pack_name}/{out_name} <- {rel_path}")
                _download(url, raw_dl)
                floats = _read_wav_mono_float(raw_dl, tmp_dir)
                pcm_ints = _process_sample(floats, duration_s, target_peak)
                dest_path = OUT_DIR / pack_name / out_name
                digest = _write_pcm16_wav(dest_path, pcm_ints)
                size_bytes = dest_path.stat().st_size
                total_bytes += size_bytes
                pack_entries.append(
                    {
                        "pitch": pitch,
                        "note": note_name,
                        "file": f"{pack_name}/{out_name}",
                        "sha256": digest,
                        "duration_ms": int(round(len(pcm_ints) * 1000.0 / TARGET_SR)),
                    }
                )
            packs_manifest[pack_name] = pack_entries

    manifest = {
        "version": 1,
        "sample_rate": TARGET_SR,
        "license": "CC0-1.0",
        "source_repo": VCSL_REPO,
        "source_commit": VCSL_COMMIT,
        "attribution": (
            "Versilian Community Sample Library (VCSL) by Sam Gossner, "
            "CC0 1.0 Universal Public Domain Dedication."
        ),
        "packs": packs_manifest,
    }
    manifest_path = OUT_DIR / "manifest.json"
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    manifest_path.write_text(text, encoding="utf-8")
    total_bytes += manifest_path.stat().st_size
    print(f"Built CC0 sample library at {OUT_DIR} ({total_bytes / 1024.0:.1f} KiB total)")


if __name__ == "__main__":
    main()
