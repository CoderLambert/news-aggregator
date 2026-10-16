import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { isRecord } from '@/types/news'
import type {
  CrawlBatch,
  CrawlerDashboard,
  CrawlerSettings,
  CrawlerTarget,
  CrawlRun,
  CrawlRunStatus,
  CrawlBatchStatus,
  SourceConfigInput,
  SourceConfigRecord,
  SourceEndpointConfig,
} from '@/types/crawlerAdmin'
import { fetchCsrfToken } from '@/services/api'

const client = axios.create({ baseURL: '/api/admin/crawler', timeout: 15_000, withCredentials: true })

function attachCsrf(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  if (!['post', 'put', 'patch', 'delete'].includes(config.method?.toLowerCase() ?? '')) return config
  const match = typeof document === 'undefined' ? null : document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  if (match) config.headers.set('X-CSRFToken', decodeURIComponent(match[1]))
  return config
}

client.interceptors.request.use(attachCsrf)

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function number(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function nullableText(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function boolean(value: unknown, fallback = false): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function parseEndpoint(value: unknown): SourceEndpointConfig {
  if (!isRecord(value)) throw new TypeError('Invalid source endpoint response')
  const parserConfig = isRecord(value.parser_config) ? value.parser_config : {}
  return {
    id: typeof value.id === 'number' ? value.id : undefined,
    kind: text(value.kind, 'rss') as SourceEndpointConfig['kind'],
    url: text(value.url),
    allowedDomains: Array.isArray(value.allowed_domains) ? value.allowed_domains.filter((item): item is string => typeof item === 'string') : [],
    priority: number(value.priority, 100),
    parserConfig,
    conditionalRequests: boolean(value.conditional_requests, true),
    requestIntervalSeconds: number(value.request_interval_seconds, 10),
    maxResponseBytes: number(value.max_response_bytes, 2 * 1024 * 1024),
    maxPages: number(value.max_pages, 1),
    maxItems: number(value.max_items, 50),
    enabled: boolean(value.enabled, true),
  }
}

function parseSourceConfig(value: unknown): SourceConfigRecord {
  if (!isRecord(value) || typeof value.source_key !== 'string') throw new TypeError('Invalid source configuration response')
  const monitoring = isRecord(value.monitoring) ? value.monitoring : {}
  const latestArticle = isRecord(monitoring.latest_article) ? monitoring.latest_article : null
  const lastHttpStatuses: Record<string, number> = {}
  if (isRecord(monitoring.last_http_statuses)) {
    for (const [code, count] of Object.entries(monitoring.last_http_statuses)) {
      if (typeof count === 'number') lastHttpStatuses[code] = count
    }
  }
  return {
    sourceKey: value.source_key,
    sourceId: typeof value.source_id === 'number' ? value.source_id : null,
    publisherName: text(value.publisher_name),
    channelName: text(value.channel_name),
    category: typeof value.category === 'number' ? value.category : null,
    categoryName: text(value.category_name),
    region: value.region === 'international' ? 'international' : 'domestic',
    language: text(value.language, 'zh'),
    contentKind: text(value.content_kind, 'article'),
    readingPolicy: text(value.reading_policy, 'summary_only'),
    status: text(value.status, 'draft') as SourceConfigRecord['status'],
    configVersion: number(value.config_version, 1),
    summaryAllowed: boolean(value.summary_allowed, true),
    feedFullContentAllowed: boolean(value.feed_full_content_allowed),
    officialHtmlFullContentAllowed: boolean(value.official_html_full_content_allowed),
    probeSummary: isRecord(value.probe_summary) ? value.probe_summary : {},
    probedAt: nullableText(value.probed_at),
    approvedAt: nullableText(value.approved_at),
    unavailableReason: text(value.unavailable_reason),
    maintenance: value.maintenance === 'database' ? 'database' : 'code',
    probeIsCurrent: boolean(value.probe_is_current),
    approvalIsCurrent: boolean(value.approval_is_current),
    canEnable: boolean(value.can_enable),
    readOnly: boolean(value.read_only),
    endpoints: Array.isArray(value.endpoints) ? value.endpoints.map(parseEndpoint) : [],
    monitoring: {
      workerHeartbeatAt: nullableText(monitoring.worker_heartbeat_at),
      lastProbeAt: nullableText(monitoring.last_probe_at),
      lastProbeStatus: text(monitoring.last_probe_status),
      configVersion: typeof monitoring.config_version === 'number' ? monitoring.config_version : null,
      approvedAt: nullableText(monitoring.approved_at),
      lastSuccessAt: nullableText(monitoring.last_success_at),
      lastFeedSuccessAt: nullableText(monitoring.last_feed_success_at),
      nextPollAt: nullableText(monitoring.next_poll_at),
      cooldownUntil: nullableText(monitoring.cooldown_until),
      lastTargetFinishedAt: nullableText(monitoring.last_target_finished_at),
      lastFailure: text(monitoring.last_failure),
      lastHttpStatuses,
      latestArticle: latestArticle ? {
        id: number(latestArticle.id), title: text(latestArticle.title), url: text(latestArticle.url),
        publishTime: text(latestArticle.publish_time),
      } : null,
    },
  }
}

function parseRun(value: unknown): CrawlRun {
  if (!isRecord(value)) throw new TypeError('Invalid crawl run response')
  const stats = isRecord(value.stats) ? value.stats : {}
  const httpStatuses: Record<string, number> = {}
  if (isRecord(value.http_statuses)) {
    for (const [code, count] of Object.entries(value.http_statuses)) {
      if (typeof count === 'number') httpStatuses[code] = count
    }
  }
  return {
    id: text(value.id),
    batchId: text(value.batch),
    spiderName: text(value.spider_name),
    targetName: text(value.target_name),
    sourceActive: typeof value.source_active === 'boolean' ? value.source_active : undefined,
    status: text(value.status, 'failed') as CrawlRunStatus,
    queuedAt: text(value.queued_at),
    startedAt: nullableText(value.started_at),
    heartbeatAt: nullableText(value.heartbeat_at),
    finishedAt: nullableText(value.finished_at),
    durationSeconds: typeof value.duration_seconds === 'number' ? value.duration_seconds : null,
    exitCode: typeof value.exit_code === 'number' ? value.exit_code : null,
    items: number(value.items),
    responses: number(value.responses),
    errors: number(value.errors),
    httpStatuses,
    finishReason: text(stats.finish_reason),
    safeError: text(value.safe_error),
    outcome: text(stats.outcome),
    entriesCommitted: number(stats.entries_committed),
    entriesChanged: number(stats.entries_changed),
    warnings: Array.isArray(stats.warnings) ? stats.warnings.filter((value): value is string => typeof value === 'string') : [],
    retryOf: nullableText(value.retry_of),
    latestRetryId: nullableText(value.latest_retry_id),
    latestRetryStatus: nullableText(value.latest_retry_status) as CrawlRunStatus | null,
    latestRetryDisplayStatus: nullableText(value.latest_retry_display_status),
    cancelRequestedAt: nullableText(value.cancel_requested_at),
  }
}

function parseTarget(value: unknown): CrawlerTarget {
  if (!isRecord(value)) throw new TypeError('Invalid crawler target response')
  return {
    spiderName: text(value.spider_name),
    displayName: text(value.display_name),
    enabled: value.enabled === true,
    supported: typeof value.supported === 'boolean' ? value.supported : undefined,
    unsupportedReason: text(value.unsupported_reason),
    sortOrder: number(value.sort_order),
    lastStatus: text(value.last_status),
    lastResultStatus: text(value.last_result_status),
    lastStartedAt: nullableText(value.last_started_at),
    lastFinishedAt: nullableText(value.last_finished_at),
    lastItems: number(value.last_items),
    lastResponses: number(value.last_responses),
    lastErrors: number(value.last_errors),
    lastSafeError: text(value.last_safe_error),
    activeRun: value.active_run ? parseRun(value.active_run) : null,
  }
}

function parseBatch(value: unknown): CrawlBatch {
  if (!isRecord(value)) throw new TypeError('Invalid crawl batch response')
  return {
    id: text(value.id),
    trigger: text(value.trigger, 'manual') as CrawlBatch['trigger'],
    status: text(value.status, 'failed') as CrawlBatchStatus,
    queuedAt: text(value.queued_at),
    startedAt: nullableText(value.started_at),
    finishedAt: nullableText(value.finished_at),
    total: number(value.total),
    succeeded: number(value.succeeded),
    failed: number(value.failed),
    cancelled: number(value.cancelled),
    runs: Array.isArray(value.runs) ? value.runs.map(parseRun) : [],
  }
}

function parseSettings(value: unknown): CrawlerSettings {
  if (!isRecord(value)) throw new TypeError('Invalid crawler settings response')
  return {
    schedulerEnabled: value.scheduler_enabled === true,
    intervalSeconds: number(value.interval_seconds, 3600),
    runOnWorkerStart: value.run_on_worker_start === true,
    nextRunAt: nullableText(value.next_run_at),
    workerHeartbeatAt: nullableText(value.worker_heartbeat_at),
    workerInstanceId: text(value.worker_instance_id),
    workerOnline: value.worker_online === true,
    updatedAt: text(value.updated_at),
  }
}

function parseDashboard(value: unknown): CrawlerDashboard {
  if (!isRecord(value) || !Array.isArray(value.targets) || !Array.isArray(value.recent_batches)) {
    throw new TypeError('Invalid crawler dashboard response')
  }
  return {
    settings: parseSettings(value.settings),
    activeRun: value.active_run ? parseRun(value.active_run) : null,
    targets: value.targets.map(parseTarget),
    recentBatches: value.recent_batches.map(parseBatch),
    serverTime: text(value.server_time),
  }
}

export type CrawlerReadinessState =
  | 'unsupported' | 'not_registered' | 'disabled' | 'worker_offline' | 'scheduler_paused'
  | 'running' | 'degraded' | 'waiting_poll' | 'idle' | 'no_history'

export interface CrawlerReadinessSource {
  sourceKey: string
  displayName: string
  registered: boolean
  supported: boolean
  enabled: boolean
  state: CrawlerReadinessState
  action: string
  lastResult: string
  lastFinishedAt: string | null
  lastFeedSuccessAt: string | null
  nextPollAt: string | null
}
export interface CrawlerReadinessSnapshot {
  schedulerConfigured: boolean
  schedulerEnabled: boolean
  crawlerWorkerOnline: boolean
  indexWorkerOnline: boolean
  sources: CrawlerReadinessSource[]
}

export function parseCrawlerReadiness(value: unknown): CrawlerReadinessSnapshot {
  if (!isRecord(value) || !isRecord(value.scheduler) || !isRecord(value.workers) ||
    !isRecord(value.workers.crawler) || !isRecord(value.workers.search_index) ||
    !Array.isArray(value.sources)) throw new TypeError('Invalid crawler readiness response')
  const stateNames = new Set([
    'unsupported', 'not_registered', 'disabled', 'worker_offline', 'scheduler_paused',
    'running', 'degraded', 'waiting_poll', 'idle', 'no_history',
  ])
  return {
    schedulerConfigured: value.scheduler.configured === true,
    schedulerEnabled: value.scheduler.enabled === true,
    crawlerWorkerOnline: value.workers.crawler.online === true,
    indexWorkerOnline: value.workers.search_index.online === true,
    sources: value.sources.flatMap((item) => {
      if (!isRecord(item) || typeof item.source_key !== 'string' ||
        typeof item.display_name !== 'string' || typeof item.state !== 'string' ||
        !stateNames.has(item.state)) return []
      return [{
        sourceKey: item.source_key,
        displayName: item.display_name,
        registered: item.registered === true,
        supported: item.supported === true,
        enabled: item.enabled === true,
        state: item.state as CrawlerReadinessState,
        action: text(item.suggested_action),
        lastResult: text(item.last_result),
        lastFinishedAt: nullableText(item.last_finished_at),
        lastFeedSuccessAt: nullableText(item.last_feed_success_at),
        nextPollAt: nullableText(item.next_poll_at),
      }]
    }),
  }
}

export async function fetchCrawlerReadiness(signal?: AbortSignal): Promise<CrawlerReadinessSnapshot> {
  try {
    const { data } = await client.get<unknown>('/readiness/', { signal })
    return parseCrawlerReadiness(data)
  } catch (error) {
    normalizeError(error)
  }
}

export class CrawlerAdminApiError extends Error {
  status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.name = 'CrawlerAdminApiError'
    this.status = status
  }
}

function normalizeError(error: unknown): never {
  const axiosError = error as AxiosError<unknown>
  const data = isRecord(axiosError.response?.data) ? axiosError.response?.data : null
  const message = data && typeof data.message === 'string'
    ? data.message
    : error instanceof Error ? error.message : '爬虫管理请求失败。'
  throw new CrawlerAdminApiError(message, axiosError.response?.status ?? null)
}

export async function fetchCrawlerDashboard(signal?: AbortSignal): Promise<CrawlerDashboard> {
  try {
    const { data } = await client.get<unknown>('/dashboard/', { signal, params: { include_history: 0 } })
    return parseDashboard(data)
  } catch (error) {
    normalizeError(error)
  }
}

export async function updateCrawlerSettings(payload: {
  scheduler_enabled?: boolean
  interval_seconds?: number
  run_on_worker_start?: boolean
}): Promise<CrawlerSettings> {
  try {
    await fetchCsrfToken()
    const { data } = await client.patch<unknown>('/settings/', payload)
    return parseSettings(data)
  } catch (error) {
    normalizeError(error)
  }
}

export async function updateCrawlerTarget(spiderName: string, enabled: boolean): Promise<CrawlerTarget> {
  try {
    await fetchCsrfToken()
    const { data } = await client.patch<unknown>(`/targets/${encodeURIComponent(spiderName)}/`, { enabled })
    return parseTarget(data)
  } catch (error) {
    normalizeError(error)
  }
}

export async function createCrawlBatch(spiderNames?: string[]): Promise<void> {
  try {
    await fetchCsrfToken()
    await client.post('/batches/', spiderNames ? { spider_names: spiderNames } : {})
  } catch (error) {
    normalizeError(error)
  }
}

export async function cancelCrawlRun(runId: string): Promise<CrawlRun> {
  try {
    await fetchCsrfToken()
    const { data } = await client.post<unknown>(`/runs/${encodeURIComponent(runId)}/cancel/`)
    return parseRun(data)
  } catch (error) {
    normalizeError(error)
  }
}

export async function retryCrawlRun(runId: string): Promise<void> {
  try {
    await fetchCsrfToken()
    await client.post(`/runs/${encodeURIComponent(runId)}/retry/`)
  } catch (error) {
    normalizeError(error)
  }
}

export async function fetchSourceConfigs(signal?: AbortSignal): Promise<SourceConfigRecord[]> {
  try {
    const { data } = await client.get<unknown>('/sources/', { signal })
    if (!Array.isArray(data)) throw new TypeError('Invalid source configuration list')
    return data.map(parseSourceConfig)
  } catch (error) {
    normalizeError(error)
  }
}

export async function createSourceConfig(payload: SourceConfigInput): Promise<SourceConfigRecord> {
  try {
    await fetchCsrfToken()
    const { data } = await client.post<unknown>('/sources/', payload)
    return parseSourceConfig(data)
  } catch (error) {
    normalizeError(error)
  }
}

export async function updateSourceConfig(sourceKey: string, payload: Partial<SourceConfigInput>): Promise<SourceConfigRecord> {
  try {
    await fetchCsrfToken()
    const { data } = await client.patch<unknown>(`/sources/${encodeURIComponent(sourceKey)}/`, payload)
    return parseSourceConfig(data)
  } catch (error) {
    normalizeError(error)
  }
}

async function sourceAction(sourceKey: string, action: 'probe' | 'approve' | 'enable', payload: Record<string, unknown> = {}): Promise<SourceConfigRecord> {
  try {
    await fetchCsrfToken()
    const { data } = await client.post<unknown>(`/sources/${encodeURIComponent(sourceKey)}/${action}/`, payload)
    return parseSourceConfig(data)
  } catch (error) {
    normalizeError(error)
  }
}

export const probeSourceConfig = (sourceKey: string) => sourceAction(sourceKey, 'probe')
export const approveSourceConfig = (sourceKey: string) => sourceAction(sourceKey, 'approve')
export const setSourceConfigEnabled = (sourceKey: string, enabled: boolean) => sourceAction(sourceKey, 'enable', { enabled })

export async function runSourceConfig(sourceKey: string): Promise<void> {
  try {
    await fetchCsrfToken()
    await client.post(`/sources/${encodeURIComponent(sourceKey)}/run/`, {})
  } catch (error) {
    normalizeError(error)
  }
}

export async function deleteSourceConfig(sourceKey: string): Promise<void> {
  try {
    await fetchCsrfToken()
    await client.delete(`/sources/${encodeURIComponent(sourceKey)}/`)
  } catch (error) {
    normalizeError(error)
  }
}

export async function fetchRecentCrawlBatches(signal?: AbortSignal): Promise<CrawlBatch[]> {
  try {
    const { data } = await client.get<unknown>('/batches/', { signal, params: { page_size: 8, summary: 1 } })
    if (!isRecord(data) || !Array.isArray(data.results)) throw new TypeError('Invalid crawl history response')
    return data.results.map(parseBatch)
  } catch (error) {
    normalizeError(error)
  }
}
