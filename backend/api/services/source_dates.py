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




def parse_feed_datetime(value, policy):
    """Returns (UTC time, inferred clock); never infer all publishers' timezones."""
    parsed = parse_source_datetime(value)
    if parsed is not None:
        return parsed, False
    if not isinstance(value, str):
        return None, False
    if policy.date_format and policy.date_timezone:
        from zoneinfo import ZoneInfo
        try:
            parsed = datetime.strptime(value.strip(), policy.date_format)
            return parsed.replace(tzinfo=ZoneInfo(policy.date_timezone)).astimezone(timezone.utc), True
        except (ValueError, OverflowError):
            return None, False
    # A calendar date has known publication day but no authoritative clock.
    if len(value.strip()) == 10:
        try:
            parsed = datetime.strptime(value.strip(), '%Y-%m-%d')
            return parsed.replace(tzinfo=timezone.utc), True
        except ValueError:
            pass
    return None, False
