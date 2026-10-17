"""Start the real pinned LiteLLM ASGI application with audited Python sockets.

This is an isolated test process, not an alternative gateway implementation.
Its configuration and database are generated in a private temporary directory.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import ipaddress
import os
import socket
import sys


def loopback_only(event: str, args: tuple) -> None:
    if event == "socket.connect":
        sock, address = args
        if sock.family == socket.AF_UNIX:
            return
        host = address[0]
    elif event == "socket.getaddrinfo":
        host = args[0]
    else:
        return
    if host in (None, "localhost", b"localhost"):
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise PermissionError("T00_NON_LOOPBACK_EGRESS_BLOCKED")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    if importlib.metadata.version("litellm") != "1.105.0":
        raise RuntimeError("T00_PROXY_VERSION_MISMATCH")
    # Installed SDKs may attempt remote cost-map refreshes at import time.
    # The audit hook is installed before LiteLLM and cannot be removed later.
    sys.addaudithook(loopback_only)
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["CONFIG_FILE_PATH"] = args.config
    from litellm.proxy.proxy_server import app
    import uvicorn

    # uvloop can open native sockets without Python's socket audit events.
    # Keep the actual HTTP client path on the audited standard asyncio loop.
    uvicorn.run(app, host="127.0.0.1", port=args.port, loop="asyncio", log_level="error", access_log=False)


if __name__ == "__main__":
    main()
