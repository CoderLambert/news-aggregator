from datetime import datetime, timezone
from pathlib import Path
import sys


CRAWLER_ROOT = Path(__file__).resolve().parents[2] / 'crawler'
if str(CRAWLER_ROOT) not in sys.path:
    sys.path.insert(0, str(CRAWLER_ROOT))

from news_crawler.spiders.venturebeat_ai_spider import parse_venturebeat_publish_time


def test_venturebeat_rfc822_date_preserves_original_publication_time():
    parsed = parse_venturebeat_publish_time('Thu, 27 Aug 2026 14:01:00 +0000')

    assert parsed == datetime(2026, 8, 27, 14, 1, tzinfo=timezone.utc)


def test_venturebeat_gmt_date_preserves_original_publication_time():
    parsed = parse_venturebeat_publish_time('Thu, 27 Aug 2026 14:01:00 GMT')

    assert parsed == datetime(2026, 8, 27, 14, 1, tzinfo=timezone.utc)


def test_venturebeat_invalid_date_uses_explicit_fallback():
    fallback = datetime(2026, 10, 13, 1, 2, tzinfo=timezone.utc)

    assert parse_venturebeat_publish_time('not-a-date', fallback=fallback) == fallback
