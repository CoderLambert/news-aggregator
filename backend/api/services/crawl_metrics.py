"""Sanitized ingestion results, separate from process exits and HTTP responses."""
RESULT_PREFIX = 'NEWSHUB_CRAWL_RESULT '
SUCCESS_OUTCOMES = frozenset({'updated', 'unchanged', 'valid_empty'})
OUTCOMES = SUCCESS_OUTCOMES | {'deferred', 'rate_limited', 'blocked', 'parse_failed', 'partial', 'unsupported'}
COUNT_KEYS = ('entries_seen', 'entries_committed', 'entries_changed', 'body_candidates_committed',
              'parse_failures', 'persistence_failures', 'physical_requests', 'budget_deferred')


def crawl_result(stats):
    http = {}
    for key, value in stats.items():
        if key.startswith(('downloader/response_status_count/', 'budget/http_status_count/')):
            code = str(key.rsplit('/', 1)[-1])
            http[code] = max(http.get(code, 0), max(0, int(value)))
    result = {key: max(0, int(stats.get(key, 0))) for key in COUNT_KEYS}
    result.update(finish_reason=str(stats.get('finish_reason', 'unknown'))[:64],
                  items=max(0, int(stats.get('item_scraped_count', 0))),
                  responses=max(sum(http.values()), int(stats.get('downloader/response_count', 0))),
                  errors=max(0, int(stats.get('log_count/ERROR', 0))), http_statuses=http,
                  checkpoint_committed=stats.get('checkpoint_committed') is True,
                  policy_skips_by_reason=stats.get('policy_skips_by_reason', {}),
                  next_attempt_at=stats.get('next_attempt_at'))
    result['entries_changed'] += max(0, int(stats.get('discovery/entries_changed', 0)))
    result['physical_requests'] = max(result['physical_requests'], int(stats.get('budget/physical_requests', 0)))
    result['budget_deferred'] = max(result['budget_deferred'], int(stats.get('budget/deferred', 0)))
    outcome = stats.get('outcome')
    if outcome in SUCCESS_OUTCOMES:
        outcome = ('partial' if result['persistence_failures'] or result['finish_reason'] != 'finished' else
                   'parse_failed' if result['parse_failures'] else
                   'blocked' if any(http.get(code, 0) for code in ('401', '403')) else
                   'rate_limited' if http.get('429', 0) else
                   'deferred' if result['budget_deferred'] else outcome)
    if outcome not in OUTCOMES:
        outcome = ('partial' if result['persistence_failures'] or result['finish_reason'] != 'finished' else
                   'parse_failed' if result['parse_failures'] else
                   'blocked' if any(http.get(code, 0) for code in ('401', '403')) else
                   'rate_limited' if http.get('429', 0) else
                   'deferred' if result['budget_deferred'] else
                   'partial' if result['errors'] else
                   'updated' if result['entries_changed'] else
                   'unchanged' if result['entries_committed'] or result['entries_seen'] else
                   'partial' if result['items'] else
                   'valid_empty' if result['responses'] else 'deferred')
    result['outcome'] = outcome
    return result


def count_ingest(stats, result):
    stats.inc_value('entries_seen')
    if result.receipt_outcome == 'committed':
        stats.inc_value('entries_committed')
        stats.inc_value('entries_changed', count=int(result.changed))
        stats.inc_value('body_candidates_committed', count=int(result.body_committed))
    elif result.receipt_outcome == 'policy_skip':
        skips = dict(stats.get_value('policy_skips_by_reason', {}))
        skips[result.reason] = skips.get(result.reason, 0) + 1
        stats.set_value('policy_skips_by_reason', skips)
    else:
        stats.inc_value('persistence_failures')


def parse_failure(spider):
    crawler = getattr(spider, 'crawler', None)
    if crawler is not None:
        crawler.stats.inc_value('parse_failures')
