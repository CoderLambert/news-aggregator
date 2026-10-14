"""Offline release evidence gates; no network, production filesystem or credentials."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from scripts.deploy import acceptance_evidence as gates


SHA = 'a' * 40


def private_file(path, contents):
    path.write_text(contents)
    path.chmod(0o600)
    return path


def test_init_is_safe_default_and_refuses_overwrite(tmp_path):
    path = tmp_path / 'readiness.json'
    gates.write_initial(path, SHA)
    assert gates.empty_ledger(SHA)['gates']
    assert path.stat().st_mode & 0o077 == 0
    assert all(item['status'] == 'NOT_RUN' for item in json.loads(path.read_text())['gates'].values())
    with pytest.raises(gates.EvidenceError):
        gates.write_initial(path, SHA)
    assert gates.main(['check', '--file', str(path), '--sha', SHA, '--evidence-root', str(tmp_path)]) == 2


def test_records_required_artifacts_only_if_integrity_is_verified(tmp_path):
    path = tmp_path / 'readiness.json'
    data = gates.empty_ledger(SHA)
    artifact = private_file(tmp_path / 'restore-results.json', '{"restore_test":"synthetic"}')
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    for item in data['gates'].values():
        item.update(status='EVIDENCE_RECORDED', evidence_file=artifact.name,
                    sha256=digest, operator_note='Local synthetic verification only; requires operator review')
    assert gates.validate_ledger(data, evidence_root=tmp_path, expected_sha=SHA) == []
    artifact.write_text('modified')
    with pytest.raises(gates.EvidenceError):
        gates.validate_ledger(data, evidence_root=tmp_path, expected_sha=SHA)


def test_refuses_production_secret_paths_symlink_and_world_readable_artifacts(tmp_path):
    ledger = gates.empty_ledger(SHA)
    item = ledger['gates']['NH-29-key-recovery']
    item.update(status='EVIDENCE_RECORDED', evidence_file='secrets.json', sha256='0' * 64)
    with pytest.raises((FileNotFoundError, gates.EvidenceError)):
        gates.validate_ledger(ledger, evidence_root=tmp_path, expected_sha=SHA)
    private_file(tmp_path / 'secrets.json', 'placeholder')
    (tmp_path / 'secrets.json').chmod(0o644)
    item['sha256'] = gates.digest_file(tmp_path / 'secrets.json') if False else hashlib.sha256(b'placeholder').hexdigest()
    with pytest.raises(gates.EvidenceError):
        gates.validate_ledger(ledger, evidence_root=tmp_path, expected_sha=SHA)
    (tmp_path / 'secrets.json').chmod(0o600)
    item['evidence_file'] = '../secrets.json'
    with pytest.raises(gates.EvidenceError):
        gates.validate_ledger(ledger, evidence_root=tmp_path, expected_sha=SHA)
    item['evidence_file'] = 'shortcut'
    (tmp_path / 'shortcut').symlink_to(tmp_path / 'secrets.json')
    with pytest.raises(gates.EvidenceError):
        gates.validate_ledger(ledger, evidence_root=tmp_path, expected_sha=SHA)


def test_wrong_release_sha_never_inherits_prior_gate_completion(tmp_path):
    ledger = gates.empty_ledger(SHA)
    with pytest.raises(gates.EvidenceError):
        gates.validate_ledger(ledger, evidence_root=tmp_path, expected_sha='b' * 40)
    with pytest.raises(gates.EvidenceError):
        gates.empty_ledger('latest')


def test_pending_gate_cannot_borrow_a_hash_from_other_run(tmp_path):
    ledger = gates.empty_ledger(SHA)
    item = ledger['gates']['NH-30-source-license']
    item['sha256'] = '0' * 64
    with pytest.raises(gates.EvidenceError):
        gates.validate_ledger(ledger, evidence_root=tmp_path, expected_sha=SHA)
