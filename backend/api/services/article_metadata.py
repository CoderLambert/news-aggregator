"""Prefer a reviewed publisher over a discovery pointer, never arbitrary peers."""
from urllib.parse import urlsplit
from api.services.source_policy import policy_for_name


def can_promote_publisher(news, incoming_policy, target_url, content_kind):
    old = policy_for_name(news.source.name)
    if (old is None or old.key != 'hackernews' or incoming_policy.key == 'hackernews'
            or incoming_policy.unsupported_reason or content_kind != 'article'
            or target_url != news.url):
        return False
    host = (urlsplit(target_url).hostname or '').lower()
    if host in old.domains or host not in incoming_policy.domains:
        return False
    # Require the original discoverer's persisted identity; don't promote a
    # manually relabelled record based only on its display name.
    return news.source_items.filter(source_key='hackernews').exists()
