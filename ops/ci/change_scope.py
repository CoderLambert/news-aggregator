#!/usr/bin/env python3
"""Route NewsHub CI jobs from the complete Git change range, fail-closed on uncertainty.

No third-party dependencies, GitHub token, network access or business configuration.
Missing history or an unknown path executes both suites instead of silently skipping.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

_SHA = re.compile(r"[a-fA-F0-9]{40,64}\Z")
# Keep aligned with `on.push/pull_request.paths-ignore` in ci.yml.
# Only non-executable docs and repository communication metadata belong here.
_ROOT_DOCUMENTS = {
    "README.md", "TESTING.md", "DEVLOG.md", "CHANGELOG.md",
    "frontend/README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
    "SECURITY.md", "LICENSE", "LICENSE.md", "NOTICE", "NOTICE.md",
    ".github/PULL_REQUEST_TEMPLATE.md", ".github/FUNDING.yml",
}
_DOCUMENT_PREFIXES = ("docs/", ".github/ISSUE_TEMPLATE/", ".github/PULL_REQUEST_TEMPLATE/")
_SHARED_FILES = {"Dockerfile", ".dockerignore", ".gitignore", ".gitattributes", "AGENTS.md"}
_BACKEND_FILES = {"pytest.ini", "conftest.py", "start_waitress.py"}
_SHARED_PREFIXES = (".github/", "ops/ci/", "deploy/", ".agents/", ".codex/")
_BACKEND_PREFIXES = (
    "backend/", "crawler/", "tests/", "ops/rss/",
    "ops/shared-litellm-proxy/", "tools/", "scripts/deploy/", "scripts/rss/",
)
_FRONTEND_CONTRACTS = {
    "backend/api/urls.py", "backend/api/serializers.py",
    "backend/newsaggregator/urls.py",
}


def classify_path(path: str) -> str:
    """Return 'frontend', 'backend', 'both', or 'docs' (no business suites)."""
    if not path or path.startswith("/") or "\\" in path or ".." in Path(path).parts:
        return "both"
    if path.startswith(_DOCUMENT_PREFIXES) or path in _ROOT_DOCUMENTS:
        return "docs"
    if path in _SHARED_FILES or path.startswith(_SHARED_PREFIXES):
        return "both"
    if path.startswith("compose") and path.endswith((".yaml", ".yml")):
        return "both"
    if path.startswith(".env"):
        return "both"
    if path in _FRONTEND_CONTRACTS:
        return "both"
    if path.startswith("backend/api/") and path.endswith(("_urls.py", "_serializers.py")):
        return "both"
    if path.startswith("frontend/"):
        return "frontend"
    if path.startswith(_BACKEND_PREFIXES) or path in _BACKEND_FILES:
        return "backend"
    # Unknown top-level assets, scripts or configuration can affect either
    # product, so conservatively run both.
    return "both"


def route_paths(paths: list[str]) -> tuple[bool, bool]:
    """Return (run_frontend, run_backend); empty/uncertain input runs both."""
    if not paths:
        return True, True
    scopes = {classify_path(path) for path in paths}
    return (bool(scopes & {"frontend", "both"}), bool(scopes & {"backend", "both"}))


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def changed_paths(event: str, before: str, base: str, head: str) -> list[str]:
    """Use merge-base for PRs; include every commit of a push (not HEAD^)."""
    if not _SHA.fullmatch(head):
        raise ValueError("missing/invalid head SHA")
    if event == "pull_request":
        if not _SHA.fullmatch(base):
            raise ValueError("missing/invalid PR base SHA")
        old = _git("merge-base", base, head).decode("ascii").strip()
        if not _SHA.fullmatch(old):
            raise ValueError("unable to resolve PR merge-base")
    elif event == "push":
        if not _SHA.fullmatch(before) or set(before) == {"0"}:
            raise ValueError("missing/invalid push before SHA")
        old = before
    else:
        raise ValueError("unexpected workflow event")
    # --no-renames classifies both old and new paths for renames across scopes.
    raw = _git("diff", "--name-only", "-z", "--no-renames", old, head, "--")
    return [os.fsdecode(part) for part in raw.split(b"\0") if part]


def _write_outputs(frontend: bool, backend: bool) -> None:
    result = f"frontend={str(frontend).lower()}\nbackend={str(backend).lower()}\n"
    target = os.getenv("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(result)
    print(result, end="")


def main() -> None:
    event = os.getenv("GITHUB_EVENT_NAME", "")
    try:
        paths = changed_paths(
            event,
            os.getenv("CI_BEFORE_SHA", ""),
            os.getenv("CI_BASE_SHA", ""),
            os.getenv("CI_HEAD_SHA", ""),
        )
        frontend, backend = route_paths(paths)
        scopes = {classify_path(path) for path in paths}
        print(f"Change routing: {len(paths)} paths; categories={sorted(scopes)}", file=sys.stderr)
    except (OSError, ValueError, subprocess.CalledProcessError, UnicodeError) as error:
        # No silent bypass when Git history, event metadata or git itself fails.
        frontend = backend = True
        print(f"Change routing uncertain ({type(error).__name__}); run BOTH suites", file=sys.stderr)
    _write_outputs(frontend, backend)


if __name__ == "__main__":
    main()
