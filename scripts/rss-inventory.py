#!/usr/bin/env python3
"""Build a non-executable inventory from code and optional sanitized evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from api.rss.migration_inventory import build_inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='sanitized consistent-copy evidence JSON, never an active DB')
    parser.add_argument('--targets', type=Path, help='reviewed inventory-key to target HTTPS Feed mapping JSON')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    result = build_inventory(ROOT, baseline,
        snapshot=json.loads(args.snapshot.read_text()) if args.snapshot else None,
        targets=json.loads(args.targets.read_text()) if args.targets else None)
    # Exclusive creation prevents accidentally replacing a reviewed source manifest.
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(f"{len(result['sources'])} sources; snapshot={result['snapshot_status']}; production_ready=false")


if __name__ == '__main__':
    main()
