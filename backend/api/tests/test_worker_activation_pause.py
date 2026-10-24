import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace


def test_channel_worker_activation_pause_only_emits_heartbeat(monkeypatch):
    calls = []
    django = ModuleType('django')
    django_conf = ModuleType('django.conf')
    django_conf.settings = SimpleNamespace(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
    django_core = ModuleType('django.core')
    django_management = ModuleType('django.core.management')
    django_base = ModuleType('django.core.management.base')
    django_base.BaseCommand = type('BaseCommand', (), {})
    django_db = ModuleType('django.db')
    django_db.close_old_connections = lambda: None
    topics = ModuleType('api.services.channel_topics')
    topics.refresh_profiles = lambda: calls.append('refresh')
    ai = ModuleType('api.services.channel_ai')
    ai.claim_next = lambda: calls.append('claim')
    ai.execute_job = lambda _job: calls.append('execute')
    ai.enqueue_site_sources = lambda: calls.append('enqueue')
    ai.process_incremental_subscriptions = lambda: calls.append('subscriptions')
    for name, module in {
        'django': django, 'django.conf': django_conf, 'django.core': django_core,
        'django.core.management': django_management,
        'django.core.management.base': django_base, 'django.db': django_db,
        'api.services.channel_topics': topics, 'api.services.channel_ai': ai,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv('NEWSHUB_ACTIVATION_PAUSED', '1')
    path = Path(__file__).resolve().parents[1] / 'management/commands/channel_worker.py'
    spec = importlib.util.spec_from_file_location('isolated_channel_worker', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'heartbeat', lambda **kwargs: calls.append(kwargs))

    module.Command().handle(once=True, interval=2)

    assert calls and all(call == {'activation_paused': True} for call in calls)
