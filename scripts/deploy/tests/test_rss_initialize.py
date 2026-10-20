"""Local maintenance boundary checks; never run against an existing site."""
import subprocess

import pytest

from scripts.rss import initialize


@pytest.mark.parametrize('project', ['newshub', 'production', 'newshub-prod-live', '../newshub-local-x'])
def test_local_initialization_rejects_other_names_before_container_operations(project, monkeypatch):
    monkeypatch.setenv('DOCKER_HOST', 'unix:///synthetic.sock')
    calls = []
    monkeypatch.setattr(initialize, 'run', lambda args, **kwargs: calls.append(args))
    with pytest.raises(initialize.InitializeError, match='local project'):
        initialize.inventory(project)
    assert calls == []


def test_local_initialization_rejects_remote_docker_and_never_retries_unknown_mutation(monkeypatch):
    monkeypatch.setenv('DOCKER_HOST', 'tcp://remote.example:2376')
    with pytest.raises(initialize.InitializeError, match='local Docker'):
        initialize.inventory('newshub-local-synthetic')
    calls = []
    def timeout(args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired(args, 1, stderr='synthetic-sensitive-upstream-detail-42')
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(initialize.InitializeError) as error:
        initialize.run(['synthetic-mutation'])
    assert calls == [['synthetic-mutation']]
    assert 'synthetic-sensitive-upstream-detail-42' not in str(error.value)
