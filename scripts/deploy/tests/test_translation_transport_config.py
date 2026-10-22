"""The optional replay service is private, authenticated and ephemeral."""
from pathlib import Path
import yaml


def test_translation_redis_has_no_public_port_or_persistent_article_storage():
    root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load((root / 'compose.translation.yaml').read_text())
    redis = config['services']['translation-redis']
    assert '@sha256:' in redis['image']
    assert all(port.startswith('127.0.0.1:') for port in redis['ports'])
    assert '--requirepass' in redis['command'][0]
    assert '--save "" --appendonly no' in redis['command'][0]
    assert '--maxmemory-policy noeviction' in redis['command'][0]
    assert redis['read_only'] and redis['cap_drop'] == ['ALL']
    assert not redis.get('volumes')
    assert redis['secrets'] == ['translation_redis_password']
