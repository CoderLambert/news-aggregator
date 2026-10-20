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


def test_private_backup_access_preserves_nonroot_app_and_restores_owner_on_failure(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(initialize, 'run', lambda args, **kwargs: calls.append(args))
    with pytest.raises(RuntimeError, match='synthetic interruption'):
        with initialize.readable_backup(tmp_path, 'synthetic-image'):
            assert len(calls) == 1
            assert "os.chown(p,10001,10001)" in calls[0][-1]
            raise RuntimeError('synthetic interruption')
    assert len(calls) == 2
    assert 'os.chown(p,' + str(initialize.os.getuid()) + ',' in calls[1][-1]
    assert all('--network' in call and call[call.index('--network') + 1] == 'none' for call in calls)
    assert all('os.chmod(p,0o700)' in call[-1] and 'os.chmod(f,0o600)' in call[-1] for call in calls)
