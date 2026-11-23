"""Declarative specifications for the optional external toolchain.

LyraForge never bundles FFmpeg, Basic Pitch or dettato inside the portable ZIP: the
release stays small and the GPL/LGPL-adjacent binaries are installed only when the user
explicitly asks for them. This module defines *what* each tool is, where it comes from
and which license applies; :mod:`lyraforge.toolchain.installer` performs the install.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One installable external dependency."""

    id: str
    display_name: str
    license: str
    description: str
    kind: str  # "binary" (ffmpeg) or "python" (isolated virtualenv)
    download_mb: int
    env_var: str
    packages: tuple[str, ...] = ()
    probe_module: str = ""
    dist_name: str = ""
    wheel_package: str = ""


FFMPEG = ToolSpec(
    id="ffmpeg",
    display_name="FFmpeg",
    license="FFmpeg (LGPL/GPL build) · imageio-ffmpeg wheel is BSD-2-Clause",
    description="MP3/MP4/MKV/WebM 解码为 WAV；仅在你需要非 WAV 音频/视频时安装。",
    kind="binary",
    download_mb=40,
    env_var="LYRAFORGE_FFMPEG_BIN",
    wheel_package="imageio-ffmpeg",
)

BASIC_PITCH = ToolSpec(
    id="basic-pitch",
    display_name="Spotify Basic Pitch",
    license="Apache-2.0",
    description="多音/和弦转谱（TensorFlow），适合钢琴与流行歌主旋律。",
    kind="python",
    download_mb=700,
    env_var="LYRAFORGE_BASIC_PITCH_PYTHON",
    packages=("basic-pitch==0.4.0", "numpy<2", "setuptools<81"),
    probe_module="basic_pitch.predict",
    dist_name="basic-pitch",
)

DETTATO = ToolSpec(
    id="dettato",
    display_name="dettato 多乐器转录",
    license="Apache-2.0（代码与权重；部分辅助训练数据含非商用条款）",
    description="多声部/多乐器分轨转谱（PyTorch，CPU 可用；首次运行自动下载权重）。",
    kind="python",
    download_mb=450,
    env_var="LYRAFORGE_DETTATO_PYTHON",
    packages=("dettato==2.0.0",),
    probe_module="dettato",
    dist_name="dettato",
)

TOOL_SPECS: tuple[ToolSpec, ...] = (FFMPEG, BASIC_PITCH, DETTATO)


def tool_spec(tool_id: str) -> ToolSpec | None:
    for spec in TOOL_SPECS:
        if spec.id == tool_id:
            return spec
    return None


def tool_ids() -> tuple[str, ...]:
    return tuple(spec.id for spec in TOOL_SPECS)
