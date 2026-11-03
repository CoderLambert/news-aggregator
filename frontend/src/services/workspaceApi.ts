import { queryOptions } from '@tanstack/react-query'

export type GroupingMode = 'off' | 'suggest' | 'auto'
export interface Topic { key: string; name: string; description: string }
export interface ChannelProfile {
  publication?: 'personal' | 'public' | null; collection_owner?: string | null
  id: number; name: string; url: string; logo: string; region: string; language: string; source_type: string
  description: string; topics: string[]; origin: string; needs_review: boolean; evidence_hash: string
  subscription_status: 'active' | 'inactive'; subscription_reason: string; feed_url: string; policy_key: string
  reading_policy: string; updated_at: string | null; news_count: number
  recent_articles?: Array<{ id: number; title: string; publish_time: string }>
}
export interface Catalog { topics: Topic[]; presets: Array<{ key: string; name: string; topics: string[] }>; sources: ChannelProfile[] }
export interface GroupingConfig { mode: GroupingMode; bindings: Record<string, number>; revision: number; ai_available: boolean; match_existing?: boolean; ai_enabled?: boolean; ai_model_id?: string | null; daily_limit?: number; error_code?: string; summary?: { pending: number; suggested: number; applied: number } }
export interface NewGroupPath { root_id: number | null; root_name: string | null; name: string }
export interface ProposalItem { source_id: number; name: string; topic_keys: string[]; group_ids?: number[]; new_group_paths?: NewGroupPath[]; reason: string; origin: string; needs_review: boolean }
export interface HierarchyProposalRow { root_id: number | null; root_name: string | null; group_ids: number[]; reason: string }
export interface Proposal {
  id: string; target?: 'groups' | 'topics' | 'hierarchy'; engine: 'rules' | 'ai'; status: string; source_ids: number[]; topic_keys: string[]; result: Array<ProposalItem | HierarchyProposalRow>
  error_code: string; created_at: string; expires_at: string; applied_count: number; model_id: string; attempts: number
}
export interface ProposalPage { results: Proposal[]; page: number; page_size: number; count: number; has_more: boolean }
export interface ReadingStats { today: number; total: number; streak: number; timezone: string; week: Array<{ day: string; count: number }> }
export interface Dashboard { kind: 'latest' | 'popular'; stories: Array<{ id: number; title: string; source_name: string; publish_time: string }> }
export interface ClassifierRuntime {
  feature_enabled: boolean; model_binding_valid: boolean; ready_to_dispatch: boolean
  daily_used: number; daily_remaining: number; job_counts: Record<string, number>
  expired_leases: number; failed_dispatched_jobs: number; next_retry_at: string | null
}
export interface SiteClassifier { runtime?: ClassifierRuntime; model_id?: string | null; enabled: boolean; is_owner: boolean; daily_limit: number; jobs: Proposal[]; intake_requests: Array<{ id: number; url: string; status: string; created_at: string }> }

export class WorkspaceError extends Error {
  readonly status: number
  constructor(message: string, status: number) { super(message); this.name = 'WorkspaceError'; this.status = status }
}
let workspaceViewer: number | null = null
export function setWorkspaceViewer(viewer: number | null): void { workspaceViewer = viewer }
function csrfCookie(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

function responseErrorMessage(value: unknown, status: number): string {
  if (status === 401) return '请先登录后再进行此操作。'
  if (status === 403) return '当前操作没有权限，或安全会话已过期。请刷新页面后重试。'
  if (status >= 500) return '服务暂时不可用，请稍后重试。'
  const record = typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined
  // DRF validation errors may be a list, or a field error, rather than `detail`.
  const envelope = record?.error && typeof record.error === 'object' ? record.error as Record<string, unknown> : undefined
  const candidate = envelope?.message ?? record?.detail ?? ((status === 400 || status === 422)
    ? record?.url ?? record?.non_field_errors ?? (Array.isArray(value) ? value : undefined) : undefined)
  const message = typeof candidate === 'string' ? candidate
    : Array.isArray(candidate) && candidate.every(item => typeof item === 'string') ? candidate.join('；') : ''
  // Only plain, bounded API messages; never display HTML or server diagnostics.
  if (message.trim() && message.length <= 300 && !/[<>]/.test(message)
    && !Array.from(message).some(character => character.charCodeAt(0) < 32)) return message.trim()
  if (status === 400 || status === 422) return '请求参数不正确，请检查输入后重试。'
  return '操作未完成，请稍后重试。'
}

export async function workspaceRequest<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal; viewer?: number; idempotencyKey?: string } = {}): Promise<T> {
  const viewer = options.viewer ?? workspaceViewer
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
    if (method !== 'GET' && viewer !== workspaceViewer) throw new WorkspaceError('账号已变化，请重新操作。', 409)
    const response = await fetch('/api' + path, {
      method, credentials: 'same-origin', signal: controller.signal,
      headers: { Accept: 'application/json', ...(options.body !== undefined && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
        ...(options.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : {}),
        ...(method !== 'GET' ? { 'X-CSRFToken': csrfCookie(), ...(viewer !== null ? { 'X-Workspace-Viewer': String(viewer) } : {}) } : {}) },
      ...(options.body !== undefined ? { body: options.body instanceof FormData ? options.body : JSON.stringify(options.body) } : {}),
    })
    if (response.status === 204) return undefined as T
    let value: unknown
    try { value = await response.json() } catch {
      throw new WorkspaceError(response.ok ? '服务器未返回有效数据，请重试。' : responseErrorMessage(undefined, response.status), response.status)
    }
    if (!response.ok) {
      throw new WorkspaceError(responseErrorMessage(value, response.status), response.status)
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
  viewerCatalog: (viewer: number | string, purpose: 'subscribe' | 'history') => ['workspace', 'catalog', { viewer, purpose }] as const,
  config: (viewer: number | string) => ['workspace', viewer, 'grouping-config'] as const,
  proposals: (viewer: number | string) => ['workspace', viewer, 'proposals'] as const,
  proposalHistory: (viewer: number | string, target: 'groups' | 'topics' | 'hierarchy', page: number) => ['workspace', viewer, 'proposals', { target, page }] as const,
  proposal: (viewer: number | string, id: string | null) => ['workspace', viewer, 'proposal', id] as const,
  stats: (viewer: number | string) => ['workspace', viewer, 'reading-stats'] as const,
}
export const workspaceCatalogOptions = (viewer: number | string, purpose: 'subscribe' | 'history' = 'history') => queryOptions({
  queryKey: workspaceKeys.viewerCatalog(viewer, purpose),
  queryFn: ({ signal }) => workspaceRequest<Catalog>('/smart-channels/catalog/?purpose=' + purpose, { signal }), staleTime: 60_000,
})
export const workspaceConfigOptions = (viewer: number | string) => queryOptions({
  queryKey: workspaceKeys.config(viewer), queryFn: ({ signal }) => workspaceRequest<GroupingConfig>('/me/smart-channels/settings/', { signal }),
})
export function safeExternalUrl(value: string): string | undefined {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined } catch { return undefined }
}
export function workspaceError(error: unknown): string { return error instanceof WorkspaceError ? error.message : '操作未完成，请检查网络后重试。' }
export const originLabel: Record<string, string> = { catalog: '目录规则', policy: '专题资料', manual: '人工确认', ai: 'AI 建议·待确认', unknown: '信息不足', title_evidence: '标题证据推测·待确认', rules: '规则推荐' }
export const proposalStatus: Record<string, string> = { queued: '等待后台处理', running: 'AI 分析中', ready: '待确认', applied: '已应用', cancelled: '已取消', undone: '已撤销', failed: '处理失败' }
