"""Unit tests for scripts/release_helper.py and .github/workflows/ci.yml release rules."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import release_helper as rh  # noqa: E402


def _make_fake_bundle(
    root: Path,
    *,
    include_exe: bool = True,
    include_dll: bool = True,
    include_index: bool = True,
    include_js: bool = True,
    include_css: bool = True,
    include_instrument: bool = True,
    include_schema: bool = True,
    include_gui_host: bool = True,
    include_secret: bool = False,
    layout_under_internal: bool = True,
) -> Path:
    bundle = root / "LyraForge"
    bundle.mkdir(parents=True, exist_ok=True)
    if include_exe:
        (bundle / "LyraForge.exe").write_bytes(b"MZ-fake-pe-executable")
    internal = bundle / "_internal"
    internal.mkdir(parents=True, exist_ok=True)
    if include_dll:
        (internal / "python311.dll").write_bytes(b"MZ-fake-python-dll")
    data_base = internal if layout_under_internal else bundle
    if include_index:
        dist_dir = data_base / "apps" / "desktop" / "web" / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
        assets_dir = dist_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        if include_js:
            (assets_dir / "index-abc.js").write_text("console.log('ok');", encoding="utf-8")
        if include_css:
            (assets_dir / "index-abc.css").write_text("body{}", encoding="utf-8")
    if include_instrument:
        inst = data_base / "lyraforge" / "instruments" / "data"
        inst.mkdir(parents=True, exist_ok=True)
        (inst / "windsong.json").write_text("{}", encoding="utf-8")
    if include_schema:
        sch = data_base / "lyraforge" / "music_core" / "schemas"
        sch.mkdir(parents=True, exist_ok=True)
        (sch / "performance.schema.json").write_text("{}", encoding="utf-8")
    if include_gui_host:
        webview_lib = data_base / "webview" / "lib"
        native = webview_lib / "runtimes" / "win-x64" / "native"
        native.mkdir(parents=True, exist_ok=True)
        (webview_lib / "Microsoft.Web.WebView2.Core.dll").write_bytes(b"MZ-fake-webview2-core")
        (native / "WebView2Loader.dll").write_bytes(b"MZ-fake-webview2-loader")
        runtime = data_base / "pythonnet" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "Python.Runtime.dll").write_bytes(b"MZ-fake-python-runtime")
    if include_secret:
        (bundle / ".lyraforge.secrets.json").write_text(
            '{"llm_api_key":"secret"}', encoding="utf-8"
        )
    return bundle


# ---------------------------------------------------------------------------
# 1. Trigger channel resolution & strict PR/branch/tag gating
# ---------------------------------------------------------------------------


def test_resolve_release_plan_gating_and_naming() -> None:
    sha = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

    # PR never publishes
    pr_plan = rh.resolve_release_plan(
        event_name="pull_request",
        ref="refs/pull/7/merge",
        sha=sha,
        commit_date_yyyymmdd="20261123",
        build_timestamp_utc="2026-11-23T03:00:00Z",
    )
    assert pr_plan.should_publish is False
    assert pr_plan.channel == "none"
    assert pr_plan.zip_name == "LyraForge-ci-a1b2c3d-windows-x64.zip"

    # Feature branch push never publishes
    feat_plan = rh.resolve_release_plan(
        event_name="push",
        ref="refs/heads/feat/some-branch",
        sha=sha,
        commit_date_yyyymmdd="20261123",
        build_timestamp_utc="2026-11-23T03:00:00Z",
    )
    assert feat_plan.should_publish is False
    assert feat_plan.channel == "none"

    # main push & workflow_dispatch share deterministic dev snapshot + rolling dev-latest
    for ev in ("push", "workflow_dispatch"):
        dev_plan = rh.resolve_release_plan(
            event_name=ev,
            ref="refs/heads/main",
            sha=sha,
            commit_date_yyyymmdd="20261123",
            build_timestamp_utc="2026-11-24T01:02:03Z",
        )
        assert dev_plan.should_publish is True
        assert dev_plan.channel == "dev"
        assert dev_plan.prerelease is True
        assert dev_plan.build_version == "dev-20261123-a1b2c3d"
        assert dev_plan.snapshot_tag == "dev-20261123-a1b2c3d"
        assert dev_plan.rolling_tag == "dev-latest"
        assert dev_plan.zip_name == "LyraForge-dev-20261123-a1b2c3d-windows-x64.zip"

    # SemVer formal stable tag -> non-prerelease, no rolling dev update
    stable_plan = rh.resolve_release_plan(
        event_name="push",
        ref="refs/tags/v0.2.0",
        sha=sha,
        commit_date_yyyymmdd="20261123",
        build_timestamp_utc="2026-11-23T03:00:00Z",
    )
    assert stable_plan.should_publish is True
    assert stable_plan.channel == "semver"
    assert stable_plan.prerelease is False
    assert stable_plan.snapshot_tag == "v0.2.0"
    assert stable_plan.rolling_tag is None
    assert stable_plan.zip_name == "LyraForge-v0.2.0-windows-x64.zip"

    # SemVer pre-release tag -> prerelease=True, no rolling dev update
    alpha_plan = rh.resolve_release_plan(
        event_name="push",
        ref="refs/tags/v0.1.0-alpha.1",
        sha=sha,
        commit_date_yyyymmdd="20261123",
        build_timestamp_utc="2026-11-23T03:00:00Z",
    )
    assert alpha_plan.should_publish is True
    assert alpha_plan.channel == "semver"
    assert alpha_plan.prerelease is True
    assert alpha_plan.snapshot_tag == "v0.1.0-alpha.1"
    assert alpha_plan.rolling_tag is None

    # Non-SemVer / rolling / malformed tags never trigger publishing
    for bad_ref in (
        "refs/tags/dev-latest",
        "refs/tags/dev-20261123-a1b2c3d",
        "refs/tags/v1.2",
        "refs/tags/vbad.tag.name",
    ):
        bad_plan = rh.resolve_release_plan(
            event_name="push",
            ref=bad_ref,
            sha=sha,
            commit_date_yyyymmdd="20261123",
            build_timestamp_utc="2026-11-23T03:00:00Z",
        )
        assert bad_plan.should_publish is False
        assert bad_plan.channel == "none"


# ---------------------------------------------------------------------------
# 2. Portable ZIP packaging, SHA256 verification & negative validation
# ---------------------------------------------------------------------------


def test_package_validate_and_sha256_checks(tmp_path: Path) -> None:
    lic = ROOT / "LICENSE"
    lic_audit = ROOT / "docs" / "LICENSE_AUDIT.md"

    bundle = _make_fake_bundle(tmp_path / "b1")
    out1 = tmp_path / "out1"
    zip_name = "LyraForge-dev-20261123-a1b2c3d-windows-x64.zip"
    zip_path, sums_path, digest = rh.package_windows_bundle(
        bundle,
        out1,
        zip_name=zip_name,
        license_path=lic,
        license_audit_path=lic_audit,
    )
    assert zip_path.is_file()
    assert sums_path.read_text(encoding="utf-8") == f"{digest}  {zip_name}\n"
    expected_sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert digest == expected_sha
    assert rh.verify_sha256sums(sums_path, zip_path) == expected_sha

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
        readme = zf.read("LyraForge/README.txt").decode("utf-8")
    assert "LyraForge/LyraForge.exe" in names
    assert "LyraForge/LICENSE" in names
    assert "LyraForge/LICENSE_AUDIT.md" in names
    assert "LyraForge/_internal/apps/desktop/web/dist/index.html" in names
    assert "LyraForge/_internal/webview/lib/Microsoft.Web.WebView2.Core.dll" in names
    assert "LyraForge/_internal/pythonnet/runtime/Python.Runtime.dll" in names
    assert "LyraForge.exe" in readme
    assert "startup.log" in readme

    # Check tampered SHA256SUMS fails
    sums_path.write_text(f"{'0' * 64}  {zip_name}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        rh.verify_sha256sums(sums_path, zip_path)

    # Check negative validation cases
    negative_cases = [
        ({"include_dll": False, "include_gui_host": False}, "_internal/"),
        ({"include_index": False}, "index.html"),
        ({"include_js": False}, "JS assets"),
        ({"include_css": False}, "CSS assets"),
        ({"include_instrument": False}, "instrument profile"),
        ({"include_schema": False}, "performance schema"),
        ({"include_gui_host": False}, "desktop GUI payload"),
        ({"include_secret": True}, "sensitive file"),
    ]
    for idx, (kwargs, err_match) in enumerate(negative_cases):
        bad_bundle = _make_fake_bundle(tmp_path / f"neg_{idx}", **kwargs)
        with pytest.raises(ValueError, match=err_match):
            rh.package_windows_bundle(
                bad_bundle,
                tmp_path / f"neg_out_{idx}",
                zip_name=zip_name,
                license_path=lic,
            )

    # Non-GPL LICENSE inside archive is rejected
    fake_lic = tmp_path / "NOT_GPL_LICENSE"
    fake_lic.write_text("Proprietary All Rights Reserved", encoding="utf-8")
    with pytest.raises(ValueError, match="GNU GPL-3.0"):
        rh.package_windows_bundle(
            bundle,
            tmp_path / "bad_lic_out",
            zip_name=zip_name,
            license_path=fake_lic,
        )


# ---------------------------------------------------------------------------
# 3. Release notes content & mocked idempotent GitHub Release publishing
# ---------------------------------------------------------------------------


def _fake_runner_factory(
    *,
    initial_main_head: str = "",
) -> tuple[
    Any,
    dict[str, dict[str, Any]],
    dict[str, str],
    list[list[str]],
    dict[str, Any],
]:
    releases: dict[str, dict[str, Any]] = {}
    tag_refs: dict[str, str] = {}
    calls: list[list[str]] = []
    state: dict[str, Any] = {"main_head": initial_main_head, "fail_main_ref": False}
    publish_seq = 0

    def run_cmd(cmd: list[str] | tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        nonlocal publish_seq
        c = list(cmd)
        calls.append(c)

        if c[:2] == ["gh", "api"]:
            if "--method" in c and "PATCH" in c:
                endpoint = c[c.index("PATCH") + 1]
                tag = endpoint.rsplit("/", 1)[-1]
                sha_arg = [x for x in c if x.startswith("sha=")][0].split("=", 1)[1]
                tag_refs[tag] = sha_arg
                return subprocess.CompletedProcess(
                    c, 0, json.dumps({"object": {"sha": sha_arg}}), ""
                )
            endpoint = c[2]
            if endpoint.endswith("/git/ref/heads/main"):
                if state["fail_main_ref"]:
                    return subprocess.CompletedProcess(c, 1, "", "503 Service Unavailable")
                return subprocess.CompletedProcess(
                    c,
                    0,
                    json.dumps({
                        "ref": "refs/heads/main",
                        "object": {"sha": state["main_head"]},
                    }),
                    "",
                )
            if endpoint.startswith("repos/") and "/git/refs/tags/" in endpoint:
                tag = endpoint.rsplit("/", 1)[-1]
                if tag in tag_refs:
                    return subprocess.CompletedProcess(
                        c, 0, json.dumps({"object": {"sha": tag_refs[tag]}}), ""
                    )
                return subprocess.CompletedProcess(c, 1, "", "404 Not Found")
            if endpoint.endswith("releases?per_page=100"):
                payload = [
                    {
                        "tag_name": t,
                        "prerelease": info["prerelease"],
                        "published_at": info["published_at"],
                    }
                    for t, info in releases.items()
                ]
                return subprocess.CompletedProcess(c, 0, json.dumps(payload), "")

        if c[:3] == ["gh", "release", "view"]:
            tag = c[3]
            if tag not in releases:
                return subprocess.CompletedProcess(c, 1, "", "release not found")
            info = releases[tag]
            return subprocess.CompletedProcess(
                c,
                0,
                json.dumps({
                    "tagName": tag,
                    "url": info["url"],
                    "assets": [{"name": a} for a in info["assets"]],
                }),
                "",
            )

        if c[:3] == ["gh", "release", "create"]:
            tag = c[3]
            if "--verify-tag" in c and tag not in tag_refs:
                return subprocess.CompletedProcess(c, 1, "", "tag does not exist remotely")
            publish_seq += 1
            if "--target" in c:
                tag_refs[tag] = c[c.index("--target") + 1]
            assets = [Path(a).name for a in c[4:] if Path(a).is_file()]
            is_pre = "--prerelease" in c
            releases[tag] = {
                "url": f"https://github.com/PariyaProject/LyraForge/releases/tag/{tag}",
                "assets": list(dict.fromkeys(assets)),
                "prerelease": is_pre,
                "title": c[c.index("--title") + 1],
                "notes": Path(c[c.index("--notes-file") + 1]).read_text(encoding="utf-8"),
                "published_at": f"2026-11-23T00:00:{publish_seq:02d}Z",
            }
            return subprocess.CompletedProcess(c, 0, "", "")

        if c[:3] == ["gh", "release", "edit"]:
            tag = c[3]
            if tag not in releases:
                return subprocess.CompletedProcess(c, 1, "", "release not found")
            releases[tag]["title"] = c[c.index("--title") + 1]
            releases[tag]["notes"] = Path(c[c.index("--notes-file") + 1]).read_text(
                encoding="utf-8"
            )
            releases[tag]["prerelease"] = "--prerelease" in c
            return subprocess.CompletedProcess(c, 0, "", "")

        if c[:3] == ["gh", "release", "upload"]:
            tag = c[3]
            assert "--clobber" in c
            idx = c.index("--clobber") + 1
            for raw_asset in c[idx:]:
                name = Path(raw_asset).name
                if name not in releases[tag]["assets"]:
                    releases[tag]["assets"].append(name)
            return subprocess.CompletedProcess(c, 0, "", "")

        if c[:3] == ["gh", "release", "delete-asset"]:
            tag, asset_name = c[3], c[4]
            releases[tag]["assets"] = [a for a in releases[tag]["assets"] if a != asset_name]
            return subprocess.CompletedProcess(c, 0, "", "")

        if c[:3] == ["gh", "release", "delete"]:
            tag = c[3]
            releases.pop(tag, None)
            tag_refs.pop(tag, None)
            return subprocess.CompletedProcess(c, 0, "", "")

        raise AssertionError(f"unexpected command: {c}")

    return run_cmd, releases, tag_refs, calls, state


def test_idempotent_publish_rolling_entry_pruning_and_semver_isolation(tmp_path: Path) -> None:
    lic = ROOT / "LICENSE"
    bundle = _make_fake_bundle(tmp_path / "bundle")
    run_cmd, releases, tag_refs, calls, state = _fake_runner_factory()

    # Safety guard refuses force-moving any SemVer or non-rolling tag
    with pytest.raises(ValueError, match="protected"):
        rh._update_rolling_dev_tag(
            repo="PariyaProject/LyraForge",
            tag="v0.1.0",
            sha="a" * 40,
            run_cmd=run_cmd,
        )
    with pytest.raises(ValueError, match="protected"):
        rh._update_rolling_dev_tag(
            repo="PariyaProject/LyraForge",
            tag="dev-20261123-aaaaaaa",
            sha="a" * 40,
            run_cmd=run_cmd,
        )

    # Protected non-release plan does nothing
    pr_plan = rh.resolve_release_plan(
        event_name="pull_request",
        ref="refs/pull/1/merge",
        sha="1" * 40,
        commit_date_yyyymmdd="20261123",
        build_timestamp_utc="2026-11-23T04:00:00Z",
    )
    pr_zip, pr_sums, _ = rh.package_windows_bundle(
        bundle, tmp_path / "pr_dist", zip_name=pr_plan.zip_name, license_path=lic
    )
    pr_res = rh.publish_release(
        plan=pr_plan, zip_path=pr_zip, checksums_path=pr_sums, run_cmd=run_cmd
    )
    assert pr_res["published"] is False
    assert calls == []

    # First main push creates dev snapshot + rolling dev-latest (Pre-release)
    sha1 = "1111111" + "0" * 33
    state["main_head"] = sha1
    plan1 = rh.resolve_release_plan(
        event_name="push",
        ref="refs/heads/main",
        sha=sha1,
        commit_date_yyyymmdd="20261123",
        build_timestamp_utc="2026-11-23T04:00:00Z",
    )
    zip1, sums1, _ = rh.package_windows_bundle(
        bundle, tmp_path / "d1", zip_name=plan1.zip_name, license_path=lic
    )
    res1 = rh.publish_release(
        plan=plan1,
        zip_path=zip1,
        checksums_path=sums1,
        retain_dev_snapshots=2,
        run_cmd=run_cmd,
    )
    assert res1["published"] is True
    assert set(releases) == {"dev-20261123-1111111", "dev-latest"}
    assert releases["dev-latest"]["prerelease"] is True
    assert releases["dev-20261123-1111111"]["prerelease"] is True
    assert "Experimental Pre-release Build" in releases["dev-latest"]["notes"]
    assert sha1 in releases["dev-latest"]["notes"]
    assert "calibration.status = unverified" in releases["dev-latest"]["notes"]
    assert "WebView2" in releases["dev-latest"]["notes"]

    # Manual workflow_dispatch rerun on SAME commit edits in-place without duplicate releases/assets
    calls.clear()
    res1_rerun = rh.publish_release(
        plan=plan1,
        zip_path=zip1,
        checksums_path=sums1,
        retain_dev_snapshots=2,
        run_cmd=run_cmd,
    )
    assert res1_rerun["published"] is True
    assert set(releases) == {"dev-20261123-1111111", "dev-latest"}
    assert releases["dev-latest"]["assets"] == [plan1.zip_name, "SHA256SUMS.txt"]
    assert not any(c[:3] == ["gh", "release", "create"] for c in calls)
    assert not any("PATCH" in c for c in calls)  # Same SHA already matches

    # SemVer tag release is published independently and never touched by dev churn/pruning
    sha_sem = "abcdef1" + "0" * 33
    tag_refs["v0.1.0"] = sha_sem
    sem_plan = rh.resolve_release_plan(
        event_name="push",
        ref="refs/tags/v0.1.0",
        sha=sha_sem,
        commit_date_yyyymmdd="20261123",
        build_timestamp_utc="2026-11-23T05:00:00Z",
    )
    zip_sem, sums_sem, _ = rh.package_windows_bundle(
        bundle, tmp_path / "d_sem", zip_name=sem_plan.zip_name, license_path=lic
    )
    sem_res = rh.publish_release(
        plan=sem_plan, zip_path=zip_sem, checksums_path=sums_sem, run_cmd=run_cmd
    )
    assert sem_res["published"] is True
    assert releases["v0.1.0"]["prerelease"] is False
    assert tag_refs["dev-latest"] == sha1  # Untouched by SemVer publish

    # Two more main pushes: dev-latest moves forward cleanly & old snapshot gets pruned (retain=2),
    # while dev-latest replaces stale ZIP and v0.1.0 stays completely untouched!
    for idx, sha_n in enumerate(("2222222" + "0" * 33, "3333333" + "0" * 33), start=2):
        state["main_head"] = sha_n
        pl = rh.resolve_release_plan(
            event_name="push",
            ref="refs/heads/main",
            sha=sha_n,
            commit_date_yyyymmdd=f"2026112{2 + idx}",
            build_timestamp_utc=f"2026-11-2{2 + idx}T06:00:00Z",
        )
        zp, sm, _ = rh.package_windows_bundle(
            bundle, tmp_path / f"d_{idx}", zip_name=pl.zip_name, license_path=lic
        )
        rh.publish_release(
            plan=pl,
            zip_path=zp,
            checksums_path=sm,
            retain_dev_snapshots=2,
            run_cmd=run_cmd,
        )

    assert tag_refs["dev-latest"] == "3333333" + "0" * 33
    assert tag_refs["v0.1.0"] == sha_sem
    assert "v0.1.0" in releases
    assert "dev-latest" in releases
    assert "dev-20261123-1111111" not in releases  # Pruned older 3rd snapshot
    assert "dev-20261124-2222222" in releases
    assert "dev-20261125-3333333" in releases
    # Rolling dev-latest contains ONLY the newest ZIP + SHA256SUMS.txt (zero stale attachments)
    assert len(releases["dev-latest"]["assets"]) == 2
    assert set(releases["dev-latest"]["assets"]) == {
        "LyraForge-dev-20261125-3333333-windows-x64.zip",
        "SHA256SUMS.txt",
    }


# ---------------------------------------------------------------------------
# 4. Static audit of .github/workflows/ci.yml security & ordering gates
# ---------------------------------------------------------------------------


def test_ci_workflow_extends_existing_build_with_minimal_permissions_and_gates() -> None:
    ci_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    # Top-level minimal read-only permissions & single consolidated workflow
    assert "\npermissions:\n  contents: read\n" in ci_text
    assert 'tags:\n      - "v*.*.*"' in ci_text

    # ZIP packaging + extracted ZIP --self-check inside existing package-windows job
    assert "scripts/release_helper.py package" in ci_text
    assert "Expand-Archive" in ci_text
    assert "& $zipExe --self-check" in ci_text
    # The frozen EXE gate must also prove the PyWebView GUI host imports (missing pywebview
    # in the PyInstaller payload used to pass --self-check and then exit silently).
    assert "--self-check --check-gui" in ci_text
    assert "path: release-dist/" in ci_text

    # Downstream release job gates strictly on test + package-windows + package-macos,
    # write permission isolated, and strictly blocks pull_request & non-main branches
    assert "package-macos:" in ci_text
    assert "LyraForge-macos-arm64" in ci_text
    assert "--platform macos" in ci_text
    assert "Contents/Resources/lyraforge.icns" in ci_text
    rel_idx = ci_text.index("release-desktop:")
    rel_block = ci_text[rel_idx:]
    assert "needs: [test, package-windows, package-macos]" in rel_block
    assert "github.event_name == 'push' || github.event_name == 'workflow_dispatch'" in rel_block
    assert "github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v')" in rel_block
    assert "pull_request" not in rel_block
    assert "contents: write" in rel_block
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in rel_block
    assert "scripts/release_helper.py publish" in rel_block
    assert "--extra-dist-dir release-dist-macos" in rel_block


def test_cli_package_and_publish_entrypoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _make_fake_bundle(tmp_path / "cli_bundle", layout_under_internal=False)
    dist_dir = tmp_path / "release-dist"
    sha = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

    rc_pkg = rh.main([
        "package",
        "--bundle-dir",
        str(bundle),
        "--output-dir",
        str(dist_dir),
        "--license",
        str(ROOT / "LICENSE"),
        "--license-audit",
        str(ROOT / "docs" / "LICENSE_AUDIT.md"),
        "--event-name",
        "workflow_dispatch",
        "--ref",
        "refs/heads/main",
        "--sha",
        sha,
        "--commit-date",
        "20261123",
        "--build-time",
        "2026-11-23T03:30:00Z",
    ])
    assert rc_pkg == 0
    meta = json.loads((dist_dir / "release-meta.json").read_text(encoding="utf-8"))
    assert meta["zip_name"] == "LyraForge-dev-20261123-a1b2c3d-windows-x64.zip"
    assert (dist_dir / "SHA256SUMS.txt").is_file()

    run_cmd, releases, _refs, _calls, state = _fake_runner_factory(initial_main_head=sha)
    monkeypatch.setattr(rh, "default_run_cmd", run_cmd)
    rc_pub = rh.main([
        "publish",
        "--dist-dir",
        str(dist_dir),
        "--repo",
        "PariyaProject/LyraForge",
        "--event-name",
        "workflow_dispatch",
        "--ref",
        "refs/heads/main",
        "--sha",
        sha,
        "--retain-dev-snapshots",
        "10",
    ])
    assert rc_pub == 0
    assert set(releases) == {"dev-20261123-a1b2c3d", "dev-latest"}


def test_stale_ci_job_cannot_rollback_dev_latest(tmp_path: Path) -> None:
    lic = ROOT / "LICENSE"
    bundle = _make_fake_bundle(tmp_path / "stale_bundle")
    sha1 = "1111111" + "0" * 33
    sha2 = "2222222" + "0" * 33
    run_cmd, releases, tag_refs, calls, state = _fake_runner_factory(initial_main_head=sha1)

    plan1 = rh.resolve_release_plan(
        event_name="push",
        ref="refs/heads/main",
        sha=sha1,
        commit_date_yyyymmdd="20261123",
        build_timestamp_utc="2026-11-23T04:00:00Z",
    )
    zip1, sums1, _ = rh.package_windows_bundle(
        bundle, tmp_path / "s1", zip_name=plan1.zip_name, license_path=lic
    )
    res1 = rh.publish_release(plan=plan1, zip_path=zip1, checksums_path=sums1, run_cmd=run_cmd)
    assert res1["rolling_updated"] is True
    assert tag_refs["dev-latest"] == sha1

    # Advance remote main HEAD to sha2 and publish newer build
    state["main_head"] = sha2
    plan2 = rh.resolve_release_plan(
        event_name="push",
        ref="refs/heads/main",
        sha=sha2,
        commit_date_yyyymmdd="20261124",
        build_timestamp_utc="2026-11-24T04:00:00Z",
    )
    zip2, sums2, _ = rh.package_windows_bundle(
        bundle, tmp_path / "s2", zip_name=plan2.zip_name, license_path=lic
    )
    res2 = rh.publish_release(plan=plan2, zip_path=zip2, checksums_path=sums2, run_cmd=run_cmd)
    assert res2["rolling_updated"] is True
    assert tag_refs["dev-latest"] == sha2

    # Stale CI job or manual rerun for older sha1 while remote main HEAD is sha2
    calls.clear()
    res_stale = rh.publish_release(
        plan=plan1,
        zip_path=zip1,
        checksums_path=sums1,
        retain_dev_snapshots=1,
        run_cmd=run_cmd,
    )
    assert res_stale["published"] is True
    assert res_stale["rolling_updated"] is False
    assert "stale commit" in str(res_stale["rolling_skipped_reason"])
    assert res_stale["pruned_snapshots"] == []
    # dev-latest stays pinned to newer sha2 and keeps sha2's assets intact
    assert tag_refs["dev-latest"] == sha2
    assert set(releases["dev-latest"]["assets"]) == {plan2.zip_name, "SHA256SUMS.txt"}
    assert "dev-20261124-2222222" in releases
    # Zero PATCH, edit, upload, delete-asset, or delete calls touched dev-latest or snapshots
    assert not any("PATCH" in c for c in calls)
    assert not any(c[:4] == ["gh", "release", "edit", "dev-latest"] for c in calls)
    assert not any(c[:4] == ["gh", "release", "upload", "dev-latest"] for c in calls)
    assert not any(c[:3] == ["gh", "release", "delete"] for c in calls)

    # Fail-closed when remote main ref API fails -> never modifies dev-latest
    state["fail_main_ref"] = True
    with pytest.raises(RuntimeError, match="fetch remote main HEAD SHA"):
        rh.publish_release(plan=plan1, zip_path=zip1, checksums_path=sums1, run_cmd=run_cmd)
    assert tag_refs["dev-latest"] == sha2


def _make_fake_macos_app(root: Path, *, include_icns: bool = True) -> Path:
    app = root / "LyraForge.app"
    contents = app / "Contents"
    macos_dir = contents / "MacOS"
    res = contents / "Resources"
    fw = contents / "Frameworks"
    macos_dir.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    fw.mkdir(parents=True, exist_ok=True)

    exe = macos_dir / "LyraForge"
    exe.write_bytes(b"#!/bin/sh\necho ok\n")
    exe.chmod(0o755)
    (contents / "Info.plist").write_text("<plist></plist>", encoding="utf-8")
    if include_icns:
        (res / "lyraforge.icns").write_bytes(b"icns\x00\x00\x00\x20" + b"\x00" * 24)

    dist_dir = fw / "apps" / "desktop" / "web" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    assets = dist_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "index-abc.js").write_text("console.log('ok');", encoding="utf-8")
    (assets / "index-abc.css").write_text("body{}", encoding="utf-8")

    inst = fw / "lyraforge" / "instruments" / "data"
    inst.mkdir(parents=True, exist_ok=True)
    (inst / "windsong.json").write_text("{}", encoding="utf-8")
    sch = fw / "lyraforge" / "music_core" / "schemas"
    sch.mkdir(parents=True, exist_ok=True)
    (sch / "performance.schema.json").write_text("{}", encoding="utf-8")

    # Symlink matching PyInstaller BUNDLE layout
    (res / "apps").symlink_to("../Frameworks/apps")
    return app


def test_package_macos_bundle_preserves_symlinks_and_dual_publish(tmp_path: Path) -> None:
    lic = ROOT / "LICENSE"
    lic_audit = ROOT / "docs" / "LICENSE_AUDIT.md"
    win_bundle = _make_fake_bundle(tmp_path / "win")
    mac_app = _make_fake_macos_app(tmp_path / "mac")

    sha = "a1b2c3d" + "0" * 33
    win_plan = rh.resolve_release_plan(
        event_name="push",
        ref="refs/heads/main",
        sha=sha,
        commit_date_yyyymmdd="20261124",
        build_timestamp_utc="2026-11-24T01:00:00Z",
        arch="windows-x64",
    )
    mac_plan = rh.resolve_release_plan(
        event_name="push",
        ref="refs/heads/main",
        sha=sha,
        commit_date_yyyymmdd="20261124",
        build_timestamp_utc="2026-11-24T01:00:00Z",
        arch="macos-arm64",
    )

    win_zip, win_sums, _ = rh.package_windows_bundle(
        win_bundle,
        tmp_path / "dist-win",
        zip_name=win_plan.zip_name,
        license_path=lic,
        license_audit_path=lic_audit,
    )
    mac_zip, mac_sums, _ = rh.package_macos_bundle(
        mac_app,
        tmp_path / "dist-mac",
        zip_name=mac_plan.zip_name,
        license_path=lic,
        license_audit_path=lic_audit,
    )
    assert mac_sums.is_file()
    info = rh.validate_macos_release_zip(mac_zip)
    assert info["zip_name"] == mac_plan.zip_name

    # Reject symlink escaping bundle
    bad_zip = tmp_path / "escape.zip"
    with zipfile.ZipFile(mac_zip, "r") as src, zipfile.ZipFile(bad_zip, "w") as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        esc = zipfile.ZipInfo("LyraForge.app/Contents/Resources/escape")
        esc.create_system = 3
        esc.external_attr = (0o120777) << 16
        dst.writestr(esc, "../../../../etc/passwd")
    with pytest.raises(ValueError, match="symlink escapes LyraForge.app"):
        rh.validate_macos_release_zip(bad_zip)

    run_cmd, releases, _refs, _calls, _state = _fake_runner_factory(initial_main_head=sha)
    rh.publish_release(
        plan=win_plan,
        zip_path=win_zip,
        checksums_path=win_sums,
        extra_artifacts=[(mac_plan, mac_zip)],
        run_cmd=run_cmd,
    )
    # Run idempotent update to exercise dev-latest upload + stale asset pruning too
    res = rh.publish_release(
        plan=win_plan,
        zip_path=win_zip,
        checksums_path=win_sums,
        extra_artifacts=[(mac_plan, mac_zip)],
        run_cmd=run_cmd,
    )
    assert res["published"] is True
    assert set(releases["dev-latest"]["assets"]) == {
        win_plan.zip_name,
        mac_plan.zip_name,
        "SHA256SUMS.txt",
    }
    assert "xattr -dr com.apple.quarantine" in releases["dev-latest"]["notes"]

