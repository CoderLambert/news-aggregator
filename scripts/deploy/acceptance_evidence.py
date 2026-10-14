#!/usr/bin/env python3
"""Offline operator evidence ledger; never probes production or runs a deploy.

This records checksums and status of operator-owned evidence artifacts.
A checksum proves only file integrity, never that the underlying release
criterion actually passed. Human acceptance remains separately required.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

GATES = {
    'NH-28-research-byok-auth': 'Real authorized BYOK-only research identity, routing and consent',
    'NH-28-research-runtime': 'Research cancellation, budgets and recovery acceptance',
    'NH-29-offhost-restore': 'Off-host backup and isolated restore rehearsal',
    'NH-29-key-recovery': 'Recovery of separately protected encryption keys',
    'NH-30-source-license': 'Publisher RSS/API license and attribution evidence',
    'NH-30-content-quality': 'Sampled canonical article URLs and complete body quality',
    'NH-31-vps-capacity': '2C/4GB isolated load test with resource observations',
    'NH-31-degradation': 'Graceful 429, SSE exhaustion and worker-failure behavior',
}
STATES = {'NOT_RUN', 'BLOCKED', 'EVIDENCE_RECORDED'}
HEX_SHA = re.compile(r'^[0-9a-f]{40}$')
HEX_HASH = re.compile(r'^[0-9a-f]{64}$')


class EvidenceError(ValueError):
    pass


def validate_release_sha(release_sha):
    if not isinstance(release_sha, str) or not HEX_SHA.fullmatch(release_sha):
        raise EvidenceError('release SHA must be full 40-character lowercase hex')
    return release_sha


def empty_ledger(release_sha):
    return {
        'schema': 1,
        'release_sha': validate_release_sha(release_sha),
        'gates': {
            name: {'status': 'NOT_RUN', 'evidence_file': '', 'sha256': '', 'operator_note': ''}
            for name in GATES
        },
    }


def _regular_private_file(path):
    if path.is_symlink() or not path.is_file():
        raise EvidenceError('evidence must be a regular file, not a symlink')
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise EvidenceError('evidence is accessible to group or others')
    return path


def digest_file(path):
    path = _regular_private_file(path)
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_ledger(value, *, evidence_root, expected_sha):
    validate_release_sha(expected_sha)
    if not isinstance(value, dict) or set(value) != {'schema', 'release_sha', 'gates'}:
        raise EvidenceError('invalid ledger fields')
    if value['schema'] != 1 or value['release_sha'] != expected_sha:
        raise EvidenceError('wrong schema or immutable release SHA')
    if not isinstance(value['gates'], dict) or set(value['gates']) != set(GATES):
        raise EvidenceError('gate list is incomplete or unknown')
    root = evidence_root.resolve(strict=True)
    if evidence_root.is_symlink() or not root.is_dir():
        raise EvidenceError('invalid evidence directory')
    pending = []
    for name in GATES:
        entry = value['gates'][name]
        if not isinstance(entry, dict) or set(entry) != {'status', 'evidence_file', 'sha256', 'operator_note'}:
            raise EvidenceError('invalid gate record for ' + name)
        state, filename, checksum, note = (
            entry['status'], entry['evidence_file'], entry['sha256'], entry['operator_note'])
        if state not in STATES or not isinstance(note, str) or len(note) > 1000:
            raise EvidenceError('invalid evidence status/note for ' + name)
        if state == 'EVIDENCE_RECORDED':
            if not isinstance(filename, str) or not filename or Path(filename).is_absolute() or '..' in Path(filename).parts:
                raise EvidenceError('invalid evidence file for ' + name)
            if not isinstance(checksum, str) or not HEX_HASH.fullmatch(checksum):
                raise EvidenceError('missing evidence digest for ' + name)
            file = (root / filename).resolve(strict=True)
            if not file.is_relative_to(root) or digest_file(file) != checksum:
                raise EvidenceError('evidence checksum mismatch for ' + name)
        else:
            if filename or checksum:
                raise EvidenceError('unverified evidence attached to incomplete gate ' + name)
            pending.append(name)
    return pending


def write_initial(path, release_sha):
    if path.is_symlink() or path.exists():
        raise EvidenceError('refusing to overwrite an existing ledger')
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise EvidenceError('ledger parent must be an existing ordinary directory')
    data = (json.dumps(empty_ledger(release_sha), indent=2, ensure_ascii=False) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as sink:
            sink.write(data)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    init = subs.add_parser('init')
    init.add_argument('--file', type=Path, required=True)
    init.add_argument('--sha', required=True)
    check = subs.add_parser('check')
    check.add_argument('--file', type=Path, required=True)
    check.add_argument('--sha', required=True)
    check.add_argument('--evidence-root', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            write_initial(args.file, args.sha)
            print('Initialized pending evidence ledger. No gate has passed.')
            return 0
        _regular_private_file(args.file)
        with args.file.open('r', encoding='utf-8') as f:
            ledger = json.load(f)
        pending = validate_ledger(ledger, evidence_root=args.evidence_root, expected_sha=args.sha)
        if pending:
            print('NOT_ACCEPTED: ' + ', '.join(pending))
            return 2
        print('EVIDENCE_RECORDED: all artifacts matched checksums. Independent operator acceptance still required.')
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print('Evidence invalid: ' + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
