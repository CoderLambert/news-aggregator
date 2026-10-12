from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from django.test import override_settings


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
MIGRATION_SCRIPT = REPO_ROOT / "scripts" / "docker-migrate.py"
PYTHONPATH = os.pathsep.join((str(BACKEND_ROOT), str(REPO_ROOT / "crawler")))
TEST_SECRET = "ISOLATED_DATA_PATH_TEST_SECRET_0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _environment(tmp_path: Path, *, mode: str, **overrides: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": PYTHONPATH,
        "PYTHONNOUSERSITE": "1",
        "HOME": str(tmp_path),
        "DJANGO_ENV": mode,
        "RUN_MAIN": "true",
    }
    if mode == "production":
        env.update(
            {
                "DJANGO_DEBUG": "0",
                "DJANGO_SECRET_KEY": TEST_SECRET,
                "WAITRESS_TRUSTED_PROXY": "127.0.0.1",
            }
        )
    env.update(overrides)
    return env


def _settings_probe(tmp_path: Path, *, mode: str, **overrides: str):
    script = """
import json
import newsaggregator.settings as settings
print(json.dumps({
    'database': str(settings.DATABASES['default']['NAME']),
    'chroma': str(settings.CHROMA_DATA_DIR),
    'tts': str(settings.TTS_CACHE_DIR),
}))
"""
    env = _environment(tmp_path, mode=mode, **overrides)
    if mode == "development":
        env.pop("DJANGO_DEBUG", None)
        script = """
import sys, types
dotenv = types.ModuleType('dotenv')
dotenv.load_dotenv = lambda *args, **kwargs: None
sys.modules['dotenv'] = dotenv
""" + script
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_production_data_paths_use_adr009_defaults(tmp_path):
    result = _settings_probe(tmp_path, mode="production")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "database": "/var/lib/newshub/db/db.sqlite3",
        "chroma": "/var/lib/newshub/chroma",
        "tts": "/var/lib/newshub/tts",
    }
    assert TEST_SECRET not in result.stdout + result.stderr


def test_data_paths_accept_explicit_absolute_production_overrides(tmp_path):
    database = tmp_path / "isolated-db" / "db.sqlite3"
    chroma = tmp_path / "isolated-chroma"
    tts = tmp_path / "isolated-tts"
    result = _settings_probe(
        tmp_path,
        mode="production",
        DJANGO_DB_PATH=str(database),
        CHROMA_DATA_DIR=str(chroma),
        TTS_CACHE_DIR=str(tts),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "database": str(database),
        "chroma": str(chroma),
        "tts": str(tts),
    }
    assert not database.exists()


@pytest.mark.parametrize(
    "variable",
    ("DJANGO_DB_PATH", "CHROMA_DATA_DIR", "TTS_CACHE_DIR"),
)
def test_relative_production_data_paths_fail_closed_without_echoing_secret(
    tmp_path, variable
):
    result = _settings_probe(tmp_path, mode="production", **{variable: "relative/path"})
    assert result.returncode != 0
    assert variable in result.stderr
    assert TEST_SECRET not in result.stdout + result.stderr


def test_development_data_path_defaults_remain_compatible(tmp_path):
    result = _settings_probe(tmp_path, mode="development")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "database": str(BACKEND_ROOT / "db.sqlite3"),
        "chroma": str(REPO_ROOT / "chroma_data"),
        "tts": str(BACKEND_ROOT / "media" / "tts_cache"),
    }


def test_vector_store_uses_configured_chroma_directory(tmp_path):
    from api.services.vector_store import VectorStoreService

    chroma_path = tmp_path / "vectors"
    with override_settings(CHROMA_DATA_DIR=chroma_path):
        assert VectorStoreService().chroma_dir == chroma_path
    assert chroma_path.is_dir()


def test_tts_cache_uses_configured_directory(tmp_path):
    from api.services import tts_service

    cache_path = tmp_path / "tts-cache"
    with override_settings(TTS_CACHE_DIR=cache_path):
        audio_path = Path(tts_service.save_to_cache(17, "test-variant", b"test-audio"))
    assert audio_path.parent == cache_path
    assert audio_path.read_bytes() == b"test-audio"


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("newshub_docker_migrate", MIGRATION_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_wrapper_runs_against_a_new_isolated_sqlite_database(tmp_path):
    database = tmp_path / "new-volume" / "db.sqlite3"
    result = subprocess.run(
        [sys.executable, str(MIGRATION_SCRIPT)],
        cwd=REPO_ROOT,
        env=_environment(tmp_path, mode="production", DJANGO_DB_PATH=str(database)),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert database.is_file()
    assert (database.parent / ".newshub-migrate.lock").is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM django_migrations"
        ).fetchone()[0] > 0


def test_migration_wrapper_refuses_a_concurrent_database_lock(tmp_path):
    database = tmp_path / "locked-volume" / "db.sqlite3"
    migration = _load_migration_module()
    with migration.migration_lock(database):
        result = subprocess.run(
            [sys.executable, str(MIGRATION_SCRIPT)],
            cwd=REPO_ROOT,
            env=_environment(tmp_path, mode="production", DJANGO_DB_PATH=str(database)),
            text=True,
            capture_output=True,
            check=False,
        )
    assert result.returncode == 75
    assert "Another migration already holds" in result.stderr
    assert not database.exists()
