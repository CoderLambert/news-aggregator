"""T31 upgrade: identify old writers without defining or reviving old services."""
import copy
import json
from unittest.mock import Mock

import pytest

from scripts.deploy import release_manifest as release
from scripts.deploy.tests.test_release_operations import manifest


def test_v4_retired_image_starts_only_retained_workers(tmp_path, capsys):
    value = manifest()
    value.update(schema_version=4, capabilities={
        'crawler_worker': False, 'full_content_worker': False, 'channel_worker': True,
    })
    assert release.validate_manifest(value) == value
    path = tmp_path / 'release.json'
    path.write_text(json.dumps(value))
    assert release.main(['worker-services', '--manifest', str(path)]) == 0
    assert capsys.readouterr().out.splitlines() == ['indexer', 'channel-worker']
    # Historical artifacts retain their original role meaning.
    old = copy.deepcopy(value)
    old['schema_version'] = 3
    del old['capabilities']['crawler_worker']
    assert release.crawler_worker_capability(release.validate_manifest(old)) is True


@pytest.mark.parametrize('bad', [None, 'false', 0, {}, {'crawler_worker': False}])
def test_v4_rejects_ambiguous_retirement_capabilities(bad):
    value = manifest()
    value.update(schema_version=4, capabilities=bad)
    with pytest.raises(release.ManifestError):
        release.validate_manifest(value)


def test_stop_includes_retired_roles_and_checks_project_before_any_stop(monkeypatch):
    selected = {'crawler': 'a' * 12, 'full-content': 'b' * 12, 'indexer': 'c' * 12}
    labels = {identity: {'com.docker.compose.project': 't31-fixture',
        'com.docker.compose.service': service} for service, identity in selected.items()}
    calls = []
    def docker(*args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == 'ps':
            service = args[-1].rsplit('=', 1)[1]
            return selected.get(service, '')
        if args[0] == 'inspect':
            return json.dumps(labels[args[-1]]) if '.Config.Labels' in args[2] else 'false'
        assert args[0] == 'stop' and args[1:3] == ('--time', '45')
        assert kwargs['timeout'] == 60
        return args[-1]
    monkeypatch.setattr(release, '_docker_text', docker)
    assert set(release.project_writers('t31-fixture')) == set(selected.values())
    assert not any(args[0] == 'stop' for args, _ in calls)
    assert set(release.project_writers('t31-fixture', stop=True)) == set(selected.values())
    assert {args[-1] for args, _ in calls if args[0] == 'stop'} == set(selected.values())
    calls.clear()
    labels[selected['indexer']]['com.docker.compose.project'] = 'another-project'
    with pytest.raises(release.ManifestError, match='labels'):
        release.project_writers('t31-fixture', stop=True)
    assert not any(args[0] == 'stop' for args, _ in calls)


@pytest.mark.parametrize('project', ['../other', '--all', '', 'with space', 'A' * 80, 'a' * 64])
def test_invalid_project_never_calls_docker(monkeypatch, project):
    docker = Mock(side_effect=AssertionError('must validate first'))
    monkeypatch.setattr(release, '_docker_text', docker)
    with pytest.raises(release.ManifestError):
        release.project_writers(project, stop=True)
    docker.assert_not_called()


def test_local_start_dispatches_only_web_processes_and_rejects_retired_crawl(tmp_path):
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    command = tmp_path / 'news'
    command.write_text((root / 'scripts/news').read_text())
    for name in ('news-server', 'news-dev'):
        child = tmp_path / name
        child.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + ':$1"\n')
        child.chmod(0o700)
    result = subprocess.run(['bash', str(command), 'start'], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert 'news-server:start' in result.stdout and 'news-dev:start' in result.stdout
    assert '爬虫' not in result.stdout
    retired = subprocess.run(['bash', str(command), 'crawl'], capture_output=True, text=True, timeout=5)
    assert retired.returncode == 2 and '已退役' in retired.stderr
    assert not retired.stdout
    assert not (root / 'scripts/news-aggregator-crawl.timer').exists()


@pytest.mark.parametrize('project', ['a' * 63, 'project_01-test'])
def test_writer_selection_preserves_existing_deploy_cli_project_names(monkeypatch, project):
    docker = Mock(return_value='')
    monkeypatch.setattr(release, '_docker_text', docker)
    assert release.project_writers(project) == []
    assert docker.call_count == 6
    assert all(f'label=com.docker.compose.project={project}' in call.args for call in docker.call_args_list)
