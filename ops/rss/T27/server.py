"""Synthetic full app server: mock only paid-provider boundary, keep real ACL/HTTP."""
import json
import os
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
assert '/newshub-rss-t27-' in os.environ['DJANGO_DB_PATH']
import django
django.setup()
from django.core.management import call_command
from api import views

def fake_chat(messages, **kwargs):
    with open(Path(os.environ['T27_STATE_DIR']) / 'ai-contexts.jsonl', 'a') as handle:
        handle.write(json.dumps({'messages': messages}, ensure_ascii=False) + '\n')
    yield 'Synthetic assistant: this answer uses only the authorized stored article.'
views.get_clients = lambda: [object()]
views.stream_chat = fake_chat
# No real personal credentials are seeded or inherited. Explicit TTS calls must
# never reach Microsoft's network during this browser fixture.
import edge_tts
class NoPaidOrExternalSpeech:
    def __init__(self, *args, **kwargs):
        raise RuntimeError('T27 synthetic: speech provider intentionally disabled')
edge_tts.Communicate = NoPaidOrExternalSpeech
call_command('runserver', os.environ['T27_APP_ADDRESS'], use_reloader=False, skip_checks=True)
