# A01 Sources Audit

Baseline: 15a3c2c6ad90da25ee5cbc537a21778d22b04bd3

57 policies; 51 registered, 6 quarantined.

## Scope and evidence
Base SHA: 15a3c2c6ad90da25ee5cbc537a21778d22b04bd3. This audit is code-only, without production DB, external publisher calls, tests, deployment changes, or runtime configuration changes. It references Issue #52 and docs/plans/2026-10-13-news-ingestion-design-codex.md. The 31 core SourcePolicy records and 26 sector feeds yield 57 policies; the crawl registry retains 51 and excludes six quarantined sources: leiphone, meta_ai, reuters, jiqizhixin, sanliu_kr and fda_news. Registered status is not evidence of a running scheduler or successful ingestion.

来源审核：待验证。
