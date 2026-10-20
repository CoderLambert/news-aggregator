"""Exercise the real control-worker completion boundary with a synthetic engine."""
from dataclasses import replace

from api.rss.control_worker import ControlWorker
from api.rss.engine import EngineConfig, FeedDTO, PolicyReceipt
from api.rss.models import FeedBinding


def connect_pending():
    binding = FeedBinding.objects.first()
    if binding is None:
        return
    instance, account = str(binding.engine_instance_uuid), binding.account_id

    class Engine:
        def __init__(self):
            self.feeds = {b.engine_feed_id: FeedDTO(instance, account, b.engine_feed_id,
                b.canonical_feed_url, 'Fixture', b.desired_mode == 'full_content', not b.desired_enabled)
                for b in FeedBinding.objects.filter(engine_feed_id__isnull=False)}

        def close(self):
            pass

        def create_feed(self, url, *, desired_mode, disabled, published_since=None):
            feed = FeedDTO(instance, account, max(self.feeds, default=0) + 1,
                url, 'Fixture', desired_mode == 'full_content', disabled)
            self.feeds[feed.id] = feed
            return feed

        def update_feed_policy(self, policy, expected_policy_version):
            feed = replace(self.feeds[policy.engine_feed_id], disabled=not policy.desired_enabled,
                crawler=policy.desired_mode == 'full_content')
            self.feeds[feed.id] = feed
            return PolicyReceipt(feed, expected_policy_version)

    engine = Engine()
    worker = ControlWorker(EngineConfig(instance, account, 'http://127.0.0.1:1', 'synthetic'),
        adapter_factory=lambda: engine)
    try:
        for _ in range(100):
            if not worker.run_once():
                return
        raise AssertionError('Synthetic registrations did not converge')
    finally:
        worker.close()
