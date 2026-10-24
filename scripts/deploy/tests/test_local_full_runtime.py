from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_local_full_overlay_enables_every_operator_health_dependency():
    overlay = yaml.safe_load((ROOT / 'compose.local-full.yaml').read_text())
    services = overlay['services']

    assert set(services) == {
        'app', 'indexer', 'channel-worker', 'translation-redis', 'rss-db', 'miniflux',
        'rss-sync', 'ai-gateway-db', 'ai-gateway',
    }
    app = services['app']
    assert app['environment'] == {
        'AI_BYOK_ENABLED': '1',
        'AI_BYOK_GATEWAY_URL': 'http://127.0.0.1:4000',
        'AI_BYOK_GATEWAY_PROJECT_KEY_FILE': '/run/secrets/ai_byok_gateway_project_key',
        'CHANNEL_WORKER_HEARTBEAT': '/app/logs/channel-worker-heartbeat.json',
        'RSS_ENGINE_INSTANCE_UUID': '${RSS_ENGINE_INSTANCE_UUID:?set by local-full-runtime.sh}',
        'RSS_ENGINE_ACCOUNT_ID': '${RSS_ENGINE_ACCOUNT_ID:?set by local-full-runtime.sh}',
        'TRANSLATION_REDIS_URL': '${TRANSLATION_REDIS_URL:?set by local-full-runtime.sh}',
    }
    assert app['secrets'] == ['ai_byok_gateway_project_key']
    assert services['indexer']['image'] == '${NEWSHUB_IMAGE:?set an exact local image}'


def test_local_full_overlay_keeps_internal_services_private_and_pinned():
    services = yaml.safe_load((ROOT / 'compose.local-full.yaml').read_text())['services']

    assert services['channel-worker']['network_mode'] == 'service:app'
    assert services['ai-gateway']['network_mode'] == 'service:app'
    assert 'ports' not in services['ai-gateway']
    assert 'ports' not in services['translation-redis']
    assert 'ports' not in services['rss-db']
    assert services['miniflux']['ports'] == ['127.0.0.1:${RSS_ENGINE_PORT:-18080}:8080']
    for service in ('translation-redis', 'rss-db', 'miniflux', 'ai-gateway-db', 'ai-gateway'):
        assert '@sha256:' in services[service]['image']
    assert services['rss-db']['networks'] == ['rss-db-net']
    assert services['ai-gateway-db']['networks'] == ['ai-gateway-db-net']
    assert services['ai-gateway']['depends_on']['ai-gateway-db']['condition'] == 'service_healthy'


def test_local_full_overlay_mounts_only_required_secrets_and_persistent_state():
    overlay = yaml.safe_load((ROOT / 'compose.local-full.yaml').read_text())
    services = overlay['services']

    assert services['translation-redis']['secrets'] == ['translation_redis_password']
    assert services['rss-sync']['secrets'] == ['rss_engine_token']
    assert services['ai-gateway']['secrets'] == [
        'ai_gateway_postgres_password', 'litellm_master_key', 'litellm_salt_key',
    ]
    assert set(overlay['volumes']) == {
        'rss-pg-data', 'rss-runtime-data', 'ai-gateway-postgres-data',
    }
    assert overlay['networks']['rss-db-net']['internal'] is True
    assert overlay['networks']['ai-gateway-db-net']['internal'] is True
    assert set(overlay['secrets']) == {
        'translation_redis_password', 'rss_pg_password', 'rss_database_url',
        'rss_engine_admin_password', 'rss_engine_token',
        'ai_gateway_postgres_password', 'litellm_master_key', 'litellm_salt_key',
        'ai_byok_gateway_project_key',
    }
