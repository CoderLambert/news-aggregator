"""Lossless archival of old compatibility translations before source text changes."""

from hashlib import sha256

from django.db import connections

from api.models import LegacyTranslationSnapshot


TRANSLATED_FIELDS = {'title': 'title_zh', 'content': 'content_zh', 'full_content': 'full_content_zh'}


def exact_hash(value: str) -> str:
    return sha256(value.encode('utf-8')).hexdigest()


def archive_changed_translations(news, replacements: dict) -> dict:
    """Archive exact old strings and return compatibility fields to clear.

    Call with a freshly loaded News inside ``fenced_article(token)`` and include
    the returned fields in the SAME transaction's update. This does not change
    original text, clear fields itself, or invent provider/translation matches.
    Unchanged source strings and independent private/shared records are untouched.
    """
    alias = news._state.db or 'default'
    if not connections[alias].in_atomic_block:
        raise RuntimeError('translation_archive_requires_transaction')
    cleared = {}
    for field, translated_field in TRANSLATED_FIELDS.items():
        original = getattr(news, field)
        if field not in replacements or replacements[field] == original:
            continue
        translated = getattr(news, translated_field)
        if translated:
            LegacyTranslationSnapshot.objects.using(alias).get_or_create(
                news_id=news.pk, field=field, source_hash=exact_hash(original),
                translation_hash=exact_hash(translated),
                defaults={'source_text': original, 'translated_text': translated, 'origin': 'legacy'},
            )
        cleared[translated_field] = ''
        if field == 'full_content':
            cleared['full_content_zh_fetched_at'] = None
    return cleared
