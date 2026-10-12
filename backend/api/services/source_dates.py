"""Timezone-preserving source timestamp parsing without network or ORM."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def parse_source_datetime(value, *, assume_utc=False):
    if isinstance(value, datetime):
        parsed = value
    elif not isinstance(value, str) or not value.strip():
        return None
    else:
        try:
            parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value.strip())
            except (TypeError, ValueError, OverflowError):
                return None
    if parsed.tzinfo is None:
        if not assume_utc:
            return None
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

