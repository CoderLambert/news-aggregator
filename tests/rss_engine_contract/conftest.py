"""Separate pytest root avoids importing Django or the workspace database."""
import json
import os
from pathlib import Path
import subprocess
import time

import pytest
import requests

from contract import PersistentContentProbe, isolated_project

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "ops/rss/T00/compose.yaml"


class Lab:
    def __init__(self, project):
        self.command = ["docker", "compose", "-p", project, "-f", str(COMPOSE)]

    def compose(self, *args):
        return subprocess.run(self.command + list(args), check=True, text=True,
                              capture_output=True, timeout=120).stdout.strip()

    def assert_local_new_project(self, project):
        # DOCKER_CONTEXT takes precedence over DOCKER_HOST in the Docker CLI.
        endpoint = None if os.environ.get("DOCKER_CONTEXT") else os.environ.get("DOCKER_HOST")
        endpoint = endpoint or subprocess.run(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            check=True, text=True, capture_output=True, timeout=10).stdout.strip()
        if not endpoint.startswith("unix://"):
            pytest.fail("T00 requires a local Unix-socket Docker daemon")
        networks = subprocess.run(["docker", "network", "ls", "--filter",
            f"label=com.docker.compose.project={project}", "-q"],
            check=True, text=True, capture_output=True, timeout=10).stdout.strip()
        if networks or self.compose("ps", "-aq"):
            pytest.fail("refusing to reuse existing project resources")

    def url(self, service, port):
        address = self.compose("port", service, str(port))
        assert address.startswith("127.0.0.1:"), "API must bind only loopback"
        return "http://" + address

    def sql(self, query):
        return self.compose("exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1",
                            "-U", "rss_contract", "-d", "rss_contract", "-Atc", query)

    def client(self, service="engine", admin=False):
        session = requests.Session()
        session.trust_env = False
        return PersistentContentProbe(self.url(service, 8080),
            username="t00_admin" if admin else "t00_collector",
            password="synthetic-t00-admin" if admin else "synthetic-t00-collector",
            timeout=(3, 10), session=session)

    def wait_ready(self, service):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                self.client(service, admin=True).me()
                return
            except Exception as exc:
                last = type(exc).__name__
                time.sleep(0.5)
        raise AssertionError(f"{service} failed readiness: {last}")


@pytest.fixture(scope="module")
def lab():
    if os.environ.get("RSS_TEST_ALLOW_LIVE") != "1":
        pytest.skip("live Docker experiment requires RSS_TEST_ALLOW_LIVE=1")
    path = os.environ.get("RSS_TEST_CONFIG")
    if not path:
        pytest.fail("RSS_TEST_CONFIG is required for live tests")
    project = isolated_project(json.loads(Path(path).read_text()))
    result = Lab(project)
    result.assert_local_new_project(project)
    try:
        result.compose("up", "-d", "--wait")
        for service in ("engine", "guarded"):
            result.wait_ready(service)
            admin = result.client(service, admin=True)
            admin.create_user("t00_collector", "synthetic-t00-collector", is_admin=False)
            admin.close()
            assert result.client(service).me()["is_admin"] is False
        result.fixture_url = result.url("fixture", 8000)
        yield result
    finally:
        # Operates only on this fresh allowlisted project, including on failure.
        result.compose("down", "--volumes", "--remove-orphans")
