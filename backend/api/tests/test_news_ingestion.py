from dataclasses import replace
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from api.models import Category, News, NewsSourceItem, Source
from api.services.article_fetcher.types import FullContentCandidate, FetchResult
from api.services.article_fetcher.validators import validate_candidate
from api.services.article_identity import InvalidIdentity, normalize_article_url
from api.services.full_content_status import (
    claim_fetch, commit_candidate, correct_article_identity, enqueue_fetch,
    has_full_content, mark_failed, mark_success, release_fetch_claim, save_suggested_questions,
)
from api.services.news_ingestion import ingest_item


@pytest.fixture
def news(db):
    return News.objects.create(
        title='A real short publisher article', content='Independent summary',
        url='https://dev.to/team/short-article', publish_time=timezone.now(),
        source=Source.objects.update_or_create(name='Dev.to', defaults={'url': 'https://dev.to'})[0],
        category=Category.objects.create(name='ingestion', slug='ingestion'),
        content_kind='article',
    )


def candidate(news, body='A complete short article.', **changes):
    values = dict(
        source_key='devto', source_item_id='17', target_url=news.url,
        retrieved_from_url='https://dev.to/api/articles/17', declared_canonical_url=None,
        title=news.title, content_kind='article', body_field='body_markdown',
        content_format='markdown', declared_completeness='full', raw_content=body,
        source_modified_at=None, source_version=None, request_started_at=timezone.now(),
    )
    values.update(changes)
    return FullContentCandidate(**values)


def test_reactivating_identical_audit_body_clears_questions_made_from_summary(news):
    news.full_content = 'A complete short article.'
    news.full_content_state = 'missing'
    news.full_content_zh = 'Retained historical translation'
    news.suggested_questions = ['summary one', 'summary two', 'summary three']
    news.save(update_fields=['full_content', 'full_content_state', 'full_content_zh', 'suggested_questions'])
    assert commit_candidate(news, candidate(news)).saved
    news.refresh_from_db()
    assert has_full_content(news) and news.suggested_questions == []
    assert news.full_content_zh == 'Retained historical translation'


def entry(body=None, **changes):
    values = dict(
        source_key='devto', upstream_id='17', title='A real short publisher article',
        url='https://dev.to/team/short-article', source_name='Dev.to',
        category_name='ingestion', summary='Independent summary', content='Legacy preview',
        publish_time=timezone.now(), content_kind='article',
    )
    if body:
        values['body_candidate'] = body
    values.update(changes)
    return values


@pytest.mark.django_db
def test_structured_short_body_is_saved_once_and_preview_is_independent(news):
    with override_settings(STRUCTURED_BODY_INGEST_ENABLED=True, STRUCTURED_BODY_SOURCE_KEYS={'devto'}):
        first = ingest_item(entry(candidate(news)))
        news.refresh_from_db()
        accepted = news.full_content_fetched_at
        revision = news.full_content_revision
        replay = ingest_item(entry(candidate(news)))
    news.refresh_from_db()
    assert first.body_committed
    assert replay.receipt_outcome == 'committed' and not replay.body_committed
    assert news.full_content == 'A complete short article.'
    assert news.content == 'Independent summary'
    assert news.full_content_state == 'complete'
    assert news.full_content_revision == revision == 1
    assert news.full_content_fetched_at == accepted
    assert NewsSourceItem.objects.count() == 1


@pytest.mark.django_db
def test_two_sources_preserve_primary_source_and_discovery(news):
    first = ingest_item(entry())
    second = ingest_item(entry(source_key='hackernews', source_name='Hacker News', upstream_id='999',
                               discovery_url='https://news.ycombinator.com/item?id=999', title='HN editorial title'))
    assert first.news_id == second.news_id == news.pk
    news.refresh_from_db()
    assert news.source.name == 'Dev.to'
    assert news.title == 'A real short publisher article'
    assert news.source_items.count() == 2


@pytest.mark.django_db
def test_secondary_hn_url_change_never_replaces_publisher_identity(news):
    ingest_item(entry())
    discovered = ingest_item(entry(source_key='hackernews', source_name='Hacker News',
                                   upstream_id='999', title='Editorial link',
                                   discovery_url='https://news.ycombinator.com/item?id=999'))
    assert discovered.news_id == news.pk
    before_url = news.url
    before_revision = news.full_content_revision
    new_target = 'https://elsewhere.example/an-unrelated-article'
    conflict = ingest_item(entry(source_key='hackernews', source_name='Hacker News',
                                 upstream_id='999', url=new_target, title='Edited headline',
                                 discovery_url='https://news.ycombinator.com/item?id=999'))
    assert conflict.receipt_outcome == 'policy_skip'
    assert conflict.reason == 'identity_conflict'
    news.refresh_from_db()
    assert news.url == before_url
    assert news.full_content_revision == before_revision
    assert NewsSourceItem.objects.get(source_key='hackernews', upstream_id='999').news_id == news.pk
    assert not News.objects.filter(url=new_target).exists()


@pytest.mark.django_db
def test_primary_hn_external_link_change_does_not_rewrite_known_article():
    first = ingest_item(entry(source_key='hackernews', source_name='Hacker News',
                              upstream_id='999', title='HN shared link'))
    assert first.receipt_outcome == 'committed'
    result = ingest_item(entry(source_key='hackernews', source_name='Hacker News',
                               upstream_id='999', title='Changed external link',
                               url='https://other.example/replacement'))
    assert result.receipt_outcome == 'policy_skip'
    assert result.reason == 'identity_conflict'
    article = News.objects.get(pk=first.news_id)
    assert article.url == 'https://dev.to/team/short-article'
    assert News.objects.count() == 1


@pytest.mark.parametrize('changes,reason', [
    ({'target_url': 'https://dev.to/team/other'}, 'body_mismatch'),
    ({'retrieved_from_url': 'https://dev.to/api/articles/18'}, 'unsupported'),
    ({'body_field': 'description'}, 'unsupported'),
    ({'body_field': 'media:content'}, 'unsupported'),
    ({'declared_completeness': 'partial'}, 'body_partial'),
    ({'raw_content': 'Sign in to read the full article. ' * 100}, 'body_partial'),
    ({'raw_content': 'A long prefix. ' * 100 + 'Continue reading the rest on the website.'}, 'body_partial'),
    ({'raw_content': 'Checking your browser, verify you are human. ' * 100}, 'body_partial'),
    ({'raw_content': ''}, 'body_empty'),
])
@pytest.mark.django_db
def test_invalid_or_long_incomplete_candidates_do_not_become_complete(news, changes, reason):
    body = candidate(news, **changes)
    validation = validate_candidate(body, expected_url=news.url, expected_title=news.title)
    assert not validation.ok and validation.error_code == reason
    assert not commit_candidate(news, body).saved
    news.refresh_from_db()
    assert not has_full_content(news)


@pytest.mark.django_db
def test_bad_candidate_and_disabled_body_still_persist_metadata(news):
    with override_settings(STRUCTURED_BODY_INGEST_ENABLED=True, STRUCTURED_BODY_SOURCE_KEYS={'devto'}):
        result = ingest_item(entry(candidate(news, declared_completeness='partial')))
    assert result.receipt_outcome == 'committed' and result.reason == 'body_partial'
    with override_settings(STRUCTURED_BODY_INGEST_ENABLED=False):
        result = ingest_item(entry(candidate(news)))
    assert result.receipt_outcome == 'committed' and result.reason == 'structured_body_disabled'
    assert NewsSourceItem.objects.count() == 1
    news.refresh_from_db()
    assert news.full_content == ''


@pytest.mark.django_db
def test_feed_newer_shorter_body_fences_worker_and_clears_only_current_derivatives(news):
    old = timezone.now() - timedelta(days=2)
    assert commit_candidate(news, candidate(news, 'Long original body. ' * 20, source_modified_at=old)).saved
    News.objects.filter(pk=news.pk).update(full_content_zh='旧译文', suggested_questions=['Old question'])
    news.refresh_from_db()
    assert enqueue_fetch(news, force=True) == 'queued'
    worker = News.objects.get(pk=news.pk)
    assert claim_fetch(worker)
    assert commit_candidate(news, candidate(news, 'Short revised body.', source_modified_at=old + timedelta(days=1))).saved
    assert not mark_failed(worker, RuntimeError('late network failure'))
    result = FetchResult(ok=True, provider='devto', markdown='Late body', candidate=candidate(worker, 'Late body'))
    assert not mark_success(worker, result)
    news.refresh_from_db()
    assert news.full_content == 'Short revised body.'
    assert news.full_content_revision == 2
    assert news.full_content_fetch_status == 'success'
    assert news.full_content_next_attempt_at is None
    assert news.full_content_retry_count == 0
    assert news.full_content_zh == '' and news.suggested_questions == []


@pytest.mark.django_db
def test_feed_same_body_new_version_preserves_translation_and_fences_old_lease(news):
    old = timezone.now() - timedelta(days=2)
    assert commit_candidate(news, candidate(news, source_modified_at=old)).saved
    News.objects.filter(pk=news.pk).update(full_content_zh='有效译文')
    news.refresh_from_db()
    enqueue_fetch(news, force=True)
    worker = News.objects.get(pk=news.pk)
    assert claim_fetch(worker)
    assert commit_candidate(news, candidate(news, source_modified_at=old + timedelta(days=1))).changed
    assert not release_fetch_claim(worker)
    news.refresh_from_db()
    assert news.full_content_revision == 2
    assert news.full_content_zh == '有效译文'
    assert news.full_content_fetch_status == 'success'


@pytest.mark.django_db
def test_old_same_version_and_unordered_conflicting_bodies_never_replace(news):
    modified = timezone.now()
    assert commit_candidate(news, candidate(news, source_modified_at=modified, source_version='opaque-z')).saved
    for body in (
        candidate(news, 'Older body', source_modified_at=modified - timedelta(days=1)),
        candidate(news, 'Conflicting body', source_modified_at=modified),
        candidate(news, 'Opaque is not an order', source_version='opaque-zz'),
        candidate(news, source_modified_at=modified - timedelta(days=1)),
    ):
        assert commit_candidate(news, body).reason == 'source_version_conflict'
    news.refresh_from_db()
    assert news.full_content_revision == 1
    assert news.full_content_provenance['source_version'] == 'opaque-z'


@pytest.mark.django_db
def test_same_feed_body_noop_preserves_refresh_and_worker_noop_finishes_it(news):
    body = candidate(news)
    assert commit_candidate(news, body).saved
    fetched_at = news.full_content_fetched_at
    enqueue_fetch(news, force=True)
    assert claim_fetch(news)
    assert commit_candidate(news, replace(body, request_started_at=timezone.now())).outcome == 'noop'
    news.refresh_from_db()
    assert news.full_content_fetch_status == 'fetching'
    result = FetchResult(ok=True, provider='devto', markdown=body.raw_content, candidate=body)
    assert mark_success(news, result)
    assert news.full_content_fetch_status == 'success'
    assert news.full_content_next_attempt_at is None
    assert news.full_content_revision == 1
    assert news.full_content_fetched_at == fetched_at


@pytest.mark.django_db
def test_url_correction_fences_success_failure_and_slow_questions(news):
    body = candidate(news)
    assert commit_candidate(news, body).saved
    enqueue_fetch(news, force=True)
    assert claim_fetch(news)
    previous_revision = news.full_content_revision
    current = News.objects.get(pk=news.pk)
    assert correct_article_identity(current, 'https://dev.to/team/corrected', expected_url=current.url,
                                    expected_revision=current.full_content_revision)
    assert not mark_success(news, FetchResult(ok=True, provider='devto', markdown=body.raw_content, candidate=body))
    assert not mark_failed(news, RuntimeError('late failure'))
    assert not save_suggested_questions(news, ['Old question'], expected_revision=previous_revision)
    current.refresh_from_db()
    assert current.full_content == body.raw_content  # preserved for audit
    assert current.full_content_state == 'missing' and not has_full_content(current)
    assert commit_candidate(current, candidate(current)).saved
    assert has_full_content(current)


@pytest.mark.django_db
def test_unclaimed_results_and_old_candidate_revision_cannot_write(news):
    body = candidate(news)
    assert not mark_success(news, FetchResult(ok=True, provider='devto', markdown=body.raw_content, candidate=body))
    assert not mark_failed(news, RuntimeError('unclaimed'))
    assert commit_candidate(news, body).saved
    assert commit_candidate(news, replace(body, expected_revision=0)).reason == 'persistence_conflict'


@pytest.mark.django_db
def test_html_fragment_preserves_code_images_lists_and_tables(news):
    html = '<p>A real short body.</p><pre><code>if x &lt; 2:\n    print(x)</code></pre><ul><li>One</li></ul>' \
           '<img src="/image.png" alt="Diagram"><img src="/pixel.gif" width="1" height="1">' \
           '<table><tr><th>Name</th></tr><tr><td>Value</td></tr></table><script>secret()</script>'
    body = candidate(news, html, body_field='body_html', content_format='html')
    result = validate_candidate(body, expected_url=news.url, expected_title=news.title)
    assert result.ok
    assert 'if x < 2:' in result.markdown and '```' in result.markdown
    assert '- One' in result.markdown and '| Value |' in result.markdown
    assert '![Diagram](https://dev.to/image.png)' in result.markdown
    assert 'pixel.gif' not in result.markdown and 'secret' not in result.markdown


def test_url_normalization_preserves_business_identity():
    assert normalize_article_url('HTTPS://DEV.TO:443/Path%2FCase?x=%2f&utm_source=test&x=Two#part') == 'https://dev.to/Path%2FCase?x=%2f&x=Two'
    assert normalize_article_url('http://dev.to/A/') != normalize_article_url('https://dev.to/A')
    with pytest.raises(InvalidIdentity):
        normalize_article_url('https://dev.to/' + 'a' * 500)


@pytest.mark.django_db
def test_upstream_id_target_change_keeps_news_id_and_replay_is_idempotent(news):
    first = ingest_item(entry())
    corrected = ingest_item(entry(url='https://dev.to/team/corrected'))
    replay = ingest_item(entry(url='https://dev.to/team/corrected'))
    assert first.news_id == corrected.news_id == replay.news_id == news.pk
    news.refresh_from_db()
    assert news.url == 'https://dev.to/team/corrected'
    assert news.full_content_revision == 1
    assert News.objects.count() == 1 and NewsSourceItem.objects.count() == 1


@pytest.mark.django_db
def test_invalid_title_never_corrects_url_or_advances_source_identity(news):
    ingest_item(entry())
    before = NewsSourceItem.objects.get(source_key='devto', upstream_id='17')
    original_revision, original_url = news.full_content_revision, news.url
    for malformed in ('', ' ', 'a' * 501, None, 123):
        rejected = ingest_item(entry(url='https://dev.to/team/changed-target', title=malformed))
        assert rejected.receipt_outcome == 'policy_skip'
        assert rejected.reason == 'invalid_identity'
        assert rejected.news_id is None
        news.refresh_from_db()
        before.refresh_from_db()
        assert news.url == original_url
        assert news.full_content_revision == original_revision
        assert before.discovery_url == original_url
    assert News.objects.count() == 1
    assert NewsSourceItem.objects.count() == 1


@pytest.mark.django_db
def test_primary_publisher_recategorization_updates_list_filter_without_duplicating_article(news):
    first = ingest_item(entry())
    original_url, revision = news.url, news.full_content_revision
    changed = ingest_item(entry(category_name='New verified category'))
    replay = ingest_item(entry(category_name='New verified category'))
    news.refresh_from_db()
    assert first.news_id == changed.news_id == replay.news_id == news.pk
    assert news.category.name == 'New verified category'
    assert changed.changed is True
    assert replay.changed is False
    assert news.url == original_url and news.full_content_revision == revision
    assert News.objects.count() == 1 and news.source_items.count() == 1


@pytest.mark.django_db
def test_secondary_discovery_cannot_relabel_primary_publisher_category(news):
    ingest_item(entry())
    ingestion = ingest_item(entry(source_key='hackernews', source_name='Hacker News', upstream_id='999',
                                  category_name='Community discussion', title='Community headline'))
    assert ingestion.receipt_outcome == 'committed'
    news.refresh_from_db()
    assert news.category.name == 'ingestion'
    assert NewsSourceItem.objects.get(source_key='hackernews', upstream_id='999').metadata['category_name'] == 'Community discussion'


@pytest.mark.django_db
def test_source_id_conflict_cannot_relabel_a_known_article(news):
    ingest_item(entry())
    wrong = candidate(news, source_item_id='18', retrieved_from_url='https://dev.to/api/articles/18')
    assert commit_candidate(news, wrong).reason == 'body_mismatch'
    assert news.full_content == ''


@pytest.mark.django_db
def test_feed_canonical_includes_path_and_allows_reviewed_host_alias(news):
    body = candidate(
        news, '<p>The complete short publisher post.</p>',
        source_key='smashing_magazine', source_item_id='publisher-guid',
        target_url='https://www.smashingmagazine.com/2026/10/short-post/',
        retrieved_from_url='https://www.smashingmagazine.com/feed/',
        body_field='content:encoded', content_format='html',
        declared_canonical_url='https://smashingmagazine.com/2026/10/short-post/',
    )
    assert validate_candidate(body, expected_url=body.target_url, expected_title=news.title).ok
    wrong = replace(body, declared_canonical_url='https://www.smashingmagazine.com/2026/10/another-post/')
    assert validate_candidate(wrong, expected_url=body.target_url, expected_title=news.title).error_code == 'body_mismatch'


@pytest.mark.django_db
def test_refresh_failure_retains_current_readable_body_translation_and_evidence(news):
    assert commit_candidate(news, candidate(news)).saved
    News.objects.filter(pk=news.pk).update(full_content_zh='可读译文')
    news.refresh_from_db()
    revision = news.full_content_revision
    provenance = news.full_content_provenance
    enqueue_fetch(news, force=True)
    assert claim_fetch(news)
    assert mark_failed(news, RuntimeError('connection reset'), status='network_error')
    assert has_full_content(news)
    assert news.full_content_zh == '可读译文'
    assert news.full_content_revision == revision and news.full_content_provenance == provenance
    assert news.full_content_next_attempt_at is not None


@pytest.mark.django_db
def test_overlong_identity_and_search_urls_are_rejected_without_truncating(news):
    for changes in ({'upstream_id': 'a' * 1025}, {'url': 'https://dev.to/search?query=title'},
                    {'source_key': 'unknown_key'}, {'url': 'https://another.example/article'}):
        result = ingest_item(entry(**changes))
        assert result.receipt_outcome == 'policy_skip' and result.news_id is None
    assert NewsSourceItem.objects.count() == 0


@pytest.mark.parametrize('changes', [
    {'source_item_id': 17}, {'request_started_at': 'yesterday'},
    {'source_modified_at': 'today'}, {'source_version': 42},
    {'expected_revision': -1}, {'source_key': {'trusted': True}},
])
@pytest.mark.django_db
def test_typed_candidate_still_validates_runtime_field_types(news, changes):
    assert validate_candidate(candidate(news, **changes), expected_url=news.url).error_code == 'invalid_identity'


@pytest.mark.django_db
def test_hn_editorial_headline_does_not_veto_exact_publisher_identity():
    discovered = ingest_item(entry(source_key='hackernews', source_name='Hacker News', upstream_id='999',
                                    discovery_url='https://news.ycombinator.com/item?id=999',
                                    title='An editorial HN headline'))
    news = News.objects.get(pk=discovered.news_id)
    publisher = candidate(news, title='The exact publisher headline')
    with override_settings(STRUCTURED_BODY_INGEST_ENABLED=True, STRUCTURED_BODY_SOURCE_KEYS={'devto'}):
        result = ingest_item(entry(publisher, title=publisher.title))
    assert result.body_committed
    news.refresh_from_db()
    assert has_full_content(news) and news.source.name == 'Hacker News'
    assert news.title == 'An editorial HN headline'
    assert news.source_items.count() == 2


@pytest.mark.django_db
def test_approved_short_body_equal_to_excerpt_is_still_complete(news):
    body = candidate(news, 'A real short post.')
    assert commit_candidate(news, body, summary=body.raw_content).saved


@pytest.mark.django_db
def test_fragment_keeps_semantic_header_and_subscription_demo(news):
    body = candidate(news, '<header><h2>Introduction</h2><p>The actual opening argument.</p></header>'
                     '<div class="subscribe"><p>A subscription programming example.</p></div>',
                     body_field='body_html', content_format='html')
    result = validate_candidate(body, expected_url=news.url)
    assert result.ok and '## Introduction' in result.markdown
    assert 'actual opening argument' in result.markdown and 'subscription programming example' in result.markdown


@pytest.mark.django_db
def test_same_upstream_version_cannot_be_overridden_by_new_modified_timestamp(news):
    instant = timezone.now()
    assert commit_candidate(news, candidate(news, source_version='v1', source_modified_at=instant)).saved
    result = commit_candidate(news, candidate(news, 'Conflicting new body', source_version='v1', source_modified_at=instant + timedelta(days=1)))
    assert result.reason == 'source_version_conflict'
    assert news.full_content == 'A complete short article.'


@pytest.mark.django_db
def test_dev_repost_canonical_is_attribution_and_never_changes_target(news):
    canonical = 'https://webkit.org/blog/17/original/'
    assert commit_candidate(news, candidate(news, declared_canonical_url=canonical)).saved
    assert news.url == 'https://dev.to/team/short-article'
    assert news.full_content_provenance['declared_canonical_url'] == canonical
    assert validate_candidate(candidate(news, declared_canonical_url='javascript:bad()'), expected_url=news.url).error_code == 'body_mismatch'


@pytest.mark.django_db
def test_equivalent_timezone_representation_is_not_a_new_body_revision(news):
    from datetime import timezone as utc_timezone
    instant = timezone.now()
    assert commit_candidate(news, candidate(news, source_modified_at=instant)).saved
    version = news.full_content_revision
    assert commit_candidate(news, candidate(news, source_modified_at=instant.astimezone(utc_timezone(timedelta(hours=8))))).outcome == 'noop'
    assert news.full_content_revision == version


@pytest.mark.django_db
def test_unicode_whitespace_availability_matches_sql(news):
    from api.services.full_content_status import filter_readable_full_content
    for body in ('\xa0', '\u3000\u2009\u202f', '\x85\x1c', 'Readable\u3000'):
        News.objects.filter(pk=news.pk).update(full_content_state='legacy', full_content=body)
        news.refresh_from_db()
        assert has_full_content(news) == filter_readable_full_content(News.objects.filter(pk=news.pk)).exists() == bool(body.strip())


@pytest.mark.django_db
def test_subscription_code_example_does_not_look_like_a_paywall(news):
    markdown = 'A subscription programming tutorial.\n\n```js\nconsole.log("subscribe to continue reading");\n```'
    result = validate_candidate(candidate(news, markdown), expected_url=news.url)
    assert result.ok and 'console.log' in result.markdown
