import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT = Path(__file__).resolve().parents[3]
MODULE_PATH = PROJECT / 'scripts' / 'deploy' / 'local_domain_fixtures.py'
SPEC = importlib.util.spec_from_file_location('local_domain_fixtures_tested', MODULE_PATH)
fixtures = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(fixtures)


def test_create_bundle_is_private_synthetic_and_does_not_print_credentials(tmp_path, capsys):
    bundle_path = tmp_path / 'fixtures.json'
    bundle = fixtures.create_bundle(bundle_path)
    info = bundle_path.stat()

    assert stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_uid == os.getuid()
    assert bundle['users']['a']['username'].startswith('nhsmoke_a_')
    assert bundle['users']['b']['email'].endswith('@example.invalid')
    assert len(bundle['registration_probes']) == 20
    assert len({item['username'] for item in bundle['registration_probes']}) == 20
    assert bundle['invitations']['a']['token'] in bundle_path.read_text(encoding='utf-8')

    output = capsys.readouterr().out
    assert output == ''
    assert bundle['invitations']['a']['token'] not in output
    assert all(bundle['users'][role]['password'] not in output for role in bundle['users'])


def test_load_bundle_rejects_wrong_mode_symlink_and_tampered_schema(tmp_path):
    bundle_path = tmp_path / 'fixtures.json'
    bundle = fixtures.create_bundle(bundle_path)
    assert fixtures.load_bundle(bundle_path)['run_id'] == bundle['run_id']

    bundle_path.chmod(0o644)
    with pytest.raises(ValueError, match='mode-0600'):
        fixtures.load_bundle(bundle_path)
    bundle_path.chmod(0o600)

    tampered = dict(bundle)
    tampered['schema_version'] = 999
    bundle_path.write_text(json.dumps(tampered), encoding='utf-8')
    bundle_path.chmod(0o600)
    with pytest.raises(ValueError, match='unsupported'):
        fixtures.load_bundle(bundle_path)

    bundle_path.unlink()
    link = tmp_path / 'fixtures-link.json'
    link.symlink_to(tmp_path / 'missing-target')
    with pytest.raises(ValueError, match='symlink'):
        fixtures.load_bundle(link)


def test_emit_program_compiles_and_guards_environment_before_django_setup(tmp_path):
    bundle = fixtures.create_bundle(tmp_path / 'fixtures.json')
    program = fixtures.render_app_program(bundle, 'seed')
    compile(program, '<private-g2-fixture>', 'exec')
    assert program.index('project = env.get("NEWSHUB_LOCAL_DOMAIN_PROJECT"') < program.index('import django')
    assert 'User.objects.exists()' in program
    assert 'hashlib.sha256(invite["token"].encode("utf-8")).hexdigest()' in program
    assert 'PUBLIC_SITE_MODE") != "full"' in program
    assert 'settings.DATABASES["default"]["NAME"]' in program

    # Source and credentials travel through stdin, never a process argument.
    # The missing runtime confirmation must stop before Django setup/database access.
    process = subprocess.run(
        [sys.executable, '-'], input=program, capture_output=True, text=True,
        env={'PATH': os.environ.get('PATH', '')}, check=False,
    )
    assert process.returncode != 0
    assert process.stdout == ''
    assert process.stderr.strip() == 'local-domain fixture precondition failed'
    assert bundle['users']['a']['password'] not in process.stderr


def test_only_fixed_fixture_phases_can_be_rendered(tmp_path):
    bundle = fixtures.create_bundle(tmp_path / 'fixtures.json')
    for phase in ('seed', 'attach-owner', 'deactivate-admin', 'audit', 'login-rate-count', 'registration-rate-counts'):
        assert '_FIXTURE_PHASE' in fixtures.render_app_program(bundle, phase)
    with pytest.raises(ValueError, match='unsupported'):
        fixtures.render_app_program(bundle, 'execute-provider')
