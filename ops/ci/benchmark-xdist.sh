#!/usr/bin/env bash
# Opt-in, full-coverage benchmark. Never modify the shared backend venv or
# existing pytest defaults. All three test roots run in each xdist repetition.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"
PYTHON="$ROOT/backend/venv/bin/python"
CACHE_ROOT="${XDG_CACHE_HOME:-$HOME/.cache}/newshub-xdist"
[[ "$CACHE_ROOT" == /* && "$CACHE_ROOT" != / && ! -L "$CACHE_ROOT" ]] || {
    echo 'xdist cache root must be absolute and not a symlink' >&2; exit 2;
}
[[ -x "$PYTHON" && -d "${TMPDIR:-}" ]] || {
    echo 'backend venv and private TMPDIR must already exist' >&2; exit 2;
}
REPEATS="${CI_XDIST_REPEATS:-3}"
[[ "$REPEATS" =~ ^[123]$ ]] || { echo 'CI_XDIST_REPEATS must be 1..3' >&2; exit 2; }
KEY="$(printf 'xdist-3.8.0|execnet-2.1.1|%s\n' "$("$PYTHON" -c 'import sys; print(sys.implementation.cache_tag)')" | sha256sum | cut -d' ' -f1)"
CACHE="$CACHE_ROOT/$KEY"
mkdir -p "$CACHE_ROOT"
chmod 700 "$CACHE_ROOT"
exec 9>"$CACHE_ROOT/.install.lock"
flock -x 9
healthy() {
    [[ -d "$CACHE" && ! -L "$CACHE" && -f "$CACHE/.ready" ]] || return 1
    PYTHONPATH="$CACHE:${PYTHONPATH:-}" "$PYTHON" -c \
        'from importlib.metadata import version; assert version("pytest-xdist") == "3.8.0" and version("execnet") == "2.1.1"' \
        >/dev/null 2>&1
}
if ! healthy; then
    [[ "$KEY" =~ ^[a-f0-9]{64}$ ]] || exit 2
    rm -rf -- "$CACHE"
    mkdir -p "$CACHE"
    "$PYTHON" -m pip install --disable-pip-version-check --no-deps --only-binary=:all: \
        --target "$CACHE" pytest-xdist==3.8.0 execnet==2.1.1
    PYTHONPATH="$CACHE:${PYTHONPATH:-}" "$PYTHON" -c \
        'from importlib.metadata import version; assert version("pytest-xdist") == "3.8.0" and version("execnet") == "2.1.1"'
    touch "$CACHE/.ready"
fi
flock -u 9
# These modules assume the serial Django migration/seed-state lifecycle.
# The initial full xdist run failed 16 cases across them on separate workers.
# Never relax the assertions; keep these files serial until their fixtures are
# independently proven safe with per-worker databases.
SERIAL_FILES=(
    backend/api/tests/test_smart_channel_workspace.py
    backend/api/tests/test_channels.py
    backend/api/tests/test_fetch_full_command.py
    backend/api/tests/test_crawler_dashboard_loading.py
    backend/api/tests/test_source_registry.py
    backend/api/tests/test_backfill_scrapy_command.py
    backend/api/tests/test_crawler_readiness.py
)
EXCLUDE_ARGS=()
for file in "${SERIAL_FILES[@]}"; do
    [[ -f "$file" ]] || { echo "missing serial-only safety test: $file" >&2; exit 2; }
    EXCLUDE_ARGS+=(--ignore="$file")
done
REPORT="$(mktemp -d "${TMPDIR}/newshub-xdist-benchmark.XXXXXX")"
printf 'xdist-benchmark: repeats=%s workers=2 dist=loadfile report=%s\n' "$REPEATS" "$REPORT"
for i in $(seq 1 "$REPEATS"); do
    start="$(date +%s)"
    # No xdist plugin in this command. State-sensitive files stay serial.
    "$PYTHON" -m pytest -q --durations=10 \
        --junitxml="$REPORT/serial-$i.xml" "${SERIAL_FILES[@]}" \
        2>&1 | tee "$REPORT/serial-$i.log"
    PYTHONPATH="$CACHE:${PYTHONPATH:-}" "$PYTHON" -m pytest \
        -q -n 2 --dist=loadfile --max-worker-restart=0 \
        --durations=25 --junitxml="$REPORT/parallel-$i.xml" \
        "${EXCLUDE_ARGS[@]}" tests/ backend/api/tests/ scripts/deploy/tests/ \
        2>&1 | tee "$REPORT/parallel-$i.log"
    # pytest's final terminal summary is authoritative for passed/skipped.
    # Some pytest/unittest combinations count XML testcase entries differently
    # than terminal outcomes; JUnit is still checked for real failures.
    "$PYTHON" - "$REPORT/serial-$i.log" "$REPORT/parallel-$i.log" \
        "$REPORT/serial-$i.xml" "$REPORT/parallel-$i.xml" <<'PY'
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

summary = re.compile(r'=+\s*(\d+) passed(?:, (\d+) skipped)? in [\d.]+s\s*=+')
passed = skipped = 0
for filename in sys.argv[1:3]:
    matches = [summary.search(line) for line in Path(filename).read_text(encoding="utf-8").splitlines()]
    matches = [match for match in matches if match is not None]
    if len(matches) != 1:
        raise SystemExit(f"xdist benchmark terminal summary missing or ambiguous: {filename}")
    passed += int(matches[0].group(1))
    skipped += int(matches[0].group(2) or "0")
for filename in sys.argv[3:]:
    document = ET.parse(filename)
    root = document.getroot()
    if any(root.iter("failure")) or any(root.iter("error")):
        raise SystemExit(f"xdist benchmark JUnit recorded an error or failure: {filename}")
if passed != 2408 or skipped != 16:
    raise SystemExit(
        f"xdist benchmark coverage mismatch: passed={passed} skipped={skipped}; "
        "expected 2408/16"
    )
print(f"xdist benchmark coverage PASS: passed={passed}, skipped={skipped}")
PY
    elapsed=$(( $(date +%s) - start ))
    printf 'xdist-benchmark: hybrid round %s/%s PASS elapsed=%ss\n' "$i" "$REPEATS" "$elapsed"
done
echo 'xdist-benchmark: three-root hybrid test matrix passed without retries'
