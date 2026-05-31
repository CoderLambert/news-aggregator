"""
Django settings for test environment.
"""
import os
import sys

# Build paths inside the project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')

import django
django.setup()
