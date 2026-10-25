#!/usr/bin/env python3
"""Build the canonical production target and report BuildKit work, without skipping it."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


class BuildMetrics:
    """Parse interleaved --progress=plain vertices; never retain RUN output/secrets."""

    def __init__(self):
        self.vertices: dict[str, dict] = {}

    def feed(self, line: str) -> None:
        match = re.match(r"#(\d+) (.*)", line.strip())
        if not match:
            return
        key, text = match.groups()
        vertex = self.vertices.setdefault(key, {"status": "incomplete"})
        stage = re.match(r"\[([\w-]+)\s+\d+/\d+\] (RUN|COPY|WORKDIR|FROM)\b(.*)", text)
        if stage:
            stage_name, operation, command = stage.groups()
            # Report a fixed category, never arbitrary shell commands or URLs.
            kind = operation.lower()
            if operation == "RUN":
                if "pip install" in command:
                    kind = "torch-install" if "torch==" in command else "python-install"
                elif "npm ci" in command:
                    kind = "npm-install"
                elif "npm run build" in command:
                    kind = "frontend-build"
            vertex.update(stage=stage_name, operation=kind)
        elif text == "exporting to image":
            vertex.update(stage="export", operation="image-export")
        if text == "CACHED":
            vertex.update(status="cached", seconds=0.0)
        elif done := re.fullmatch(r"DONE ([\d.]+)s", text):
            vertex.update(status="executed", seconds=float(done.group(1)))
        elif text.startswith("ERROR:"):
            vertex["status"] = "failed"
        elif text == "CANCELED":
            vertex["status"] = "cancelled"

    def result(self, *, sha: str, exit_code: int, wall_seconds: float) -> dict:
        steps = [dict(id=key, **value) for key, value in self.vertices.items() if "stage" in value]
        dependency_steps = [s for s in steps if s["operation"] in {"torch-install", "python-install", "npm-install"}]
        return {
            "schema": 1, "release_sha": sha, "exit_code": exit_code,
            "wall_seconds": round(wall_seconds, 3), "steps": steps,
            "dependency_cache_hits": sum(s["status"] == "cached" for s in dependency_steps),
            "dependency_steps": len(dependency_steps),
            "note": "Step durations overlap; use wall_seconds for total build time. Cached downloads are not cached layers.",
        }


def markdown(report: dict) -> str:
    rows = [
        "### Production image build", "",
        f"Revision: `{report['release_sha']}`; exit: **{report['exit_code']}**; wall time: **{report['wall_seconds']:.3f}s**.",
        f"Dependency layer hits: {report['dependency_cache_hits']}/{report['dependency_steps']}.",
        "", "| Stage | Operation | Status | Seconds |", "|---|---|---|---:|",
    ]
    for step in report["steps"]:
        seconds = str(step["seconds"]) if "seconds" in step else "unknown"
        rows.append(f"| {step['stage']} | {step['operation']} | {step['status']} | {seconds} |")
    return "\n".join(rows + ["", report["note"], ""])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error("--sha must be a full lowercase Git SHA")
    if args.image != f"newshub:ci-{args.sha}":
        parser.error("--image must be the exact CI tag for --sha")
    if os.environ.get("DOCKER_HOST") != "unix:///ci-docker/docker.sock":
        parser.error("only the isolated CI Docker socket is allowed")

    metrics = BuildMetrics()
    started = time.monotonic()
    command = [
        "docker", "build", "--progress=plain", "--target", "production",
        "--build-arg", f"RELEASE_SHA={args.sha}", "--tag", args.image, ".",
    ]
    # Docker remains authoritative. No cache-hit short circuit, retry, pull,
    # pruning, install, or alternate image/target is performed by this wrapper.
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="replace", start_new_session=True) as process:
            def forward(signum, _frame):
                try:
                    os.killpg(process.pid, signum)
                except ProcessLookupError:
                    pass

            previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGTERM, signal.SIGINT)}
            try:
                for line in process.stdout:
                    print(line, end="", flush=True)
                    metrics.feed(line)
                code = process.wait()
                if code < 0:
                    code = 128 - code
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
    except OSError:
        print("production build could not start Docker", file=sys.stderr)
        code = 127
    report = metrics.result(sha=args.sha, exit_code=code, wall_seconds=time.monotonic() - started)
    try:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary, "a", encoding="utf-8") as stream:
                stream.write(markdown(report))
    except OSError:
        print("production build metrics could not be written", file=sys.stderr)
        # Never hide the original Docker failure behind a reporting error.
        return code or 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
