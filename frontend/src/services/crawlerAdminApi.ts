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
    retryOf: nullableText(value.retry_of),
    latestRetryId: nullableText(value.latest_retry_id),
    latestRetryStatus: nullableText(value.latest_retry_status) as CrawlRunStatus | null,
    cancelRequestedAt: nullableText(value.cancel_requested_at),
  }
}

function parseTarget(value: unknown): CrawlerTarget {
  if (!isRecord(value)) throw new TypeError('Invalid crawler target response')
  return {
    spiderName: text(value.spider_name),
    displayName: text(value.display_name),
    enabled: value.enabled === true,
    sortOrder: number(value.sort_order),
    lastStatus: text(value.last_status),
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
    const { data } = await client.get<unknown>('/dashboard/', { signal })
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
