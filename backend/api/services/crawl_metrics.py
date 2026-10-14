"""Sanitized ingestion results, separate from process exits and HTTP responses."""
RESULT_PREFIX = 'NEWSHUB_CRAWL_RESULT '
SUCCESS_OUTCOMES = frozenset({'updated', 'unchanged', 'valid_empty'})
# A scheduler pass that has not reached poll time is healthy, but it did not
# fetch or checkpoint the feed. Keep it distinct from actual ingest success.
NON_FAILURE_OUTCOMES = SUCCESS_OUTCOMES | {'not_due'}
OUTCOMES = NON_FAILURE_OUTCOMES | {'deferred', 'rate_limited', 'blocked', 'parse_failed', 'partial', 'unsupported',
                               'network_error', 'http_error', 'filtered'}
COUNT_KEYS = ('entries_seen', 'entries_committed', 'entries_changed', 'body_candidates_committed',
              'parse_failures', 'persistence_failures', 'physical_requests', 'budget_deferred', 'rate_limited_responses')


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
    result['rate_limited_responses'] = max(result['rate_limited_responses'], int(stats.get('budget/rate_limited', 0)))
    result['budget_deferred'] = max(result['budget_deferred'], int(stats.get('budget/deferred', 0)))
    classified = stats.get('request_classification_available') is True
    primary_http = {str(key.rsplit('/', 1)[-1]): max(0, int(value)) for key, value in stats.items()
                    if key.startswith('discovery/http_status_count/')}
    auxiliary_http = {str(key.rsplit('/', 1)[-1]): max(0, int(value)) for key, value in stats.items()
                      if key.startswith('auxiliary/http_status_count/')}
    failures = {reason: max(0, int(stats.get(f'discovery/failures/{reason}', 0)))
                for reason in ('timeout', 'transport_error')}
    auxiliary_failures = sum(max(0, int(stats.get(f'auxiliary/failures/{reason}', 0)))
                             for reason in failures)
    result.update(primary_http_statuses=primary_http, auxiliary_http_statuses=auxiliary_http,
                  network_failures=sum(failures.values()), auxiliary_failures=auxiliary_failures,
                  request_failures_by_reason=failures,
                  filtered_requests=max(0, int(stats.get('offsite/filtered', 0))))
    warnings = []
    if auxiliary_failures or any(count for code, count in auxiliary_http.items() if int(code) >= 400):
        warnings.append('robots_unavailable')
    result['warnings'] = warnings
    result['source_paused'] = stats.get('source_paused') is True
    result['robots_disallowed'] = stats.get('robots_disallowed') is True
    # Robots requests are diagnostics, not evidence that the article feed was
    # blocked. Retain the old conservative interpretation for unclassified logs.
    http = primary_http if classified else http
    remaining_errors = max(0, result['errors'] - auxiliary_failures) if classified else result['errors']
    outcome = stats.get('outcome')
    if outcome in SUCCESS_OUTCOMES:
        outcome = ('partial' if result['persistence_failures'] or result['finish_reason'] != 'finished' else
                   'parse_failed' if result['parse_failures'] else
                   'network_error' if result['network_failures'] else
                   'rate_limited' if result['rate_limited_responses'] else
                   'blocked' if any(http.get(code, 0) for code in ('401', '403')) else
                   'rate_limited' if http.get('429', 0) else
                   'http_error' if any(count for code, count in http.items() if int(code) >= 400) else
                   'deferred' if result['budget_deferred'] else outcome)
    if outcome not in OUTCOMES:
        outcome = ('partial' if result['persistence_failures'] or result['finish_reason'] != 'finished' else
                   'parse_failed' if result['parse_failures'] else
                   'network_error' if result['network_failures'] else
                   'rate_limited' if result['rate_limited_responses'] else
                   'blocked' if any(http.get(code, 0) for code in ('401', '403')) else
                   'rate_limited' if http.get('429', 0) else
                   'http_error' if any(count for code, count in http.items() if int(code) >= 400) else
                   'deferred' if result['budget_deferred'] else
                   'partial' if remaining_errors else
                   'updated' if result['entries_changed'] else
                   'unchanged' if result['entries_committed'] or result['entries_seen'] else
                   'partial' if result['items'] else
                   'valid_empty' if result['responses'] else 'deferred')
    if result['filtered_requests'] and not result['physical_requests']:
        outcome = 'filtered'
    if outcome == 'not_due' and result['finish_reason'] != 'finished':
        outcome = 'partial'
    result['failure_outcome'] = outcome if outcome not in NON_FAILURE_OUTCOMES else ''
    if result['entries_committed'] and outcome not in SUCCESS_OUTCOMES | {'rate_limited', 'deferred'}:
        outcome = 'partial'
    result['outcome'] = outcome
    return result


def describe_crawl_result(result):
    reason = result.get('failure_outcome') or result.get('outcome')
    messages = {
        'not_due': '尚未到计划轮询时间，未请求源站；不是采集失败。',
        'deferred': '正在等待源站或请求预算，暂未完成本轮采集。',
        'rate_limited': '源站限流，任务等待冷却后重试。',
        'blocked': '源站返回 401/403，当前渠道拒绝访问。',
        'parse_failed': '部分页面未能解析出有效文章。',
        'network_error': '源站连接或响应超时，请检查采集进程的网络出口。',
        'http_error': '源站返回错误 HTTP 状态，未获得有效内容。',
        'filtered': '请求被域名白名单过滤，尚未访问源站。',
        'partial': '本轮存在未完成的请求或条目。',
        'unsupported': '当前来源缺少受支持的采集渠道。',
    }
    message = messages.get(reason, '')
    if result.get('source_paused'):
        message = '该渠道已因源站拒绝访问暂停自动重试，需核查公开采集接口。'
    if result.get('robots_disallowed'):
        message = '源站 robots.txt 不允许访问当前入口，请使用官方允许的 Feed 或 API。'
    if result.get('entries_committed') and message:
        message = f"已有 {result['entries_committed']} 条成功入库；" + message
    primary = result.get('primary_http_statuses', {})
    bad_codes = sorted(code for code in primary if code.isdecimal() and int(code) >= 400)
    if bad_codes:
        message += ' HTTP ' + '/'.join(bad_codes) + '。'
    if 'robots_unavailable' in result.get('warnings', []):
        message += ' robots.txt 获取异常；已单独记录辅助请求告警。'
    return message[:500]


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
