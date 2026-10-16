"""Executed inside the actual image after its synthetic ORM migrations."""
import importlib.abc
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import sys

absent = ('torch', 'sentence_transformers', 'chromadb', 'scrapy', 'feedparser',
          'playwright', 'selenium', 'trafilatura', 'newspaper', 'readability')
assert all(importlib.util.find_spec(name) is None for name in absent)
assert all(shutil.which(name) is None for name in ('chromium', 'google-chrome', 'firefox'))
attempted = []
blocked = absent + ('api.services.embedding', 'api.urls', 'newsaggregator.urls')


class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
            attempted.append(fullname)
            raise ImportError('forbidden RSS runtime import')


sys.meta_path.insert(0, Guard())
os.environ['RUN_MAIN'] = ''
os.environ['NEWS_CRAWL_ONLY'] = '0'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
import django
django.setup()
from api.rss.runtime import probe
from django.db import connection
from django.db.migrations.loader import MigrationLoader
status = probe()
assert not attempted and status['sync_ready'] is False
assert os.getuid() == 10001
assert not os.path.exists('/run/secrets/rss_engine_admin_password')
assert not os.path.exists('/run/secrets/rss_pg_password')
print(json.dumps({'status': status, 'python': platform.python_version(),
    'uid': os.getuid(), 'absent_modules': list(absent),
    'schema': MigrationLoader(connection).graph.leaf_nodes(),
    'packages': {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}
}, sort_keys=True))
