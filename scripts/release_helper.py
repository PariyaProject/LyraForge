"""CI packaging, ZIP/SHA256 validation, and idempotent GitHub Release helper (stdlib-only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROLLING_DEV_TAG = "dev-latest"
DEFAULT_ARCH = "windows-x64"
DEFAULT_MACOS_ARCH = "macos-arm64"
DEFAULT_REPO = "PariyaProject/LyraForge"
CHECKSUMS_FILENAME = "SHA256SUMS.txt"
METADATA_FILENAME = "release-meta.json"
PORTABLE_README_FILENAME = "README.txt"

PORTABLE_README_TEXT = """\
LyraForge - Portable Windows build
==================================

1. Extract this whole ZIP into a folder you can write to
   (for example %LOCALAPPDATA%\\Programs\\LyraForge).
2. Keep LyraForge.exe next to the _internal folder, and do not start the EXE from
   inside the ZIP preview window.
3. Start LyraForge.exe. The desktop workbench window opens after a few seconds.
4. The Microsoft Edge WebView2 Runtime is required (preinstalled on Windows 11; on
   Windows 10 install the Evergreen Runtime from Microsoft).

This is an experimental pre-release build unless the release title says otherwise:
live Genshin Impact playback verification is still pending.

If no window appears, open the startup log and attach it to a GitHub issue:
  %LOCALAPPDATA%\\LyraForge\\logs\\startup.log

License: GNU General Public License v3.0 (see LICENSE).
"""

PORTABLE_MACOS_README_TEXT = """\
LyraForge - Portable macOS (Apple Silicon) build
================================================

1. Extract this ZIP (`unzip` or double-click in Finder) and drag `LyraForge.app`
   into `/Applications` or any writable folder.
2. This experimental build is ad-hoc signed without Apple notarization. On first launch:
   Right-click (or Control-click) `LyraForge.app` -> Open, OR run in Terminal:
     xattr -dr com.apple.quarantine LyraForge.app
3. macOS supports full MIDI/audio import, transcription, Piano Roll arrangement,
   offline preview WAV synthesis, local library backups, and MCP integration.
   In-game OS keyboard automation runs in virtual DryRun simulation mode on macOS.

License: GNU General Public License v3.0 (see LICENSE).
"""

SEMVER_TAG_RE = re.compile(
    r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
DEV_SNAPSHOT_TAG_RE = re.compile(r"^dev-\d{8}-[0-9a-f]{7,40}$")
_FORBIDDEN_ZIP_FILENAMES = frozenset({".lyraforge.secrets.json", ".env"})

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def default_run_cmd(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), text=True, capture_output=True, check=False)


def is_semver_tag(tag: str) -> bool:
    return SEMVER_TAG_RE.match(tag) is not None


@dataclass(frozen=True, slots=True)
class ReleasePlan:
    should_publish: bool
    channel: str  # "dev" | "semver" | "none"
    prerelease: bool
    build_version: str
    snapshot_tag: str | None
    rolling_tag: str | None
    zip_name: str
    checksums_name: str
    arch: str
    sha: str
    sha7: str
    commit_date_yyyymmdd: str
    build_timestamp_utc: str
    event_name: str
    ref: str
    reason: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def resolve_release_plan(
    *,
    event_name: str,
    ref: str,
    sha: str,
    commit_date_yyyymmdd: str,
    build_timestamp_utc: str,
    arch: str = DEFAULT_ARCH,
) -> ReleasePlan:
    """Resolve deterministic artifact naming and release policy from GitHub context."""
    clean_sha = sha.strip().lower()
    sha7 = clean_sha[:7] or "unknown"
    clean_date = commit_date_yyyymmdd.strip()
    if not re.fullmatch(r"\d{8}", clean_date):
        raise ValueError(f"commit_date_yyyymmdd must be YYYYMMDD, got {commit_date_yyyymmdd!r}")

    allowed_events = {"push", "workflow_dispatch"}
    if event_name in allowed_events and ref == "refs/heads/main":
        build_ver = f"dev-{clean_date}-{sha7}"
        return ReleasePlan(
            should_publish=True,
            channel="dev",
            prerelease=True,
            build_version=build_ver,
            snapshot_tag=build_ver,
            rolling_tag=ROLLING_DEV_TAG,
            zip_name=f"LyraForge-{build_ver}-{arch}.zip",
            checksums_name=CHECKSUMS_FILENAME,
            arch=arch,
            sha=clean_sha,
            sha7=sha7,
            commit_date_yyyymmdd=clean_date,
            build_timestamp_utc=build_timestamp_utc,
            event_name=event_name,
            ref=ref,
            reason="trusted main branch build",
        )

    if event_name in allowed_events and ref.startswith("refs/tags/"):
        tag = ref.removeprefix("refs/tags/")
        match = SEMVER_TAG_RE.match(tag)
        if match is not None:
            is_pre = match.group("pre") is not None
            return ReleasePlan(
                should_publish=True,
                channel="semver",
                prerelease=is_pre,
                build_version=tag,
                snapshot_tag=tag,
                rolling_tag=None,
                zip_name=f"LyraForge-{tag}-{arch}.zip",
                checksums_name=CHECKSUMS_FILENAME,
                arch=arch,
                sha=clean_sha,
                sha7=sha7,
                commit_date_yyyymmdd=clean_date,
                build_timestamp_utc=build_timestamp_utc,
                event_name=event_name,
                ref=ref,
                reason="explicit SemVer release tag",
            )
        return ReleasePlan(
            should_publish=False,
            channel="none",
            prerelease=True,
            build_version=f"ci-{sha7}",
            snapshot_tag=None,
            rolling_tag=None,
            zip_name=f"LyraForge-ci-{sha7}-{arch}.zip",
            checksums_name=CHECKSUMS_FILENAME,
            arch=arch,
            sha=clean_sha,
            sha7=sha7,
            commit_date_yyyymmdd=clean_date,
            build_timestamp_utc=build_timestamp_utc,
            event_name=event_name,
            ref=ref,
            reason=f"tag {tag!r} is not a formal SemVer vX.Y.Z tag",
        )

    return ReleasePlan(
        should_publish=False,
        channel="none",
        prerelease=True,
        build_version=f"ci-{sha7}",
        snapshot_tag=None,
        rolling_tag=None,
        zip_name=f"LyraForge-ci-{sha7}-{arch}.zip",
        checksums_name=CHECKSUMS_FILENAME,
        arch=arch,
        sha=clean_sha,
        sha7=sha7,
        commit_date_yyyymmdd=clean_date,
        build_timestamp_utc=build_timestamp_utc,
        event_name=event_name,
        ref=ref,
        reason=f"non-release trigger ({event_name} on {ref})",
    )


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def write_sha256sums(zip_path: Path, checksums_path: Path) -> str:
    digest = compute_sha256(zip_path)
    checksums_path.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    verify_sha256sums(checksums_path, zip_path)
    return digest


def verify_sha256sums(checksums_path: Path, zip_path: Path) -> str:
    content = checksums_path.read_text(encoding="utf-8").strip()
    parts = content.split()
    if len(parts) != 2 or parts[1] != zip_path.name:
        raise ValueError(f"malformed checksum file {checksums_path}: {content!r}")
    expected = parts[0].lower()
    actual = compute_sha256(zip_path)
    if expected != actual:
        raise ValueError(f"SHA256 mismatch for {zip_path.name}: expected {expected}, got {actual}")
    return actual


def _has_bundle_path(files: dict[str, int], rel_suffix: str) -> bool:
    return (
        f"LyraForge/{rel_suffix}" in files
        or f"LyraForge/_internal/{rel_suffix}" in files
    )


def _any_bundle_prefix(files: dict[str, int], rel_prefix: str, suffix: str) -> bool:
    p1 = f"LyraForge/{rel_prefix}"
    p2 = f"LyraForge/_internal/{rel_prefix}"
    return any(
        (name.startswith(p1) or name.startswith(p2)) and name.endswith(suffix) and size > 0
        for name, size in files.items()
    )


def validate_release_zip(zip_path: Path) -> dict[str, Any]:
    """Validate that a packaged Windows portable ZIP contains required runtime/assets."""
    if not zip_path.is_file() or zip_path.stat().st_size == 0:
        raise ValueError(f"release archive missing or empty: {zip_path}")

    with zipfile.ZipFile(zip_path, mode="r") as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        if not infos:
            raise ValueError("release ZIP contains no files")

        files: dict[str, int] = {}
        for info in infos:
            raw = info.filename
            norm = raw.replace("\\", "/")
            if norm.startswith("/") or ".." in Path(norm).parts or "\x00" in norm:
                raise ValueError(f"unsafe path inside release ZIP: {raw!r}")
            if not norm.startswith("LyraForge/"):
                raise ValueError(f"archive entries must reside under LyraForge/: {raw!r}")
            basename = norm.rsplit("/", 1)[-1].lower()
            if basename in _FORBIDDEN_ZIP_FILENAMES or basename.endswith(".secrets.json"):
                raise ValueError(f"forbidden sensitive file in release ZIP: {raw!r}")
            if norm in files:
                raise ValueError(f"duplicate path inside release ZIP: {raw!r}")
            files[norm] = int(info.file_size)

        if files.get("LyraForge/LyraForge.exe", 0) <= 0:
            raise ValueError("release ZIP missing non-empty LyraForge/LyraForge.exe")

        if files.get("LyraForge/LICENSE", 0) <= 0:
            raise ValueError("release ZIP missing non-empty LyraForge/LICENSE")
        lic_text = zf.read("LyraForge/LICENSE").decode("utf-8", errors="replace")
        if "GNU GENERAL PUBLIC LICENSE" not in lic_text.upper():
            raise ValueError("release ZIP LyraForge/LICENSE is not GNU GPL-3.0 text")

        has_runtime_libs = any(
            name.startswith("LyraForge/_internal/")
            and name.lower().endswith((".dll", ".pyd"))
            and size > 0
            for name, size in files.items()
        )
        if not has_runtime_libs:
            raise ValueError(
                "release ZIP missing PyInstaller runtime dependencies under _internal/"
            )

        if not _has_bundle_path(files, "apps/desktop/web/dist/index.html"):
            raise ValueError("release ZIP missing built frontend index.html")
        if not _any_bundle_prefix(files, "apps/desktop/web/dist/assets/", ".js"):
            raise ValueError("release ZIP missing built frontend JS assets")
        if not _any_bundle_prefix(files, "apps/desktop/web/dist/assets/", ".css"):
            raise ValueError("release ZIP missing built frontend CSS assets")

        if not _any_bundle_prefix(files, "lyraforge/instruments/data/", ".json"):
            raise ValueError("release ZIP missing instrument profile JSON data")
        if not _any_bundle_prefix(files, "lyraforge/music_core/schemas/", ".json"):
            raise ValueError("release ZIP missing performance schema JSON data")

        if files.get(f"LyraForge/{PORTABLE_README_FILENAME}", 0) <= 0:
            raise ValueError("release ZIP missing non-empty portable README.txt")

        # The desktop window is hosted by pywebview: without these payload files the frozen
        # EXE starts, fails to import the GUI host, and exits without showing anything.
        for required_payload in (
            "webview/lib/Microsoft.Web.WebView2.Core.dll",
            "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
            "pythonnet/runtime/Python.Runtime.dll",
        ):
            if not _has_bundle_path(files, required_payload):
                raise ValueError(
                    f"release ZIP missing bundled desktop GUI payload: {required_payload}"
                )

    return {
        "zip_name": zip_path.name,
        "file_count": len(files),
        "size_bytes": zip_path.stat().st_size,
    }


def _zip_info_for_posix(
    arcname: str, st: os.stat_result, *, symlink_target: str | None = None
) -> zipfile.ZipInfo:
    dt = datetime.fromtimestamp(st.st_mtime, tz=UTC)
    info = zipfile.ZipInfo(
        filename=arcname,
        date_time=(max(1980, dt.year), dt.month, dt.day, dt.hour, dt.minute, dt.second),
    )
    info.create_system = 3
    if symlink_target is not None:
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        info.compress_type = zipfile.ZIP_STORED
    else:
        mode = stat.S_IMODE(st.st_mode) or 0o644
        if arcname.startswith("LyraForge.app/Contents/MacOS/"):
            mode |= 0o755
        info.external_attr = (stat.S_IFREG | mode) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _has_macos_bundle_path(files: dict[str, int], rel_suffix: str) -> bool:
    return (
        f"LyraForge.app/Contents/Resources/{rel_suffix}" in files
        or f"LyraForge.app/Contents/Frameworks/{rel_suffix}" in files
        or f"LyraForge.app/Contents/MacOS/{rel_suffix}" in files
    )


def _any_macos_bundle_prefix(files: dict[str, int], rel_prefix: str, suffix: str) -> bool:
    prefixes = (
        f"LyraForge.app/Contents/Resources/{rel_prefix}",
        f"LyraForge.app/Contents/Frameworks/{rel_prefix}",
    )
    return any(
        any(name.startswith(pref) for pref in prefixes) and name.endswith(suffix) and size > 0
        for name, size in files.items()
    )


def validate_macos_release_zip(zip_path: Path) -> dict[str, Any]:
    """Validate that a packaged macOS LyraForge.app ZIP contains required runtime/assets."""
    if not zip_path.is_file() or zip_path.stat().st_size == 0:
        raise ValueError(f"release archive missing or empty: {zip_path}")

    root_files = {"LICENSE", "LICENSE_AUDIT.md", PORTABLE_README_FILENAME}
    with zipfile.ZipFile(zip_path, mode="r") as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        if not infos:
            raise ValueError("release ZIP contains no files")

        files: dict[str, int] = {}
        exec_info: zipfile.ZipInfo | None = None
        for info in infos:
            raw = info.filename
            norm = raw.replace("\\", "/")
            if norm.startswith("/") or ".." in Path(norm).parts or "\x00" in norm:
                raise ValueError(f"unsafe path inside release ZIP: {raw!r}")
            if not (norm.startswith("LyraForge.app/") or norm in root_files):
                raise ValueError(
                    f"macOS archive entries must reside under LyraForge.app/ or root docs: {raw!r}"
                )
            basename = norm.rsplit("/", 1)[-1].lower()
            if basename in _FORBIDDEN_ZIP_FILENAMES or basename.endswith(".secrets.json"):
                raise ValueError(f"forbidden sensitive file in release ZIP: {raw!r}")
            if norm in files:
                raise ValueError(f"duplicate path inside release ZIP: {raw!r}")

            mode_bits = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode_bits):
                target = zf.read(info).decode("utf-8", errors="strict")
                if not target or target.startswith("/") or "\x00" in target:
                    raise ValueError(f"unsafe symlink target in release ZIP ({raw!r}): {target!r}")
                parent_rel = posixpath.dirname(norm)
                resolved = posixpath.normpath(posixpath.join(parent_rel, target))
                if (
                    resolved == ".."
                    or resolved.startswith("../")
                    or not resolved.startswith("LyraForge.app/")
                ):
                    raise ValueError(
                        f"symlink escapes LyraForge.app ({raw!r} -> {target!r}): {resolved!r}"
                    )
            if norm == "LyraForge.app/Contents/MacOS/LyraForge":
                exec_info = info
            files[norm] = int(info.file_size)

        if files.get("LyraForge.app/Contents/MacOS/LyraForge", 0) <= 0:
            raise ValueError("release ZIP missing non-empty LyraForge.app/Contents/MacOS/LyraForge")
        if exec_info is not None:
            exec_mode = (exec_info.external_attr >> 16) & 0o777
            if exec_info.create_system == 3 and (exec_mode & 0o100) == 0:
                raise ValueError("LyraForge.app/Contents/MacOS/LyraForge missing executable bit")

        if files.get("LyraForge.app/Contents/Info.plist", 0) <= 0:
            raise ValueError("release ZIP missing non-empty LyraForge.app/Contents/Info.plist")

        icns_name = "LyraForge.app/Contents/Resources/lyraforge.icns"
        if files.get(icns_name, 0) <= 0:
            raise ValueError(f"release ZIP missing non-empty {icns_name}")
        icns_bytes = zf.read(icns_name)
        if not icns_bytes.startswith(b"icns"):
            raise ValueError(f"release ZIP {icns_name} is not a valid Apple .icns file")

        lic_candidate = (
            "LICENSE"
            if files.get("LICENSE", 0) > 0
            else (
                "LyraForge.app/Contents/Resources/LICENSE"
                if files.get("LyraForge.app/Contents/Resources/LICENSE", 0) > 0
                else ""
            )
        )
        if not lic_candidate:
            raise ValueError("release ZIP missing non-empty LICENSE")
        lic_text = zf.read(lic_candidate).decode("utf-8", errors="replace")
        if "GNU GENERAL PUBLIC LICENSE" not in lic_text.upper():
            raise ValueError("release ZIP LICENSE is not GNU GPL-3.0 text")

        if files.get(PORTABLE_README_FILENAME, 0) <= 0:
            raise ValueError("release ZIP missing non-empty README.txt")

        if not _has_macos_bundle_path(files, "apps/desktop/web/dist/index.html"):
            raise ValueError("release ZIP missing built frontend index.html")
        if not _any_macos_bundle_prefix(files, "apps/desktop/web/dist/assets/", ".js"):
            raise ValueError("release ZIP missing built frontend JS assets")
        if not _any_macos_bundle_prefix(files, "apps/desktop/web/dist/assets/", ".css"):
            raise ValueError("release ZIP missing built frontend CSS assets")

        if not _any_macos_bundle_prefix(files, "lyraforge/instruments/data/", ".json"):
            raise ValueError("release ZIP missing instrument profile JSON data")
        if not _any_macos_bundle_prefix(files, "lyraforge/music_core/schemas/", ".json"):
            raise ValueError("release ZIP missing performance schema JSON data")

    return {
        "zip_name": zip_path.name,
        "file_count": len(files),
        "size_bytes": zip_path.stat().st_size,
    }


def package_macos_bundle(
    app_dir: Path,
    output_dir: Path,
    *,
    zip_name: str,
    license_path: Path,
    license_audit_path: Path | None = None,
) -> tuple[Path, Path, str]:
    """Package PyInstaller ``dist/LyraForge.app`` preserving POSIX permissions & symlinks."""
    if not app_dir.is_dir():
        raise FileNotFoundError(f"PyInstaller macOS .app directory not found: {app_dir}")
    if not (app_dir / "Contents" / "MacOS" / "LyraForge").is_file():
        raise FileNotFoundError(f"LyraForge executable not found inside {app_dir}/Contents/MacOS")
    if not (app_dir / "Contents" / "Info.plist").is_file():
        raise FileNotFoundError(f"Info.plist not found inside {app_dir}/Contents")
    if not (app_dir / "Contents" / "Resources" / "lyraforge.icns").is_file():
        raise FileNotFoundError(f"lyraforge.icns not found inside {app_dir}/Contents/Resources")
    if not license_path.is_file():
        raise FileNotFoundError(f"LICENSE file not found at {license_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / zip_name
    checksums_path = output_dir / CHECKSUMS_FILENAME

    bundle_root = app_dir.resolve()
    entries: list[tuple[str, Path, os.stat_result, str | None]] = []
    for root, dirnames, filenames in os.walk(bundle_root, followlinks=False):
        root_path = Path(root)
        kept_dirs: list[str] = []
        for dname in sorted(dirnames):
            dpath = root_path / dname
            if dpath.is_symlink():
                rel = dpath.relative_to(bundle_root).as_posix()
                entries.append((f"LyraForge.app/{rel}", dpath, dpath.lstat(), os.readlink(dpath)))
            else:
                kept_dirs.append(dname)
        dirnames[:] = kept_dirs
        for fname in sorted(filenames):
            fpath = root_path / fname
            rel = fpath.relative_to(bundle_root).as_posix()
            st = fpath.lstat()
            sym = os.readlink(fpath) if stat.S_ISLNK(st.st_mode) else None
            entries.append((f"LyraForge.app/{rel}", fpath, st, sym))

    entries.sort(key=lambda item: item[0])
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, path_obj, st, sym in entries:
            info = _zip_info_for_posix(arcname, st, symlink_target=sym)
            if sym is not None:
                zf.writestr(info, sym.encode("utf-8"))
            else:
                zf.writestr(info, path_obj.read_bytes())

        zf.write(license_path, arcname="LICENSE")
        if license_audit_path is not None and license_audit_path.is_file():
            zf.write(license_audit_path, arcname="LICENSE_AUDIT.md")
        zf.writestr(PORTABLE_README_FILENAME, PORTABLE_MACOS_README_TEXT)

    validate_macos_release_zip(zip_path)
    digest = write_sha256sums(zip_path, checksums_path)
    return zip_path, checksums_path, digest


def package_windows_bundle(
    bundle_dir: Path,
    output_dir: Path,
    *,
    zip_name: str,
    license_path: Path,
    license_audit_path: Path | None = None,
) -> tuple[Path, Path, str]:
    """Package PyInstaller ``dist/LyraForge`` directory into a verified ZIP + SHA256SUMS.txt."""
    if not bundle_dir.is_dir():
        raise FileNotFoundError(f"PyInstaller bundle directory not found: {bundle_dir}")
    if not (bundle_dir / "LyraForge.exe").is_file():
        raise FileNotFoundError(f"LyraForge.exe not found inside {bundle_dir}")
    if not license_path.is_file():
        raise FileNotFoundError(f"LICENSE file not found at {license_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / zip_name
    checksums_path = output_dir / CHECKSUMS_FILENAME

    bundle_root = bundle_dir.resolve()
    arc_written: set[str] = set()
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(bundle_root.rglob("*")):
            if not item.is_file():
                continue
            rel = item.relative_to(bundle_root).as_posix()
            arcname = f"LyraForge/{rel}"
            zf.write(item, arcname=arcname)
            arc_written.add(arcname)
        if "LyraForge/LICENSE" not in arc_written:
            zf.write(license_path, arcname="LyraForge/LICENSE")
            arc_written.add("LyraForge/LICENSE")
        if (
            license_audit_path is not None
            and license_audit_path.is_file()
            and "LyraForge/LICENSE_AUDIT.md" not in arc_written
        ):
            zf.write(license_audit_path, arcname="LyraForge/LICENSE_AUDIT.md")
            arc_written.add("LyraForge/LICENSE_AUDIT.md")
        if f"LyraForge/{PORTABLE_README_FILENAME}" not in arc_written:
            zf.writestr(f"LyraForge/{PORTABLE_README_FILENAME}", PORTABLE_README_TEXT)
            arc_written.add(f"LyraForge/{PORTABLE_README_FILENAME}")

    validate_release_zip(zip_path)
    digest = write_sha256sums(zip_path, checksums_path)
    return zip_path, checksums_path, digest


def render_release_notes(
    plan: ReleasePlan,
    *,
    repo: str,
    sha256_digest: str,
    zip_size_bytes: int,
    rolling_entry: bool = False,
    extra_entries: Sequence[tuple[ReleasePlan, str, int]] = (),
) -> str:
    """Render user-facing Markdown release notes with honest experimental notices."""
    commit_url = f"https://github.com/{repo}/commit/{plan.sha}"
    size_mb = zip_size_bytes / (1024 * 1024)
    all_plans = [plan, *(item[0] for item in extra_entries)]
    arch_summary = " + ".join(p.arch for p in all_plans)
    has_windows = any("windows" in p.arch.lower() for p in all_plans)
    has_macos = any("macos" in p.arch.lower() for p in all_plans)

    if plan.prerelease:
        warning_line = (
            "> [!WARNING]\n"
            "> **Experimental Pre-release Build (NOT a verified stable release)** — "
            "Windows 10/11 live Genshin Impact 21-key calibration and foreground playback "
            "have NOT yet completed verification on physical game hardware "
            "(`calibration.status = unverified`). "
            "Only unit tests, frontend checks, PyInstaller bundling, and headless "
            "`--self-check --check-gui` passed in CI."
        )
    else:
        warning_line = (
            "> [!IMPORTANT]\n"
            "> LyraForge only targets the in-game **free-play instrument interface** "
            "(never falling-note minigames). Always verify foreground window focus "
            "and obey game Terms of Service."
        )

    channel_label = (
        "Development Pre-release (`dev-latest` rolling channel)"
        if rolling_entry
        else (
            "Development Snapshot Pre-release"
            if plan.channel == "dev"
            else ("SemVer Pre-release" if plan.prerelease else "Stable Release (SemVer)")
        )
    )
    snapshot_links = ""
    if plan.channel == "dev" and plan.snapshot_tag:
        snapshot_links = (
            f"\n- **Fixed Latest Dev Entry**: "
            f"https://github.com/{repo}/releases/tag/{ROLLING_DEV_TAG}\n"
            f"- **Immutable Build Snapshot**: "
            f"https://github.com/{repo}/releases/tag/{plan.snapshot_tag}\n"
        )

    target_desc = (
        f"Windows 10 / 11 x64 + macOS Apple Silicon (`{arch_summary}`)"
        if (has_windows and has_macos)
        else (
            f"macOS Apple Silicon (`{arch_summary}` `.app` bundle ZIP)"
            if has_macos
            else f"Windows 10 / 11 x64 (`{plan.arch}` portable ZIP)"
        )
    )

    artifact_lines = [
        f"- **`{plan.zip_name}`** (`{plan.arch}`, {size_mb:.2f} MiB, `{zip_size_bytes}` bytes)\n"
        f"  - SHA256: `{sha256_digest}`"
    ]
    for ext_plan, ext_digest, ext_size in extra_entries:
        ext_mb = ext_size / (1024 * 1024)
        artifact_lines.append(
            f"- **`{ext_plan.zip_name}`** (`{ext_plan.arch}`, {ext_mb:.2f} MiB, "
            f"`{ext_size}` bytes)\n  - SHA256: `{ext_digest}`"
        )
    artifact_lines.append(f"- **`{plan.checksums_name}`**")
    artifacts_block = "\n".join(artifact_lines)

    win_zip = next((p.zip_name for p in all_plans if "windows" in p.arch.lower()), plan.zip_name)
    mac_zip = next((p.zip_name for p in all_plans if "macos" in p.arch.lower()), plan.zip_name)

    sections = [
        f"""# LyraForge {plan.build_version} ({arch_summary})

{warning_line}

## Build Metadata

| Field | Value |
|---|---|
| **Release Channel** | {channel_label} |
| **Build Version** | `{plan.build_version}` |
| **Commit SHA** | [`{plan.sha}`]({commit_url}) |
| **Commit Date (UTC)** | `{plan.commit_date_yyyymmdd}` |
| **Built At (UTC)** | `{plan.build_timestamp_utc}` |
| **Target Architecture** | {target_desc} |
| **License** | GNU General Public License v3.0 (`LICENSE` included inside archive) |
{snapshot_links}
## Artifacts & SHA256 Verification

{artifacts_block}

Verify integrity after downloading (PowerShell):

```powershell
Get-FileHash .\\{win_zip} -Algorithm SHA256
Get-Content .\\{plan.checksums_name}
```

Or in macOS / Git Bash / Linux:

```bash
sha256sum -c {plan.checksums_name}
# macOS alternative: shasum -a 256 -c {plan.checksums_name}
```"""
    ]

    if has_windows:
        sections.append(
            f"""## Runtime Requirements & Quick Start (Windows 10/11 x64)

1. **System Requirements**:
   - Windows 10 or Windows 11 (64-bit), no Python or Node.js required. `LyraForge.exe` requests
     UAC Administrator elevation by default so synthetic free-play input matches elevated games
     (`--no-elevate` / `LYRAFORGE_NO_ELEVATE=1` opts out from CLI/source).
   - Microsoft Edge **WebView2 Runtime** (pre-installed on modern Windows 10/11) for UI.
   - Optional external tools (`ffmpeg`, `basic-pitch`, `dettato`) are **not bundled** due
     to size/license boundaries and can be configured separately or via **Settings**.
2. **Extract & Run**:
   - Extract `{win_zip}` to any writable folder (keep `LyraForge.exe` together with
     `_internal\\` inside the extracted `LyraForge\\` folder).
   - Run headless health check:
     ```powershell
     .\\LyraForge\\LyraForge.exe --self-check
     ```
   - Launch the desktop workbench:
     ```powershell
     .\\LyraForge\\LyraForge.exe
     ```
3. **Important Notes**:
   - Live in-game keyboard input requires explicit two-step confirmation in the UI,
     checks active foreground window focus, and releases pressed keys on focus loss or `Esc`.
   - Third-party keyboard automation cannot guarantee zero game-account risk; evaluate
     and assume responsibility before use."""
        )

    if has_macos:
        sections.append(
            f"""## Runtime Requirements & Quick Start (macOS Apple Silicon)

1. **Extract & Install**:
   - Extract `{mac_zip}` (`unzip {mac_zip}` or double-click in Finder) and drag `LyraForge.app`
     to `/Applications` (or any writable folder).
2. **First Launch (Unsigned Build)**:
   - Open-source builds are ad-hoc signed without Apple Developer notarization. If macOS
     Gatekeeper prompts, Right-click `LyraForge.app` → **Open**, or run:
     ```bash
     xattr -dr com.apple.quarantine LyraForge.app
     ```
   - Optional headless check: `./LyraForge.app/Contents/MacOS/LyraForge --self-check --check-gui`
3. **Platform Scope**:
   - Full MIDI/audio import, transcription, Piano Roll editing, WAV preview synthesis, library
     management, and MCP integration work natively; OS playback uses safe **DryRun** mode."""
        )

    return "\n\n".join(sections) + "\n"


def _require_ok(
    res: subprocess.CompletedProcess[str], action: str
) -> subprocess.CompletedProcess[str]:
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip()
        raise RuntimeError(f"{action} failed (exit {res.returncode}): {detail}")
    return res


def _get_remote_main_sha(*, repo: str, run_cmd: CommandRunner) -> str:
    resp = _require_ok(
        run_cmd(["gh", "api", f"repos/{repo}/git/ref/heads/main"]),
        "fetch remote main HEAD SHA",
    )
    try:
        sha = str(json.loads(resp.stdout or "{}").get("object", {}).get("sha") or "").strip()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON from remote main ref API: {exc}") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", sha.lower()):
        raise RuntimeError(f"unexpected remote main HEAD SHA: {sha!r}")
    return sha.lower()


def _update_rolling_dev_tag(
    *,
    repo: str,
    tag: str,
    sha: str,
    run_cmd: CommandRunner,
) -> None:
    if tag != ROLLING_DEV_TAG or is_semver_tag(tag):
        raise ValueError(f"refusing to force-move protected or non-rolling tag: {tag!r}")
    ref_endpoint = f"repos/{repo}/git/refs/tags/{tag}"
    probe = run_cmd(["gh", "api", ref_endpoint])
    if probe.returncode != 0:
        return
    try:
        current_sha = str(json.loads(probe.stdout or "{}").get("object", {}).get("sha") or "")
    except json.JSONDecodeError:
        current_sha = ""
    if current_sha.lower() == sha.lower():
        return
    _require_ok(
        run_cmd([
            "gh",
            "api",
            "--method",
            "PATCH",
            ref_endpoint,
            "-f",
            f"sha={sha}",
            "-F",
            "force=true",
        ]),
        f"update rolling tag ref {tag!r}",
    )


def _ensure_release(
    *,
    repo: str,
    tag: str,
    sha: str,
    title: str,
    notes_path: Path,
    assets: Sequence[Path],
    prerelease: bool,
    mark_latest: bool,
    is_rolling_dev: bool,
    verify_existing_tag: bool,
    prune_extra_assets: bool,
    run_cmd: CommandRunner,
) -> str:
    if is_rolling_dev:
        _update_rolling_dev_tag(repo=repo, tag=tag, sha=sha, run_cmd=run_cmd)

    view = run_cmd([
        "gh",
        "release",
        "view",
        tag,
        "--repo",
        repo,
        "--json",
        "tagName,url,assets",
    ])
    asset_args = [str(p) for p in assets]
    expected_asset_names = {p.name for p in assets}

    if view.returncode != 0:
        cmd = [
            "gh",
            "release",
            "create",
            tag,
            "--repo",
            repo,
            "--title",
            title,
            "--notes-file",
            str(notes_path),
            "--verify-tag" if verify_existing_tag else "--target",
            *([] if verify_existing_tag else [sha]),
            *(["--prerelease", "--latest=false"] if prerelease else ["--prerelease=false"]),
            *(["--latest"] if (mark_latest and not prerelease) else []),
            *asset_args,
        ]
        _require_ok(run_cmd(cmd), f"create release {tag!r}")
    else:
        existing_data = json.loads(view.stdout or "{}")
        existing_assets = [
            str(item.get("name"))
            for item in (existing_data.get("assets") or [])
            if item.get("name")
        ]
        edit_cmd = [
            "gh",
            "release",
            "edit",
            tag,
            "--repo",
            repo,
            "--title",
            title,
            "--notes-file",
            str(notes_path),
            *(["--target", sha] if is_rolling_dev else []),
            *(["--prerelease"] if prerelease else ["--prerelease=false"]),
            *(["--latest"] if (mark_latest and not prerelease) else []),
        ]
        _require_ok(run_cmd(edit_cmd), f"edit release {tag!r}")
        _require_ok(
            run_cmd([
                "gh",
                "release",
                "upload",
                tag,
                "--repo",
                repo,
                "--clobber",
                *asset_args,
            ]),
            f"upload assets to release {tag!r}",
        )
        if prune_extra_assets:
            for old_asset in existing_assets:
                if old_asset not in expected_asset_names:
                    _require_ok(
                        run_cmd([
                            "gh",
                            "release",
                            "delete-asset",
                            tag,
                            old_asset,
                            "--repo",
                            repo,
                            "--yes",
                        ]),
                        f"delete stale asset {old_asset!r} on {tag!r}",
                    )

    final_view = _require_ok(
        run_cmd(["gh", "release", "view", tag, "--repo", repo, "--json", "url"]),
        f"fetch URL for release {tag!r}",
    )
    return str(json.loads(final_view.stdout or "{}").get("url") or f"https://github.com/{repo}/releases/tag/{tag}")


def prune_old_dev_snapshots(
    *,
    repo: str,
    keep_tag: str,
    retain: int = 10,
    run_cmd: CommandRunner | None = None,
) -> list[str]:
    """Delete excess historical dev-* pre-releases while preserving dev-latest and v*."""
    if retain <= 0:
        return []
    runner = run_cmd or default_run_cmd
    resp = _require_ok(
        runner(["gh", "api", f"repos/{repo}/releases?per_page=100"]),
        "list releases for snapshot retention pruning",
    )
    releases = json.loads(resp.stdout or "[]")
    snapshots: list[tuple[str, str]] = []
    for rel in releases:
        tag = str(rel.get("tag_name") or "")
        is_pre = bool(rel.get("prerelease"))
        if not is_pre or tag == ROLLING_DEV_TAG or is_semver_tag(tag):
            continue
        if DEV_SNAPSHOT_TAG_RE.match(tag):
            snapshots.append((str(rel.get("published_at") or rel.get("created_at") or ""), tag))

    # Newest first
    snapshots.sort(key=lambda item: item[0], reverse=True)
    kept: list[str] = [keep_tag]
    for _ts, tag in snapshots:
        if tag != keep_tag and len(kept) < retain:
            kept.append(tag)
    keep_set = set(kept)

    deleted: list[str] = []
    for _ts, tag in snapshots:
        if tag in keep_set:
            continue
        if tag == ROLLING_DEV_TAG or is_semver_tag(tag):
            continue
        _require_ok(
            runner([
                "gh",
                "release",
                "delete",
                tag,
                "--repo",
                repo,
                "--yes",
                "--cleanup-tag",
            ]),
            f"prune old dev snapshot {tag!r}",
        )
        deleted.append(tag)
    return deleted


def _validate_archive_for_arch(arch: str, zip_path: Path) -> None:
    if "macos" in arch.lower():
        validate_macos_release_zip(zip_path)
    else:
        validate_release_zip(zip_path)


def publish_release(
    *,
    plan: ReleasePlan,
    zip_path: Path,
    checksums_path: Path,
    repo: str = DEFAULT_REPO,
    retain_dev_snapshots: int = 10,
    run_cmd: CommandRunner | None = None,
    extra_artifacts: Sequence[tuple[ReleasePlan, Path]] = (),
) -> dict[str, Any]:
    """Publish dev or SemVer GitHub Releases idempotently from validated artifacts."""
    runner = run_cmd or default_run_cmd
    if not plan.should_publish or not plan.snapshot_tag:
        return {
            "published": False,
            "channel": plan.channel,
            "reason": plan.reason,
            "releases": [],
            "pruned_snapshots": [],
        }

    _validate_archive_for_arch(plan.arch, zip_path)
    digest = verify_sha256sums(checksums_path, zip_path)
    size_bytes = zip_path.stat().st_size

    extra_entries: list[tuple[ReleasePlan, str, int]] = []
    extra_zips: list[Path] = []
    for ext_plan, ext_zip in extra_artifacts:
        _validate_archive_for_arch(ext_plan.arch, ext_zip)
        ext_digest = compute_sha256(ext_zip)
        extra_entries.append((ext_plan, ext_digest, ext_zip.stat().st_size))
        extra_zips.append(ext_zip)

    arch_label = " + ".join([plan.arch, *(ext.arch for ext, _ in extra_artifacts)])

    with tempfile.TemporaryDirectory(prefix="lyraforge-rel-notes-") as tmp:
        tmp_dir = Path(tmp)
        published_urls: list[dict[str, str]] = []
        if extra_entries:
            combined_sums = tmp_dir / CHECKSUMS_FILENAME
            lines = [f"{digest}  {zip_path.name}\n"]
            for ext_plan, ext_digest, _ext_sz in extra_entries:
                lines.append(f"{ext_digest}  {ext_plan.zip_name}\n")
            combined_sums.write_text("".join(lines), encoding="utf-8")
            assets = [zip_path, *extra_zips, combined_sums]
        else:
            assets = [zip_path, checksums_path]

        if plan.channel == "dev":
            snap_notes = tmp_dir / "snapshot-notes.md"
            snap_notes.write_text(
                render_release_notes(
                    plan,
                    repo=repo,
                    sha256_digest=digest,
                    zip_size_bytes=size_bytes,
                    rolling_entry=False,
                    extra_entries=extra_entries,
                ),
                encoding="utf-8",
            )
            snap_url = _ensure_release(
                repo=repo,
                tag=plan.snapshot_tag,
                sha=plan.sha,
                title=f"LyraForge {plan.build_version} ({arch_label}, Experimental Pre-release)",
                notes_path=snap_notes,
                assets=assets,
                prerelease=True,
                mark_latest=False,
                is_rolling_dev=False,
                verify_existing_tag=False,
                prune_extra_assets=True,
                run_cmd=runner,
            )
            published_urls.append({"tag": plan.snapshot_tag, "url": snap_url})

            remote_main_sha = _get_remote_main_sha(repo=repo, run_cmd=runner)
            if remote_main_sha.lower() != plan.sha.lower():
                return {
                    "published": True,
                    "channel": plan.channel,
                    "sha": plan.sha,
                    "sha256": digest,
                    "releases": published_urls,
                    "pruned_snapshots": [],
                    "rolling_updated": False,
                    "rolling_skipped_reason": (
                        f"stale commit {plan.sha} != remote main {remote_main_sha}"
                    ),
                }

            if plan.rolling_tag:
                rolling_notes = tmp_dir / "rolling-notes.md"
                rolling_notes.write_text(
                    render_release_notes(
                        plan,
                        repo=repo,
                        sha256_digest=digest,
                        zip_size_bytes=size_bytes,
                        rolling_entry=True,
                        extra_entries=extra_entries,
                    ),
                    encoding="utf-8",
                )
                rolling_url = _ensure_release(
                    repo=repo,
                    tag=plan.rolling_tag,
                    sha=plan.sha,
                    title=(
                        f"LyraForge Latest Dev ({plan.build_version}, "
                        f"{arch_label}, Experimental Pre-release)"
                    ),
                    notes_path=rolling_notes,
                    assets=assets,
                    prerelease=True,
                    mark_latest=False,
                    is_rolling_dev=True,
                    verify_existing_tag=False,
                    prune_extra_assets=True,
                    run_cmd=runner,
                )
                published_urls.append({"tag": plan.rolling_tag, "url": rolling_url})

            pruned = prune_old_dev_snapshots(
                repo=repo,
                keep_tag=plan.snapshot_tag,
                retain=retain_dev_snapshots,
                run_cmd=runner,
            )
            return {
                "published": True,
                "channel": plan.channel,
                "sha": plan.sha,
                "sha256": digest,
                "releases": published_urls,
                "pruned_snapshots": pruned,
                "rolling_updated": bool(plan.rolling_tag),
                "rolling_skipped_reason": None,
            }

        sem_notes = tmp_dir / "semver-notes.md"
        sem_notes.write_text(
            render_release_notes(
                plan,
                repo=repo,
                sha256_digest=digest,
                zip_size_bytes=size_bytes,
                rolling_entry=False,
                extra_entries=extra_entries,
            ),
            encoding="utf-8",
        )
        sem_title = (
            f"LyraForge {plan.build_version} ({arch_label}, Pre-release)"
            if plan.prerelease
            else f"LyraForge {plan.build_version} ({arch_label})"
        )
        sem_url = _ensure_release(
            repo=repo,
            tag=plan.snapshot_tag,
            sha=plan.sha,
            title=sem_title,
            notes_path=sem_notes,
            assets=assets,
            prerelease=plan.prerelease,
            mark_latest=not plan.prerelease,
            is_rolling_dev=False,
            verify_existing_tag=True,
            prune_extra_assets=False,
            run_cmd=runner,
        )
        published_urls.append({"tag": plan.snapshot_tag, "url": sem_url})
        return {
            "published": True,
            "channel": plan.channel,
            "sha": plan.sha,
            "sha256": digest,
            "releases": published_urls,
            "pruned_snapshots": [],
        }


def _resolve_commit_date_utc(sha: str) -> str:
    res = default_run_cmd(["git", "show", "-s", "--format=%ct", sha])
    if res.returncode == 0 and res.stdout.strip().isdigit():
        return datetime.fromtimestamp(int(res.stdout.strip()), tz=UTC).strftime("%Y%m%d")
    return datetime.now(UTC).strftime("%Y%m%d")


def _cmd_package(args: argparse.Namespace) -> int:
    platform_name = getattr(args, "platform", "windows") or "windows"
    arch = args.arch or (DEFAULT_MACOS_ARCH if platform_name == "macos" else DEFAULT_ARCH)
    commit_date = args.commit_date or _resolve_commit_date_utc(args.sha)
    build_ts = args.build_time or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    plan = resolve_release_plan(
        event_name=args.event_name,
        ref=args.ref,
        sha=args.sha,
        commit_date_yyyymmdd=commit_date,
        build_timestamp_utc=build_ts,
        arch=arch,
    )
    out_dir = Path(args.output_dir)
    packager = package_macos_bundle if platform_name == "macos" else package_windows_bundle
    zip_path, checksums_path, digest = packager(
        Path(args.bundle_dir),
        out_dir,
        zip_name=plan.zip_name,
        license_path=Path(args.license),
        license_audit_path=Path(args.license_audit) if args.license_audit else None,
    )
    meta = {
        "platform": platform_name,
        "plan": plan.to_json(),
        "zip_name": zip_path.name,
        "checksums_name": checksums_path.name,
        "sha256": digest,
        "size_bytes": zip_path.stat().st_size,
    }
    (out_dir / METADATA_FILENAME).write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    return 0


def _load_dist_dir(
    dist_dir: Path,
    *,
    event_name: str,
    ref: str,
    sha: str,
) -> tuple[ReleasePlan, Path, Path]:
    meta_path = dist_dir / METADATA_FILENAME
    if not meta_path.is_file():
        raise FileNotFoundError(f"missing {METADATA_FILENAME} in {dist_dir}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    raw_plan = meta["plan"]
    plan = resolve_release_plan(
        event_name=event_name or raw_plan["event_name"],
        ref=ref or raw_plan["ref"],
        sha=sha or raw_plan["sha"],
        commit_date_yyyymmdd=raw_plan["commit_date_yyyymmdd"],
        build_timestamp_utc=raw_plan["build_timestamp_utc"],
        arch=raw_plan.get("arch") or DEFAULT_ARCH,
    )
    zip_path = dist_dir / str(meta["zip_name"])
    checksums_path = dist_dir / str(meta["checksums_name"])
    return plan, zip_path, checksums_path


def _cmd_publish(args: argparse.Namespace) -> int:
    plan, zip_path, checksums_path = _load_dist_dir(
        Path(args.dist_dir),
        event_name=args.event_name,
        ref=args.ref,
        sha=args.sha,
    )
    extra_artifacts: list[tuple[ReleasePlan, Path]] = []
    for extra_dir_str in getattr(args, "extra_dist_dir", None) or ():
        ext_plan, ext_zip, ext_sums = _load_dist_dir(
            Path(extra_dir_str),
            event_name=args.event_name,
            ref=args.ref,
            sha=args.sha,
        )
        verify_sha256sums(ext_sums, ext_zip)
        extra_artifacts.append((ext_plan, ext_zip))

    result = publish_release(
        plan=plan,
        zip_path=zip_path,
        checksums_path=checksums_path,
        repo=args.repo,
        retain_dev_snapshots=int(args.retain_dev_snapshots),
        extra_artifacts=extra_artifacts,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LyraForge CI Release helper (Windows & macOS)")
    sub = parser.add_subparsers(dest="command", required=True)

    pkg = sub.add_parser("package", help="Package and validate portable ZIP + SHA256")
    pkg.add_argument("--platform", choices=["windows", "macos"], default="windows")
    pkg.add_argument("--bundle-dir", required=True)
    pkg.add_argument("--output-dir", required=True)
    pkg.add_argument("--license", default="LICENSE")
    pkg.add_argument("--license-audit", default="docs/LICENSE_AUDIT.md")
    pkg.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", "push"))
    pkg.add_argument("--ref", default=os.environ.get("GITHUB_REF", "refs/heads/main"))
    pkg.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    pkg.add_argument("--commit-date", default="")
    pkg.add_argument("--build-time", default="")
    pkg.add_argument("--arch", default=None)
    pkg.set_defaults(func=_cmd_package)

    pub = sub.add_parser("publish", help="Idempotently publish verified release to GitHub")
    pub.add_argument("--dist-dir", required=True)
    pub.add_argument("--extra-dist-dir", action="append", default=[])
    pub.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO))
    pub.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    pub.add_argument("--ref", default=os.environ.get("GITHUB_REF", ""))
    pub.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    pub.add_argument("--retain-dev-snapshots", type=int, default=10)
    pub.set_defaults(func=_cmd_publish)

    args = parser.parse_args(argv)
    if args.command == "package" and not args.sha:
        sha_res = default_run_cmd(["git", "rev-parse", "HEAD"])
        args.sha = sha_res.stdout.strip()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
