import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { fetchCsrfToken } from '@/services/api'
import type {
  ArticleFetchDashboard,
  ArticleFetchDomainStats,
  ArticleFetchEvent,
  ArticleFetchFailureCode,
  ArticleFetchProviderStats,
  JinaFallbackPolicy,
} from '@/types/articleFetchAdmin'
import { isRecord } from '@/types/news'

const client = axios.create({ baseURL: '/api/admin/article-fetch', timeout: 15_000, withCredentials: true })

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

function parseFailureCodes(value: unknown): ArticleFetchFailureCode[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((entry) => isRecord(entry) && typeof entry.provider === 'string' && typeof entry.code === 'string'
    ? [{ provider: entry.provider, code: entry.code }]
    : [])
}

function parsePolicy(value: unknown): JinaFallbackPolicy {
  if (!isRecord(value)) throw new TypeError('Invalid Jina fallback policy response')
  return {
    domain: text(value.domain),
    enabled: value.enabled === true,
    autoDiscovered: value.auto_discovered === true,
    failureCount: number(value.failure_count),
    lastFailureCodes: parseFailureCodes(value.last_failure_codes),
    lastSeenAt: nullableText(value.last_seen_at),
    updatedAt: text(value.updated_at),
  }
}

function parseEvent(value: unknown): ArticleFetchEvent {
  if (!isRecord(value)) throw new TypeError('Invalid article fetch event response')
  return {
    id: number(value.id),
    newsId: typeof value.news_id === 'number' ? value.news_id : null,
    domain: text(value.domain),
    outcome: value.outcome === 'success' ? 'success' : 'failed',
    provider: text(value.provider),
    failureCodes: parseFailureCodes(value.failure_codes),
    qualityScore: typeof value.quality_score === 'number' ? value.quality_score : null,
    contentLength: number(value.content_length),
    elapsedMs: number(value.elapsed_ms),
    createdAt: text(value.created_at),
  }
}

function parseDomain(value: unknown): ArticleFetchDomainStats {
  if (!isRecord(value)) throw new TypeError('Invalid article fetch domain response')
  return {
    domain: text(value.domain),
    total: number(value.total),
    failed: number(value.failed),
    succeeded: number(value.succeeded),
  }
}

function parseProvider(value: unknown): ArticleFetchProviderStats {
  if (!isRecord(value)) throw new TypeError('Invalid article fetch provider response')
  return {
    provider: text(value.provider),
    outcome: value.outcome === 'success' ? 'success' : 'failed',
    count: number(value.count),
  }
}

function parseDashboard(value: unknown): ArticleFetchDashboard {
  if (!isRecord(value) || !isRecord(value.summary)) {
    throw new TypeError('Invalid article fetch dashboard response')
  }
  const summary = value.summary
  return {
    windowDays: number(value.window_days, 7),
    retentionDays: number(value.retention_days, 30),
    summary: {
      total: number(summary.total),
      success: number(summary.success),
      failed: number(summary.failed),
      successRate: number(summary.success_rate),
      unresolvedArticles: number(summary.unresolved_articles),
    },
    domains: Array.isArray(value.domains) ? value.domains.map(parseDomain) : [],
    providers: Array.isArray(value.providers) ? value.providers.map(parseProvider) : [],
    topFailureCodes: Array.isArray(value.top_failure_codes)
      ? value.top_failure_codes.flatMap((entry) => isRecord(entry) && typeof entry.code === 'string'
        ? [{ code: entry.code, count: number(entry.count) }]
        : [])
      : [],
    policies: Array.isArray(value.policies) ? value.policies.map(parsePolicy) : [],
    recentEvents: Array.isArray(value.recent_events) ? value.recent_events.map(parseEvent) : [],
    serverTime: text(value.server_time),
  }
}

function normalizeError(error: unknown): never {
  const axiosError = error as AxiosError<unknown>
  const data = isRecord(axiosError.response?.data) ? axiosError.response?.data : null
  const message = data && typeof data.message === 'string'
    ? data.message
    : error instanceof Error ? error.message : '全文抓取监控请求失败。'
  throw new Error(message)
}

export async function fetchArticleFetchDashboard(signal?: AbortSignal): Promise<ArticleFetchDashboard> {
  try {
    const { data } = await client.get<unknown>('/dashboard/?days=7', { signal })
    return parseDashboard(data)
  } catch (error) {
    normalizeError(error)
  }
}

export async function createJinaPolicy(domain: string): Promise<JinaFallbackPolicy> {
  try {
    await fetchCsrfToken()
    const { data } = await client.post<unknown>('/policies/', { domain, enabled: false })
    return parsePolicy(data)
  } catch (error) {
    normalizeError(error)
  }
}

export async function updateJinaPolicy(domain: string, enabled: boolean): Promise<JinaFallbackPolicy> {
  try {
    await fetchCsrfToken()
    const { data } = await client.patch<unknown>(`/policies/${encodeURIComponent(domain)}/`, { enabled })
    return parsePolicy(data)
  } catch (error) {
    normalizeError(error)
  }
}
