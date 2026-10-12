"""Bounded fake-only concurrency matrix: isolated memory and file/WAL SQLite."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import PropertyMock, patch

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'backend/api/tests/test_subscription_submission_locks.py::test_first_creation_race_commits_one_task_and_dispatches_once'
parser = argparse.ArgumentParser()
parser.add_argument('--repetitions', type=int, default=5, choices=range(1, 11))
parser.add_argument('--output', type=Path)
parser.add_argument('--worker', choices=['memory', 'wal'])
parser.add_argument('--suite', choices=['submission', 'worker'], default='submission')
args = parser.parse_args()
if args.suite == 'worker':
    TARGET = 'backend/api/tests/test_subscription_worker_locks.py::test_sse_success_with_temporary_task_reader'
if args.worker:
    os.chdir(ROOT)
    sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
    os.environ.update({'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings', 'DJANGO_ENV': 'development',
        'RUN_MAIN': 'true', 'NEWS_CRAWL_ONLY': '1', 'PYTEST_CURRENT_TEST': 'isolated_submission_probe',
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
    with tempfile.TemporaryDirectory(prefix='subscription-submission-') as directory:
        os.environ['DJANGO_DB_PATH'] = str(Path(directory) / 'unused-runtime.sqlite3')
        os.environ['CHATGPT_DEPLOYMENT_INSTANCE_FILE'] = str(Path(directory) / 'deployment-id')
        with patch('api.services.embedding.EmbeddingService.preload', side_effect=AssertionError('preload forbidden')) as preload, \
             patch('api.services.embedding.EmbeddingService.model', new_callable=PropertyMock, side_effect=AssertionError('load forbidden')) as model, \
             patch('api.services.embedding.EmbeddingService.encode', side_effect=AssertionError('inference forbidden')) as encode:
            from django.conf import settings
            if args.worker == 'wal':
                settings.DATABASES['default'].setdefault('TEST', {})['NAME'] = str(Path(directory) / 'wal-test.sqlite3')
            import pytest
            class Probe:
                @pytest.hookimpl(hookwrapper=True)
                def pytest_runtest_call(self, item):
                    from django.db import connection
                    with connection.cursor() as cursor:
                        cursor.execute('PRAGMA journal_mode')
                        journal = cursor.fetchone()[0]
                    assert journal == args.worker, journal
                    outcome = yield
                    print('SQLITE_PROBE:', json.dumps({'database': args.worker, 'journal_mode': journal,
                        'test_passed': outcome.excinfo is None}))
            result = pytest.main([TARGET, '-q', '-s', '--tb=short', '-p', 'no:cacheprovider'], plugins=[Probe()])
            preload.assert_not_called()
            model.assert_not_called()
            encode.assert_not_called()
            print('MODEL_GUARDS: zero calls')
        sys.exit(result)
records = []
for mode in ('memory', 'wal'):
    for iteration in range(1, args.repetitions + 1):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', mode, '--suite', args.suite],
            cwd=ROOT, capture_output=True, text=True, timeout=40)
        print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, file=sys.stderr, end='')
        record = {'suite': args.suite, 'tests_per_run': 3 if args.suite == 'worker' else 1, 'database': mode, 'iteration': iteration, 'exit_code': result.returncode,
            'model_guards_zero': 'MODEL_GUARDS: zero calls' in result.stdout}
        records.append(record)
        if args.output:
            args.output.write_text(json.dumps(records, indent=2)+'\n')
assert all(record['exit_code'] == 0 and record['model_guards_zero'] for record in records), records
print(json.dumps(records, indent=2))
