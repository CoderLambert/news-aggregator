"""Allocate a fresh project; never accept an existing engine URL or database."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

root = Path(__file__).resolve().parents[3]
suite = root / "tests/rss_engine_contract"
with tempfile.TemporaryDirectory(prefix="newshub-rss-t00-") as directory:
    config = Path(directory) / "isolated.json"
    config.write_text(json.dumps({"environment": "isolated", "project": "newshub-rss-t00-" + uuid.uuid4().hex[:12]}))
    env = os.environ.copy()
    env.update(RSS_TEST_ALLOW_LIVE="1", RSS_TEST_CONFIG=str(config), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    print("T00 target:", config.read_text(), flush=True)
    result = subprocess.run([sys.executable, "-m", "pytest", "-c", str(suite / "pytest.ini"),
        "--confcutdir", str(suite), str(suite / "test_engine_contract.py"), "-m", "rss_live", "-v"], env=env)
    sys.exit(result.returncode)
