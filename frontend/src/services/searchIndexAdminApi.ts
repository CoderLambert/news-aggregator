import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { fetchCsrfToken } from '@/services/api'
import { isRecord } from '@/types/news'
import type {
  SearchIndexAudit,
  SearchIndexDashboard,
  SearchIndexRun,
  SearchIndexRunMode,
  SearchIndexRunStatus,
  SearchIndexSettings,
} from '@/types/searchIndexAdmin'

const client = axios.create({ baseURL: '/api/admin/search-index', timeout: 20_000, withCredentials: true })

function attachCsrf(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  if (!['post', 'put', 'patch', 'delete'].includes(config.method?.toLowerCase() ?? '')) return config
  const match = typeof document === 'undefined' ? null : document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  if (match) config.headers.set('X-CSRFToken', decodeURIComponent(match[1]))
  return config
}
client.interceptors.request.use(attachCsrf)

const text = (value: unknown, fallback = '') => typeof value === 'string' ? value : fallback
const number = (value: unknown, fallback = 0) => typeof value === 'number' && Number.isFinite(value) ? value : fallback
const nullableText = (value: unknown) => typeof value === 'string' ? value : null

function parseSettings(value: unknown): SearchIndexSettings {
  if (!isRecord(value)) throw new TypeError('Invalid search index settings response')
  return {
    enabled: value.enabled === true,
    intervalSeconds: number(value.interval_seconds, 300),
    batchSize: number(value.batch_size, 100),
    activeCollection: text(value.active_collection),
    modelName: text(value.model_name),
    schemaVersion: text(value.schema_version),
    nextRunAt: nullableText(value.next_run_at),
    workerHeartbeatAt: nullableText(value.worker_heartbeat_at),
    workerInstanceId: text(value.worker_instance_id),
    workerOnline: value.worker_online === true,
    lastSuccessAt: nullableText(value.last_success_at),
    updatedAt: text(value.updated_at),
  }
}

function parseAudit(value: unknown): SearchIndexAudit {
  if (!isRecord(value)) throw new TypeError('Invalid search index audit response')
  return {
    available: value.available === true,
    newsCount: number(value.news_count),
    vectorCount: number(value.vector_count),
    missingCount: number(value.missing_count),
    changedCount: number(value.changed_count),
    orphanedCount: number(value.orphaned_count),
    errorCode: text(value.error_code),
  }
}

function parseRun(value: unknown): SearchIndexRun {
  if (!isRecord(value)) throw new TypeError('Invalid search index run response')
  return {
    id: text(value.id),
    trigger: text(value.trigger, 'manual') as SearchIndexRun['trigger'],
    mode: text(value.mode, 'sync') as SearchIndexRunMode,
    status: text(value.status, 'failed') as SearchIndexRunStatus,
    crawlBatch: nullableText(value.crawl_batch),
    collectionName: text(value.collection_name),
    modelName: text(value.model_name),
    schemaVersion: text(value.schema_version),
    newsCount: number(value.news_count),
    vectorCountBefore: number(value.vector_count_before),
    vectorCountAfter: number(value.vector_count_after),
    missingCount: number(value.missing_count),
    changedCount: number(value.changed_count),
    orphanedCount: number(value.orphaned_count),
    upsertedCount: number(value.upserted_count),
    deletedCount: number(value.deleted_count),
    failedCount: number(value.failed_count),
    safeErrorCode: text(value.safe_error_code),
    safeErrorMessage: text(value.safe_error_message),
    queuedAt: text(value.queued_at),
    startedAt: nullableText(value.started_at),
    heartbeatAt: nullableText(value.heartbeat_at),
    finishedAt: nullableText(value.finished_at),
    cancelRequestedAt: nullableText(value.cancel_requested_at),
    durationSeconds: typeof value.duration_seconds === 'number' ? value.duration_seconds : null,
  }
}

function parseDashboard(value: unknown): SearchIndexDashboard {
  if (!isRecord(value) || !Array.isArray(value.recent_runs)) {
    throw new TypeError('Invalid search index dashboard response')
  }
  return {
    settings: parseSettings(value.settings),
    audit: parseAudit(value.audit),
    activeRun: value.active_run ? parseRun(value.active_run) : null,
    recentRuns: value.recent_runs.map(parseRun),
    serverTime: text(value.server_time),
  }
}

export class SearchIndexAdminApiError extends Error {
  status: number | null
  constructor(message: string, status: number | null) {
    super(message)
    this.name = 'SearchIndexAdminApiError'
    this.status = status
  }
}

function normalizeError(error: unknown): never {
  const axiosError = error as AxiosError<unknown>
  const data = isRecord(axiosError.response?.data) ? axiosError.response.data : null
  const message = data && typeof data.message === 'string'
    ? data.message
    : error instanceof Error ? error.message : '索引管理请求失败。'
  throw new SearchIndexAdminApiError(message, axiosError.response?.status ?? null)
}

export async function fetchSearchIndexDashboard(signal?: AbortSignal): Promise<SearchIndexDashboard> {
  try {
    const { data } = await client.get<unknown>('/dashboard/', { signal })
    return parseDashboard(data)
  } catch (error) {
    normalizeError(error)
  }
}

export async function updateSearchIndexSettings(payload: {
  enabled?: boolean
  interval_seconds?: number
  batch_size?: number
}): Promise<SearchIndexSettings> {
  try {
    await fetchCsrfToken()
    const { data } = await client.patch<unknown>('/settings/', payload)
    return parseSettings(data)
  } catch (error) {
    normalizeError(error)
  }
}

export async function createSearchIndexRun(mode: SearchIndexRunMode): Promise<SearchIndexRun> {
  try {
    await fetchCsrfToken()
    const { data } = await client.post<unknown>('/runs/', { mode })
    return parseRun(data)
  } catch (error) {
    normalizeError(error)
  }
}

export async function cancelSearchIndexRun(runId: string): Promise<SearchIndexRun> {
  try {
    await fetchCsrfToken()
    const { data } = await client.post<unknown>(`/runs/${encodeURIComponent(runId)}/cancel/`)
    return parseRun(data)
  } catch (error) {
    normalizeError(error)
  }
}
