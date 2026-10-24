import json
import io

import pytest

from scripts.deploy import app_network_unit as unit
from scripts.deploy import local_full_runtime


def test_recreate_unit_lists_sorted_service_app_sidecars():
    services = {
        'translation-redis': {'network_mode': 'service:app'},
        'app': {'image': 'example'},
        'ai-gateway': {'network_mode': 'service:app'},
        'channel-worker': {'network_mode': 'service:app'},
        'indexer': {'image': 'example'},
    }
    assert unit.recreate_unit(services) == [
        'app', 'ai-gateway', 'channel-worker', 'translation-redis',
    ]


def test_recreate_unit_without_sidecars_is_app_only():
    assert unit.recreate_unit({'app': {}, 'database': {}}) == ['app']


def test_expand_services_expands_app_alone_and_rejects_partial_unit():
    full = ['app', 'ai-gateway', 'channel-worker', 'translation-redis']
    assert unit.expand_services_for_app_action(['app'], full) == full
    assert unit.expand_services_for_app_action(['indexer'], full) == ['indexer']
    assert unit.expand_services_for_app_action(full, full) == full
    with pytest.raises(unit.AppNetworkUnitError, match='partial app network unit'):
        unit.expand_services_for_app_action(['app', 'ai-gateway'], full)


def test_expand_keeps_non_unit_services_after_contiguous_unit():
    full = ['app', 'ai-gateway', 'channel-worker', 'translation-redis']
    assert unit.expand_services_for_app_action(
        ['indexer', 'app', 'rss-db'], full,
    ) == full + ['indexer', 'rss-db']


def test_unit_from_compose_json_rejects_unsafe_names():
    with pytest.raises(unit.AppNetworkUnitError, match='unsafe service name'):
        unit.unit_from_compose_json(json.dumps({
            'services': {'app': {}, 'bad name': {'network_mode': 'service:app'}},
        }))


def test_require_app_network_unit_accepts_required_services_contract():
    services = {
        'app': {},
        'ai-gateway': {'network_mode': 'service:app'},
        'channel-worker': {'network_mode': 'service:app'},
        'translation-redis': {'network_mode': 'service:app'},
    }
    assert local_full_runtime.require_app_network_unit(
        services, local_full_runtime.REQUIRED_SERVICES,
    ) == ['app', 'ai-gateway', 'channel-worker', 'translation-redis']


def test_require_app_network_unit_fails_closed_when_sidecar_omitted():
    services = {
        'app': {},
        'ai-gateway': {'network_mode': 'service:app'},
        'orphan': {'network_mode': 'service:app'},
    }
    with pytest.raises(local_full_runtime.LocalRuntimeError, match='orphan'):
        local_full_runtime.require_app_network_unit(services, ('app', 'ai-gateway'))


def test_list_unit_cli_reads_stdin_json(capsys, monkeypatch):
    payload = json.dumps({
        'services': {
            'app': {},
            'z-sidecar': {'network_mode': 'service:app'},
            'a-sidecar': {'network_mode': 'service:app'},
        },
    })
    monkeypatch.setattr(unit.sys, 'stdin', io.StringIO(payload))
    assert unit.main(['list-unit', '--from-json', '--project', 'preview-test']) == 0
    assert capsys.readouterr().out.splitlines() == ['app', 'a-sidecar', 'z-sidecar']


def test_recreate_app_cli_defaults_to_dry_run(capsys, monkeypatch, tmp_path):
    compose = tmp_path / 'compose.yaml'
    compose.write_text('services: {}\n')

    def fake_discover(**kwargs):
        return ['app', 'ai-gateway', 'translation-redis']

    monkeypatch.setattr(unit, 'discover_unit_from_compose', fake_discover)

    def fail_run(*_args, **_kwargs):
        raise AssertionError('dry-run must not call docker')

    monkeypatch.setattr(unit, '_run', fail_run)
    result = unit.main([
        'recreate-app',
        '--project', 'newshub-local-main',
        '--compose', str(compose),
    ])
    assert result == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan['execute'] is False
    assert plan['unit'] == ['app', 'ai-gateway', 'translation-redis']
    assert 'force-recreate' in plan['action']
