"""
Django settings for test environment.
"""
import os
import sys

# Build paths inside the project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'backend'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')

# Use SQLite in-memory database for tests
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Disable debug mode for tests
DEBUG = False

# Use faster password hasher for tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

import django
from django.conf import settings

# Override settings for testing
settings.DATABASES = DATABASES
settings.DEBUG = DEBUG
settings.PASSWORD_HASHERS = PASSWORD_HASHERS
