"""Keep repeated performance experiments out of ordinary PR feedback."""
from pathlib import Path
import unittest

import yaml


class PytestBenchmarkScopeTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[3]
        workflow = root / '.github/workflows/ci-pytest-benchmark.yml'
        self.workflow = yaml.load(workflow.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)

    def test_three_round_benchmark_is_explicitly_manual(self):
        self.assertEqual(set(self.workflow['on']), {'workflow_dispatch'})
        job = self.workflow['jobs']['pytest-xdist-lab']
        self.assertEqual(job['env']['CI_XDIST_REPEATS'], '3')
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})

    def test_benchmark_reuses_normal_isolated_redis_setup(self):
        job = self.workflow['jobs']['pytest-xdist-lab']
        self.assertEqual(job['env']['PYTHONPATH'], 'backend')
        runs = [step.get('run', '') for step in job['steps']]
        self.assertIn(
            'bash ops/ci/with-translation-redis.sh bash ops/ci/benchmark-xdist.sh',
            runs,
        )
