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
    assert program.index('configured_settings_module = env.get(') < program.index('import django')
    assert 'env["DJANGO_SETTINGS_MODULE"] = "newsaggregator.settings"' in program
    assert 'if configured_settings_module and configured_settings_module != "newsaggregator.settings": refuse()' in program
    assert 'User.objects.exists()' in program
    assert 'hashlib.sha256(invite["token"].encode("utf-8")).hexdigest()' in program
    assert 'PUBLIC_SITE_MODE") != "full"' in program
    assert 'NEWSHUB_LOCAL_DOMAIN_IMAGE_ID' in program
    assert 'sha256:[0-9a-f]{64}' in program
    assert 'Fixture article' in program
    assert 'Mermaid flow' in program
    assert '```mermaid' in program
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


def _bootstrap_only_program(program: str, database_root: Path) -> str:
    # Keep the real child guards and Django bootstrap, but replace only the
    # in-container DB root with a temp path and stop before fixture DB work.
    program = program.replace(
        'db_root = Path("/var/lib/newshub/db")',
        f'db_root = Path({str(database_root)!r})',
        1,
    )
    assert 'db_root = Path("/var/lib/newshub/db")' not in program
    assert '    fixture_database_phase()\n' in program
    program = program.replace(
        '    fixture_database_phase()\n',
        '    print("BOOTSTRAP_OK")\n',
        1,
    )
    # The fixed production UID is synthetic only in this offline child test.
    return 'import os\nos.getuid = lambda: 10001\n' + program


def test_real_django_bootstrap_sets_missing_settings_module_without_database_access(tmp_path):
    bundle = fixtures.create_bundle(tmp_path / 'fixtures.json')
    program = fixtures.render_app_program(bundle, 'seed')
    database_root = tmp_path / 'isolated-db'
    bootstrap_program = _bootstrap_only_program(program, database_root)
    compile(bootstrap_program, '<g2-django-bootstrap-only>', 'exec')
    home = tmp_path / 'home'
    temporary = tmp_path / 'tmp'
    home.mkdir(mode=0o700)
    temporary.mkdir(mode=0o700)
    database = database_root / 'db.sqlite3'
    project = 'newshub-local-g2-123-0123456789abcdef'
    env = {
        'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
        'PYTHONPATH': os.pathsep.join((str(PROJECT / 'backend'), str(PROJECT / 'crawler'))),
        'HOME': str(home),
        'TMPDIR': str(temporary),
        'DJANGO_ENV': 'production',
        'DJANGO_DEBUG': '0',
        'DJANGO_SECRET_KEY': 'Synthetic-Only-Key-A1b2C3d4' * 3,
        'DJANGO_DB_PATH': str(database),
        'NEWSHUB_LOCAL_DOMAIN_PROJECT': project,
        'NEWSHUB_LOCAL_DOMAIN_FIXTURE_CONFIRMATION': project,
        'NEWSHUB_LOCAL_DOMAIN_STAGE': 'g2',
        'NEWSHUB_LOCAL_DOMAIN_REVISION': 'a' * 40,
        'NEWSHUB_LOCAL_DOMAIN_IMAGE_ID': 'sha256:' + 'b' * 64,
        'WAITRESS_TRUSTED_PROXY': '127.0.0.1',
        'PUBLIC_SITE_MODE': 'full',
        'PUBLIC_SIGNUP_ENABLED': '1',
        'PUBLIC_AI_ENABLED': '0',
        'CHATGPT_PLAN_USAGE_ENABLED': '0',
        'CHATGPT_AUTH_MODE': 'disabled',
        'CRAWLER_SCHEDULER_ENABLED': '0',
        'CRAWL_RUN_ON_START': '0',
        'SEARCH_INDEX_ENABLED': '0',
        'RUN_MAIN': 'true',
    }
    process = subprocess.run(
        [sys.executable, '-'], input=bootstrap_program, capture_output=True, text=True,
        env=env, check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == 'BOOTSTRAP_OK'
    assert 'DJANGO_SETTINGS_MODULE' not in env
    assert not database.exists()


def test_wrong_settings_module_is_refused_before_django_setup(tmp_path):
    bundle = fixtures.create_bundle(tmp_path / 'fixtures.json')
    program = fixtures.render_app_program(bundle, 'seed')
    database_root = tmp_path / 'isolated-db'
    bootstrap_program = _bootstrap_only_program(program, database_root)
    home = tmp_path / 'home'
    temporary = tmp_path / 'tmp'
    home.mkdir(mode=0o700)
    temporary.mkdir(mode=0o700)
    database = database_root / 'db.sqlite3'
    project = 'newshub-local-g2-123-0123456789abcdef'
    env = {
        'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
        'PYTHONPATH': os.pathsep.join((str(PROJECT / 'backend'), str(PROJECT / 'crawler'))),
        'HOME': str(home),
        'TMPDIR': str(temporary),
        'DJANGO_ENV': 'production',
        'DJANGO_DEBUG': '0',
        'DJANGO_SECRET_KEY': 'Synthetic-Only-Key-A1b2C3d4' * 3,
        'DJANGO_DB_PATH': str(database),
        'NEWSHUB_LOCAL_DOMAIN_PROJECT': project,
        'NEWSHUB_LOCAL_DOMAIN_FIXTURE_CONFIRMATION': project,
        'NEWSHUB_LOCAL_DOMAIN_STAGE': 'g2',
        'NEWSHUB_LOCAL_DOMAIN_REVISION': 'a' * 40,
        'NEWSHUB_LOCAL_DOMAIN_IMAGE_ID': 'sha256:' + 'b' * 64,
        'WAITRESS_TRUSTED_PROXY': '127.0.0.1',
        'PUBLIC_SITE_MODE': 'full',
        'PUBLIC_SIGNUP_ENABLED': '1',
        'PUBLIC_AI_ENABLED': '0',
        'CHATGPT_PLAN_USAGE_ENABLED': '0',
        'CHATGPT_AUTH_MODE': 'disabled',
        'CRAWLER_SCHEDULER_ENABLED': '0',
        'CRAWL_RUN_ON_START': '0',
        'SEARCH_INDEX_ENABLED': '0',
        'RUN_MAIN': 'true',
        'DJANGO_SETTINGS_MODULE': 'synthetic.wrong.settings',
    }
    process = subprocess.run(
        [sys.executable, '-'], input=bootstrap_program, capture_output=True, text=True,
        env=env, check=False,
    )
    assert process.returncode != 0
    assert process.stdout == ''
    assert process.stderr.strip() == 'local-domain fixture precondition failed'
    assert not database.exists()


def test_fixture_program_failure_summary_uses_fixed_type_and_omits_exception_text(tmp_path):
    bundle = fixtures.create_bundle(tmp_path / 'fixtures.json')
    program = fixtures.render_app_program(bundle, 'seed')
    start = program.index('SAFE_EXCEPTION_TYPES = {')
    end = program.index('\ndef bootstrap_django():', start)
    helper_program = (
        'import json, os, sys\n'
        + program[start:end]
        + '\nreport_safe_failure(RuntimeError("synthetic-password-marker"))\n'
    )
    process = subprocess.run(
        [sys.executable, '-'], input=helper_program, capture_output=True, text=True,
        env={'PATH': os.environ.get('PATH', '/usr/bin:/bin')}, check=False,
    )
    assert process.returncode == 0
    assert json.loads(process.stdout) == {'error_type': 'FixtureExecutionError', 'ok': False}
    assert 'synthetic-password-marker' not in process.stdout
    assert 'synthetic-password-marker' not in process.stderr


def test_only_fixed_fixture_phases_can_be_rendered(tmp_path):
    bundle = fixtures.create_bundle(tmp_path / 'fixtures.json')
    for phase in ('seed', 'attach-owner', 'deactivate-admin', 'audit', 'login-rate-count', 'registration-rate-counts'):
        assert '_FIXTURE_PHASE' in fixtures.render_app_program(bundle, phase)
    with pytest.raises(ValueError, match='unsupported'):
        fixtures.render_app_program(bundle, 'execute-provider')
