"""Initialize the same Django configuration for manage.py and direct Scrapy CLI."""
import os
from pathlib import Path
import sys

import django
from django.apps import apps


def initialize_django():
    backend = str(Path(__file__).resolve().parents[2] / 'backend')
    if backend not in sys.path:
        sys.path.insert(0, backend)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
    if not apps.ready and not apps.loading:
        django.setup()
