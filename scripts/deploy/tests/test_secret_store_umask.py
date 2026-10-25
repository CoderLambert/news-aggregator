"""Secret file modes must not depend on the operator or CI process umask."""
import os
import stat

import pytest

from scripts.deploy.local_full_runtime import LocalRuntimeError, PENDING, SecretStore


@pytest.mark.parametrize('mask', [0o027, 0o077])
def test_creation_sets_container_readable_mode_under_restrictive_umask(tmp_path, mask):
    store = SecretStore(tmp_path / 'secrets')
    previous = os.umask(mask)
    try:
        path = store.ensure('project-key', lambda: 'synthetic-key')
        reused = store.ensure('project-key', lambda: 'must-not-replace')
    finally:
        os.umask(previous)

    assert reused == path
    assert path.read_text() == 'synthetic-key\n'
    assert stat.S_IMODE(path.stat().st_mode) == 0o444
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700


@pytest.mark.parametrize('mask', [0o027, 0o077])
def test_replacement_sets_mode_independently_of_creation_umask(tmp_path, mask):
    # Prepare a valid existing secret independently so a creation bug cannot
    # prevent this test from exercising the atomic replacement path.
    root = tmp_path / 'secrets'
    root.mkdir(mode=0o700)
    path = root / 'project-key'
    path.write_text(PENDING + '\n')
    path.chmod(0o444)
    store = SecretStore(root)

    previous = os.umask(mask)
    try:
        replaced = store.replace_pending('project-key', 'synthetic-replacement')
    finally:
        os.umask(previous)

    assert replaced == path
    assert store.read('project-key') == 'synthetic-replacement'
    assert stat.S_IMODE(path.stat().st_mode) == 0o444
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert not (root / '.project-key.new').exists()


@pytest.mark.parametrize('operation', ['create', 'replace'])
def test_permission_failure_is_not_reported_as_a_success(tmp_path, monkeypatch, operation):
    store = SecretStore(tmp_path / 'secrets')
    if operation == 'replace':
        store.root.mkdir(mode=0o700)
        existing = store.root / 'project-key'
        existing.write_text(PENDING + '\n')
        existing.chmod(0o444)

    def reject_mode_change(_fd, _mode):
        raise OSError('synthetic permission failure with sensitive details')

    monkeypatch.setattr(os, 'fchmod', reject_mode_change)
    with pytest.raises(LocalRuntimeError, match='could not (create|replace pending) runtime secret') as caught:
        if operation == 'create':
            store.ensure('project-key', lambda: 'synthetic-key')
        else:
            store.replace_pending('project-key', 'synthetic-replacement')
    assert 'sensitive details' not in str(caught.value)
    if operation == 'replace':
        assert store.read('project-key') == PENDING
