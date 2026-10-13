import type { CrawlBatch, CrawlRun } from '@/types/crawlerAdmin'

export function crawlRunDisplayStatus(run: CrawlRun): string {
  if (run.exitCode !== 0 || !['failed', 'succeeded'].includes(run.status)) return run.status
  if (run.status === 'failed' && (run.entriesCommitted ?? 0) > 0) return 'partial'
  const outcomes = ['deferred', 'rate_limited', 'blocked', 'network_error', 'http_error', 'filtered', 'parse_failed']
  return outcomes.includes(run.outcome ?? '') ? run.outcome! : run.status
}

export function crawlBatchDisplay(batch: CrawlBatch) {
  const counts = { succeeded: 0, partial: 0, failed: 0, deferred: 0, cancelled: 0 }
  for (const run of batch.runs) {
    const status = crawlRunDisplayStatus(run)
    if (status === 'succeeded') counts.succeeded++
    else if (status === 'partial') counts.partial++
    else if (['deferred', 'rate_limited'].includes(status)) counts.deferred++
    else if (status === 'cancelled') counts.cancelled++
    else if (!['queued', 'running', 'cancel_requested'].includes(status)) counts.failed++
  }
  let status: string = batch.status
  if (batch.runs.length && !['queued', 'running'].includes(status)) {
    if (counts.deferred === batch.runs.length) status = 'deferred'
    else if (counts.partial || counts.deferred || (counts.failed && counts.succeeded)) status = 'partial'
  }
  return { status, counts }
}

export function crawlRunReason(run: CrawlRun): string {
  if (!run.safeError.startsWith('来源结果：')) return run.safeError
  const reason = run.outcome || run.safeError.slice('来源结果：'.length)
  return ({
    partial: '本轮有请求或条目未完成；已入库内容保留。',
    deferred: '等待下一次允许执行的时间。',
    blocked: '源站拒绝部分请求；请核查渠道状态。',
    parse_failed: '部分响应未能解析为有效文章。',
    network_error: '源站连接或响应超时。',
    http_error: '源站返回错误 HTTP 状态。',
    filtered: '请求被域名白名单过滤。',
    rate_limited: '源站限流，等待冷却后重试。',
  } as Record<string, string>)[reason] || run.safeError
}
