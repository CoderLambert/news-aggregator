"""Disposable local PostgreSQL and real LiteLLM processes for T00 only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def isolated_env() -> dict[str, str]:
    # Never copy os.environ, provider keys, HTTP proxies, or database settings.
    return {"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "DO_NOT_TRACK": "1"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def group_has_live_members(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    # Linux containers may retain an adopted zombie until PID 1 reaps it.
    # Zombies cannot perform work and must not be mistaken for live producers.
    proc = Path("/proc")
    if proc.is_dir():
        for path in proc.iterdir():
            if not path.name.isdecimal():
                continue
            try:
                fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
                if int(fields[2]) == pgid and fields[0] != "Z":
                    return True
            except (OSError, ValueError, IndexError):
                continue
        return False
    return True


def post_json(url: str, body: dict, key: str) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with OPENER.open(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("T00_ADMIN_HTTP_" + str(exc.code)) from None


class LocalProxy:
    def __init__(self, python: str, upstream_url: str):
        self.python = Path(python).absolute()
        self.prefix = self.python.parent.parent
        self.upstream_url = upstream_url
        self.processes: list[subprocess.Popen] = []
        self.handles = []
        self.runtime: Path | None = None
        self.pgroot: Path | None = None
        self.master = "sk-" + secrets.token_hex(32)
        self.project_keys: dict[str, str] = {}
        self.versions: dict[str, str] = {}
        self.url = "http://127.0.0.1:" + str(free_port())
        self.cleanup_complete = False

    def _run(self, argv: list[str], env: dict, *, stage: str, user=None, group=None) -> None:
        child = subprocess.Popen(
            argv, env=env, cwd=self.pgroot if user is not None else self.runtime, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            user=user, group=group, start_new_session=True,
        )
        self.processes.append(child)
        child.communicate(timeout=90)
        if child.returncode:
            # Raw subprocess output can contain synthetic credentials and URLs.
            raise RuntimeError("T00_" + stage + "_FAILED")

    def _spawn(self, argv: list[str], env: dict, log_name: str, **kwargs) -> subprocess.Popen:
        output = (self.runtime / log_name).open("wb")
        self.handles.append(output)
        child = subprocess.Popen(
            argv, env=env, cwd=self.pgroot if kwargs.get("user") is not None else self.runtime, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True, **kwargs,
        )
        self.processes.append(child)
        return child

    def __enter__(self):
        try:
            self.start()
            return self
        except BaseException:
            self.close()
            raise

    def start(self) -> None:
        self.runtime = Path(tempfile.mkdtemp(prefix="byok-t00-"))
        self.pgroot = Path(tempfile.mkdtemp(prefix="byok-t00-pg-"))
        env = isolated_env()
        env["XDG_RUNTIME_DIR"] = str(self.runtime)
        metadata = subprocess.run(
            [str(self.python), "-c", "import importlib.metadata,json,sys;d=importlib.metadata.distribution('pgserver');print(json.dumps({'pg_bin':str(d.locate_file('pgserver/pginstall/bin')),'versions':{**{name:importlib.metadata.version(name) for name in ('litellm','pgserver','prisma')},'proxy_python':sys.version.split()[0]}}))"],
            env=env, capture_output=True, text=True, timeout=15, check=True,
        )
        installed = json.loads(metadata.stdout)
        self.versions = installed["versions"]
        if self.versions["litellm"] != "1.105.0":
            raise RuntimeError("T00_PROXY_VERSION_MISMATCH")
        pg_bin = Path(installed["pg_bin"])
        uid = gid = None
        if os.geteuid() == 0:
            # PostgreSQL refuses root. Use the existing unprivileged account;
            # never let pgserver create users or change system permissions.
            account = pwd.getpwnam("nobody")
            uid, gid = account.pw_uid, account.pw_gid
            os.chown(self.pgroot, uid, gid)
            # CI venvs can be beneath a root-owned 0700 temporary directory.
            # Copy the bundled PostgreSQL runtime into our own cluster scratch
            # space; never chmod users' parent paths or create system accounts.
            runtime_copy = self.pgroot / "pgserver/pginstall"
            shutil.copytree(pg_bin.parent, runtime_copy)
            # Linux wheels use $ORIGIN/../../../pgserver.libs in RPATH.
            # Preserve that layout instead of inheriting an LD_LIBRARY_PATH.
            libraries = pg_bin.parents[2] / "pgserver.libs"
            if libraries.is_dir():
                shutil.copytree(libraries, self.pgroot / "pgserver.libs")
            for path in self.pgroot.rglob("*"):
                os.chown(path, uid, gid)
            pg_bin = runtime_copy / "bin"
        password = secrets.token_hex(32)
        password_file = self.pgroot / "password"
        password_file.write_text(password)
        password_file.chmod(0o600)
        if uid is not None:
            os.chown(password_file, uid, gid)
        data_dir = self.pgroot / "data"
        # Commands only point to this fresh cluster; no database URL is accepted.
        self._run(
            [str(pg_bin / "initdb"), "-D", str(data_dir), "-U", "t00", "--auth=scram-sha-256", "--pwfile", str(password_file), "--encoding=UTF8", "--no-locale"],
            env, stage="POSTGRES_INIT", user=uid, group=gid,
        )
        pg_port = free_port()
        pg = self._spawn(
            [str(pg_bin / "postgres"), "-D", str(data_dir), "-h", "127.0.0.1", "-p", str(pg_port), "-k", str(self.pgroot)],
            env, "postgres.log", user=uid, group=gid,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if pg.poll() is not None:
                raise RuntimeError("T00_POSTGRES_START_FAILED")
            try:
                with socket.create_connection(("127.0.0.1", pg_port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("T00_POSTGRES_START_TIMEOUT")
        env.update({
            "DATABASE_URL": f"postgresql://t00:{password}@127.0.0.1:{pg_port}/postgres",
            "LITELLM_MASTER_KEY": self.master,
            "LITELLM_SALT_KEY": secrets.token_hex(32),
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "PRISMA_BINARY_CACHE_DIR": str(self.prefix / "t00-prisma/binaries"),
            "PRISMA_NODEENV_CACHE_DIR": str(self.prefix / "t00-prisma/nodeenv"),
            "PYTHONPATH": str(ROOT / "ops/shared-litellm-proxy"),
            "BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat",
            "BYOK_DENY_STREAMING_CALL_TYPES": "",
        })
        # prepare_proxy.py generated this offline-ready Prisma toolchain.
        prisma_schema = self.prefix / "t00-prisma/schema.prisma"
        if not prisma_schema.is_file():
            raise RuntimeError("T00_RUN_PREPARE_PROXY_FIRST")
        node = Path(json.loads((self.prefix / "t00-prisma/runtime.json").read_text())["node"])
        if not node.is_file():
            raise RuntimeError("T00_PREPARED_NODE_MISSING")
        env["PATH"] = os.pathsep.join((str(self.python.parent), str(node.parent), os.defpath))
        env["CHECKPOINT_DISABLE"] = "1"
        env["PRISMA_HIDE_UPDATE_MESSAGE"] = "True"
        self._run(
            [str(self.python), "-m", "prisma", "db", "push", "--skip-generate", "--schema", str(prisma_schema)],
            env, stage="TEMP_SCHEMA",
        )
        model_list = [{
            "model_name": "deepseek/deepseek-chat",
            "litellm_params": {
                "model": "deepseek/deepseek-chat",
                "api_base": self.upstream_url + "/v1",
                "timeout": 20.0,
            },
        }]
        for suffix, model in (("", "test-model"), ("-other", "other-test-model")):
            for protocol, provider in (("chat", "openai"), ("messages", "anthropic")):
                model_list.append({"model_name": f"t00{suffix}-{protocol}", "litellm_params": {
                    "model": provider + "/" + model,
                    "api_base": self.upstream_url + ("/v1" if provider == "openai" else ""),
                    "api_key": "sk-t00-nonfunctional-deployment-sentinel",
                    "timeout": 1.0,
                }})
        config = {
            "model_list": model_list,
            "general_settings": {
                "master_key": "os.environ/LITELLM_MASTER_KEY", "database_url": "os.environ/DATABASE_URL",
                "forward_llm_provider_auth_headers": False, "forward_client_headers_to_llm_api": False,
                "store_prompts_in_spend_logs": False,
            },
            "router_settings": {"num_retries": 0, "fallbacks": [], "allowed_fails": 1000},
            "litellm_settings": {
                "callbacks": "provider_key_guard.proxy_handler_instance", "num_retries": 0,
                "cache": False, "turn_off_message_logging": True,
                "redact_messages_in_exceptions": True, "telemetry": False, "set_verbose": False,
            },
        }
        config_path = self.runtime / "proxy.yaml"
        config_path.write_text(json.dumps(config))
        config_path.chmod(0o600)
        proxy = self._spawn(
            [str(self.python), str(HERE / "proxy_process.py"), "--config", str(config_path), "--port", self.url.rsplit(":", 1)[1]],
            env, "proxy.log",
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if proxy.poll() is not None:
                raise RuntimeError("T00_PROXY_START_FAILED")
            try:
                with OPENER.open(self.url + "/health/readiness", timeout=0.5) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("T00_PROXY_START_TIMEOUT")
        for tenant, models in {
            "tenant-a": ["t00-chat", "t00-messages", "deepseek/deepseek-chat"],
            "tenant-b": ["t00-other-chat", "t00-other-messages"],
        }.items():
            result = post_json(self.url + "/key/generate", {"models": models, "key_alias": "t00-" + tenant}, self.master)
            key = result.get("key")
            if not isinstance(key, str) or not key.startswith("sk-"):
                raise RuntimeError("T00_PROJECT_KEY_CREATION_FAILED")
            self.project_keys[tenant] = key

    def close(self) -> None:
        clean = True
        for child in reversed(self.processes):
            try:
                # Own _spawn() creates a new process group. The leader may
                # already be gone while a Prisma query engine is still alive.
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 5
                while group_has_live_members(child.pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if group_has_live_members(child.pid):
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                child.wait(timeout=5)
                deadline = time.monotonic() + 2
                while group_has_live_members(child.pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                clean = clean and not group_has_live_members(child.pid)
            except (OSError, subprocess.TimeoutExpired):
                clean = False
        for handle in self.handles:
            try:
                handle.close()
            except OSError:
                clean = False
        for path in (self.runtime, self.pgroot):
            if path is not None:
                try:
                    shutil.rmtree(path)
                except FileNotFoundError:
                    pass
                except OSError:
                    clean = False
        self.cleanup_complete = clean

    def __exit__(self, *_args):
        self.close()
