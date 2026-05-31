#!/usr/bin/env python3
"""Start Django with Waitress WSGI server for proper SSE support."""
import os
import sys

# Add the project to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')

# Ensure API key is available for LLM translation
if not os.environ.get('DASHSCOPE_CODING_API_KEY'):
    try:
        import yaml
        config_path = os.path.expanduser('~/.hermes/config.yaml')
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        api_key = config.get('model', {}).get('api_key', '')
        if api_key:
            os.environ['DASHSCOPE_CODING_API_KEY'] = api_key
            print(f"Loaded API key from config", flush=True)
    except Exception as e:
        print(f"Warning: Could not load API key from config: {e}", flush=True)

import django
django.setup()

from waitress import serve
from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

print(f"Starting Waitress on 0.0.0.0:9527...", flush=True)

serve(
    application,
    host='0.0.0.0',
    port=9527,
    threads=4,
    connection_limit=1000,
    channel_timeout=300,
)
