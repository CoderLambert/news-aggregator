"""Stored article availability and metadata helpers; never start publisher work."""
from __future__ import annotations

from django.db.models import F, Q, TextField, Value, Func, BooleanField, Case, When
from django.db.models.functions import Coalesce
from django.utils.timezone import now as tz_now
from api.models import News

def trimmed_text_expression(field_name: str):
    """Return a database expression matching Python's common whitespace trim."""
    whitespace = ' \t\n\r\v\f\x1c\x1d\x1e\x1f\x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000'
    return Coalesce(Func(F(field_name), Value(whitespace), function='TRIM', output_field=TextField()),
                    Value(''), output_field=TextField())

def annotate_full_content_availability(queryset):
    return queryset.alias(_readable_body=trimmed_text_expression('full_content')).annotate(
        has_readable_body=Case(When(Q(full_content_state__in=('legacy', 'complete')) & Q(_readable_body__gt=''),
                                   then=Value(True)), default=Value(False), output_field=BooleanField()))

def save_suggested_questions(news, questions, *, expected_revision):
    return news.__class__.objects.filter(pk=news.pk, url=news.url, full_content_revision=expected_revision).update(
        suggested_questions=questions, suggested_questions_generated_at=tz_now(),
    ) == 1

def has_full_content(news: News, *, privileged=False) -> bool:
    """Availability is independent of the latest refresh attempt's status."""
    if hasattr(news, '_rss_access_user'):
        from api.rss.access import body_authorized_news
        return body_authorized_news(news._rss_access_user, News.objects.filter(pk=news.pk)).exists()
    from api.services.channel_articles import summary_only
    return news.full_content_state in {'legacy', 'complete'} and bool((news.full_content or '').strip()) and (privileged or not summary_only(news))

def get_readable_full_content(news: News, *, privileged=False) -> str:
    return news.full_content if has_full_content(news, privileged=privileged) else ''

def filter_readable_full_content(queryset, *, privileged=False):
    from api.services.channel_articles import exclude_summary_only
    return (queryset if privileged else exclude_summary_only(queryset)).alias(
        _readable_body=trimmed_text_expression('full_content'),
    ).filter(full_content_state__in=['legacy', 'complete']).exclude(_readable_body='')
