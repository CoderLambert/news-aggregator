# Scrapy-backed Full Content API Implementation Plan

**Goal:** Build a well-encapsulated real-article fetch pipeline that can use Jina first, then a Scrapy/HTTP-backed HTML extractor, persist only verified real article Markdown, and support future batch backfill plus per-site extraction rules.

**Architecture:** Add `api.services.article_fetcher` as the single orchestration layer. Providers return `FetchResult` objects with provider name, markdown, title, canonical URL, quality score, and error. Existing manual fetch and future batch commands call the same service so behavior stays consistent. No generated summaries or validation content may ever be persisted as `News.full_content`.

**Tech Stack:** Django REST Framework, Scrapy-compatible HTTP settings, urllib/BeautifulSoup extraction initially, pluggable site extractor registry, pytest/Django tests.

---

## Tasks

1. Create failing tests for provider chain behavior, validation failures, and `NewsFetchFullView` persistence semantics.
2. Implement `api.services.article_fetcher` package:
   - dataclasses: `FetchResult`, `ProviderError`
   - `fetch_article_markdown(url, expected_title=None, prefer_jina=True)`
   - provider chain: Jina provider → Scrapy/HTTP provider
   - extractor registry: domain-specific extractor first, generic article/main/body extractor second
   - validators: minimum length, title similarity, summary-not-full guard
3. Wire `NewsFetchFullView` and `ensure_full_content()` to use the new service.
4. Add `fetch_full_content` management command for batch backfill with `--limit`, `--source`, `--dry-run`, `--force`, and truthful failure reporting.
5. Run backend tests and Django check; restart 9527 and verify one real endpoint.
6. Update skill docs with new architecture and batch command.
