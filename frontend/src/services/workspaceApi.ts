import { queryOptions } from '@tanstack/react-query'

export type GroupingMode = 'off' | 'suggest' | 'auto'
export interface Topic { key: string; name: string; description: string }
export interface ChannelProfile {
  id: number; name: string; url: string; logo: string; region: string; language: string; source_type: string
  description: string; topics: string[]; origin: string; needs_review: boolean; evidence_hash: string
  subscription_status: 'active' | 'inactive'; subscription_reason: string; feed_url: string; policy_key: string
  reading_policy: string; updated_at: string | null; news_count: number
  recent_articles?: Array<{ id: number; title: string; publish_time: string }>
}
export interface Catalog { topics: Topic[]; presets: Array<{ key: string; name: string; topics: string[] }>; sources: ChannelProfile[] }
export interface GroupingConfig { mode: GroupingMode; bindings: Record<string, number>; revision: number; ai_available: boolean }
export interface ProposalItem { source_id: number; name: string; topic_keys: string[]; reason: string; origin: string; needs_review: boolean }
export interface Proposal {
  id: string; engine: 'rules' | 'ai'; status: string; source_ids: number[]; topic_keys: string[]; result: ProposalItem[]
  error_code: string; created_at: string; expires_at: string; applied_count: number; model_id: string; attempts: number
}
export interface ReadingStats { today: number; total: number; streak: number; timezone: string; week: Array<{ day: string; count: number }> }
export interface Dashboard { kind: 'latest' | 'popular'; stories: Array<{ id: number; title: string; source_name: string; publish_time: string }> }
export interface SiteClassifier { enabled: boolean; is_owner: boolean; daily_limit: number; jobs: Proposal[]; intake_requests: Array<{ id: number; url: string; status: string; created_at: string }> }

export class WorkspaceError extends Error {
  readonly status: number
  constructor(message: string, status: number) { super(message); this.name = 'WorkspaceError'; this.status = status }
}

function csrfCookie(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

export async function workspaceRequest<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (options.signal?.aborted) controller.abort()
  options.signal?.addEventListener('abort', abort, { once: true })
  const timeout = setTimeout(abort, 20_000)
  const method = options.method ?? 'GET'
  try {
    if (method !== 'GET' && !csrfCookie()) {
      const csrf = await fetch('/api/auth/csrf/', { credentials: 'same-origin', signal: controller.signal })
      if (!csrf.ok) throw new WorkspaceError('无法初始化安全会话，请重新登录。', csrf.status)
    }
    const response = await fetch('/api' + path, {
      method, credentials: 'same-origin', signal: controller.signal,
      headers: { Accept: 'application/json', ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(method !== 'GET' ? { 'X-CSRFToken': csrfCookie() } : {}) },
      ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
    })
    if (response.status === 204) return undefined as T
    let value: unknown
    try { value = await response.json() } catch { throw new WorkspaceError('服务器未返回有效数据，请重试。', response.status) }
    if (!response.ok) {
      const detail = typeof value === 'object' && value !== null ? (value as Record<string, unknown>).detail : null
      throw new WorkspaceError(typeof detail === 'string' ? detail : '操作未完成，请重试或检查登录状态。', response.status)
    }
    return value as T
  } finally {
    clearTimeout(timeout)
    options.signal?.removeEventListener('abort', abort)
  }
}

export const workspaceKeys = {
  all: ['workspace'] as const,
  catalog: ['workspace', 'catalog'] as const,
  config: (viewer: number | string) => ['workspace', viewer, 'grouping-config'] as const,
  proposals: (viewer: number | string) => ['workspace', viewer, 'proposals'] as const,
  proposal: (viewer: number | string, id: string | null) => ['workspace', viewer, 'proposal', id] as const,
  stats: (viewer: number | string) => ['workspace', viewer, 'reading-stats'] as const,
}
export const workspaceCatalogOptions = () => queryOptions({
  queryKey: workspaceKeys.catalog,
  queryFn: ({ signal }) => workspaceRequest<Catalog>('/smart-channels/catalog/', { signal }), staleTime: 60_000,
})
export const workspaceConfigOptions = (viewer: number | string) => queryOptions({
  queryKey: workspaceKeys.config(viewer), queryFn: ({ signal }) => workspaceRequest<GroupingConfig>('/me/smart-channels/settings/', { signal }),
})
export function safeExternalUrl(value: string): string | undefined {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined } catch { return undefined }
}
export function workspaceError(error: unknown): string { return error instanceof WorkspaceError ? error.message : '操作未完成，请检查网络后重试。' }
export const originLabel: Record<string, string> = { catalog: '目录规则', policy: '专题资料', manual: '人工确认', ai: 'AI 建议·待确认', unknown: '信息不足', rules: '规则推荐' }
export const proposalStatus: Record<string, string> = { queued: '等待后台处理', running: 'AI 分析中', ready: '待确认', applied: '已应用', cancelled: '已取消', undone: '已撤销', failed: '处理失败' }
