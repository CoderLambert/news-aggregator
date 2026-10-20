"""Restart wrapper targeting and ordering; no Docker daemon or site data."""
import importlib.util
import json
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/rss'))
spec = importlib.util.spec_from_file_location('channel_recovery_wrapper', ROOT / 'scripts/rss/recover_channels.py')
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


def fixture(monkeypatch, mismatch=False):
    containers = {name: {'Id': char*64, 'Image': 'sha256:candidate',
        'Config': {'Image': 'candidate:mutable', 'Env': []},
        'State': {'Running': True, 'StartedAt': '2026-10-20T00:00:00Z'}}
        for name, char in [('app','a'), ('rss-sync','b'), ('miniflux','c'), ('rss-db','d')]}
    if mismatch: containers['rss-sync']['Image'] = 'sha256:old'
    calls = []
    monkeypatch.setattr(wrapper, 'inventory', lambda p: (containers, {'RSS_ENGINE_INSTANCE_UUID': 'synthetic', 'RSS_ENGINE_ACCOUNT_ID': '3'}))
    monkeypatch.setattr(wrapper, 'run', lambda cmd, **kw: calls.append(cmd) or (b'{"resolved_operations":3}' if 'rss_recovery_boundary' in cmd else b''))
    return containers, calls


def test_same_mutable_tag_but_different_image_is_rejected_before_any_stop(monkeypatch, tmp_path):
    _, calls = fixture(monkeypatch, mismatch=True)
    with pytest.raises(ValueError, match='same recovery candidate'):
        wrapper.main(['--project','newshub-local-test','--receipt',str(tmp_path/'receipt.json'),'--apply'])
    assert calls == []


def test_preview_checks_capability_but_never_stops_or_restarts(monkeypatch, tmp_path):
    _, calls = fixture(monkeypatch)
    wrapper.main(['--project','newshub-local-test','--receipt',str(tmp_path/'receipt.json')])
    assert len(calls) == 1 and calls[0][:2] == ['docker','exec']
    assert not (tmp_path/'receipt.json').exists()


def test_apply_observes_stop_then_same_container_restart_before_recording_and_resuming(monkeypatch, tmp_path):
    containers, calls = fixture(monkeypatch)
    def inspect(identity):
        if identity == 'b'*64:
            return {**containers['rss-sync'], 'State': {'Running': False, 'FinishedAt': '2026-10-21T00:00:00Z'}}
        assert identity == 'c'*64
        return {**containers['miniflux'], 'State': {'Running': True, 'StartedAt': '2026-10-21T00:00:01Z'}}
    monkeypatch.setattr(wrapper, 'inspect', inspect)
    receipt = tmp_path/'receipt.json'
    wrapper.main(['--project','newshub-local-test','--receipt',str(receipt),'--apply'])
    assert [c[1] for c in calls] == ['exec','stop','restart','exec','exec','start']
    assert json.loads(receipt.read_text())['engine_container'] == 'c'*64
    assert calls[3][0:3] == ['docker', 'exec', '-i']
    assert calls[-1] == ['docker','start','b'*64]
