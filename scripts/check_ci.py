"""Inspect and diagnose GitHub Actions CI status for a commit SHA."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def resolve_commit_sha(ref: str) -> str:
    res = _run(["git", "rev-parse", ref])
    if res.returncode != 0:
        raise RuntimeError(f"failed to resolve git ref {ref!r}: {res.stderr.strip()}")
    return res.stdout.strip()


def find_run_for_sha(repo: str, sha: str) -> dict[str, Any] | None:
    res = _run([
        "gh",
        "run",
        "list",
        "--repo",
        repo,
        "--limit",
        "25",
        "--json",
        "databaseId,headSha,status,conclusion,url,displayTitle,event,createdAt",
    ])
    if res.returncode != 0:
        raise RuntimeError(f"gh run list failed: {res.stderr.strip()}")
    runs = json.loads(res.stdout or "[]")
    for run in runs:
        if str(run.get("headSha", "")).lower() == sha.lower():
            return dict(run)
    return None


def inspect_run(
    repo: str, run_id: int, *, watch: bool = False, log_lines: int = 120
) -> dict[str, Any]:
    if watch:
        subprocess.run(
            ["gh", "run", "watch", str(run_id), "--repo", repo],
            check=False,
        )

    view = _run([
        "gh",
        "run",
        "view",
        str(run_id),
        "--repo",
        repo,
        "--json",
        "databaseId,headSha,status,conclusion,url,jobs",
    ])
    if view.returncode != 0:
        raise RuntimeError(f"gh run view failed: {view.stderr.strip()}")
    data = json.loads(view.stdout)

    jobs_summary = []
    for job in data.get("jobs") or []:
        failed_steps = [
            s.get("name")
            for s in (job.get("steps") or [])
            if s.get("conclusion") not in (None, "", "success", "skipped")
        ]
        jobs_summary.append({
            "id": job.get("databaseId"),
            "name": job.get("name"),
            "status": job.get("status"),
            "conclusion": job.get("conclusion"),
            "url": job.get("url"),
            "failed_steps": failed_steps,
        })

    failed_excerpt = ""
    if data.get("conclusion") not in (None, "", "success"):
        logs = _run(["gh", "run", "view", str(run_id), "--repo", repo, "--log-failed"])
        raw_lines = (logs.stdout or logs.stderr or "").splitlines()
        failed_excerpt = "\n".join(raw_lines[-max(1, log_lines) :])

    return {
        "run_id": data.get("databaseId"),
        "head_sha": data.get("headSha"),
        "status": data.get("status"),
        "conclusion": data.get("conclusion"),
        "url": data.get("url"),
        "jobs": jobs_summary,
        "failed_log_excerpt": failed_excerpt,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check GitHub Actions CI run for a commit SHA.")
    parser.add_argument("--repo", default="PariyaProject/LyraForge", help="GitHub owner/repo")
    parser.add_argument("--sha", default="HEAD", help="Git ref or SHA to inspect (default: HEAD)")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Wait for run creation and stream until completion",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=30,
        help="Max seconds to wait for GitHub Actions run creation when --watch is set",
    )
    parser.add_argument(
        "--log-lines",
        type=int,
        default=120,
        help="Trailing failed log lines to include on non-success runs",
    )
    args = parser.parse_args(argv)

    try:
        sha = resolve_commit_sha(args.sha)
        deadline = time.monotonic() + (args.wait_seconds if args.watch else 0)
        run = find_run_for_sha(args.repo, sha)
        while run is None and time.monotonic() < deadline:
            time.sleep(3)
            run = find_run_for_sha(args.repo, sha)

        if run is None:
            print(
                json.dumps(
                    {
                        "repo": args.repo,
                        "head_sha": sha,
                        "status": "missing",
                        "conclusion": None,
                        "error": f"No GitHub Actions run found for commit {sha}",
                    },
                    indent=2,
                )
            )
            return 2

        report = inspect_run(
            args.repo,
            int(run["databaseId"]),
            watch=bool(args.watch),
            log_lines=int(args.log_lines),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report.get("status") == "completed" and report.get("conclusion") == "success":
            return 0
        return 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
