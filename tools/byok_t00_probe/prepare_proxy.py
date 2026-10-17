"""Prepare Prisma's official generated client before offline T00 execution.

Run with the isolated Proxy interpreter. Downloads are limited to dependency
preparation; this command creates no database and has no provider credentials.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    if importlib.metadata.version("litellm") != "1.105.0":
        raise RuntimeError("T00_PROXY_VERSION_MISMATCH")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("T00_NODE_REQUIRED_FOR_PRISMA_SETUP")
    root = Path(sys.prefix) / "t00-prisma"
    root.mkdir(mode=0o700, exist_ok=True)
    schema = Path(importlib.metadata.distribution("litellm-proxy-extras").locate_file("litellm_proxy_extras/schema.prisma"))
    # The schema is unchanged; native-only engine selection avoids downloading
    # unused platform binaries. No business or existing database is touched.
    source = re.sub(r"binaryTargets\s*=\s*\[[^\]]+\]", 'binaryTargets = ["native"]', schema.read_text())
    (root / "schema.prisma").write_text(source)
    env = {
        "PATH": os.pathsep.join((str(Path(sys.executable).parent), str(Path(node).parent), os.defpath)),
        "PRISMA_BINARY_CACHE_DIR": str(root / "binaries"),
        "PRISMA_NODEENV_CACHE_DIR": str(root / "nodeenv"),
        "PRISMA_USE_GLOBAL_NODE": "True",
        "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
        "DO_NOT_TRACK": "1",
        "npm_config_cache": str(root / "npm-cache"),
        "npm_config_userconfig": str(root / "empty.npmrc"),
    }
    (root / "empty.npmrc").write_text("")
    # Dependency preparation can use the execution host's network proxy. The
    # offline protocol runner has a different, empty environment allowlist.
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "all_proxy", "no_proxy", "npm_config_http_proxy", "npm_config_https_proxy", "NODE_EXTRA_CA_CERTS"):
        if name in os.environ:
            env[name] = os.environ[name]
    result = subprocess.run(
        [sys.executable, "-m", "prisma", "generate", "--schema", str(root / "schema.prisma")],
        env=env, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240,
    )
    if result.returncode:
        # No raw installer output: it may contain environment-derived URLs.
        print(json.dumps({"preparation": "FAIL", "error": "PRISMA_GENERATION_FAILED"}))
        return 1
    (root / "runtime.json").write_text(json.dumps({"node": node}))
    print(json.dumps({"preparation": "PASS", "litellm": "1.105.0", "provider_requests": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
