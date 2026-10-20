import { workspaceRequest } from '@/services/workspaceApi'
import { isRecord } from '@/types/news'

export interface Page<T> { results: T[]; count: number; page: number; page_size: number; counts?: Record<string, number> }
export interface Addition {
  operation_id: string; source_id: number | null; name: string; feed_url: string; state: string; version: number
  article_count?: number; article_state?: 'waiting' | 'ready' | 'empty'; can_recommend?: boolean; actions: string[]; error_code: string; cooldown_until: string; created_at: string; connection_state: string; recovery_of: string | null
}
export interface Recommendation {
  candidate_id: string; name: string; feed_url: string; category_id: number; category_name: string; language: string
  version: number; state: string; connection_state: string; public_source_id: number | null; scope_description: string
  cooldown_until?: string | null; can_review: boolean; can_verify: boolean; reason: string; error_code: string; member_sync_complete: boolean; created_at: string
  personal_source_id?: number | null; submission_id?: string; note?: string; withdrawn?: boolean
  notes?: { note: string; created_at: string }[]
  history?: { action: string; candidate_version: number; reason: string; created_at: string }[]
}
export interface Reviewer { id: number | null; username: string; active: boolean; version: number | null }
export interface PublicFeedInput { name: string; category_id: number; language: string; feed_url?: string; source_id?: number; note?: string; confirm_public_scope?: boolean }
export interface CategoryOption { id: number; name: string }
const operationStates = new Set(['pending', 'running', 'retry_wait', 'unknown', 'manual_blocked', 'succeeded', 'failed', 'cancelled'])
const reviewStates = new Set(['pending', 'approved', 'rejected', 'withdrawn', 'published'])
const positive = (x: unknown): x is number => Number.isSafeInteger(x) && (x as number) > 0
function addition(value: unknown): Addition {
  if (!isRecord(value) || typeof value.operation_id !== 'string' || typeof value.name !== 'string' || typeof value.feed_url !== 'string'
    || !operationStates.has(String(value.state)) || !positive(value.version) || !Array.isArray(value.actions)
    || value.actions.some(x => !['retry', 'reconcile', 'cancel'].includes(String(x))) || typeof value.cooldown_until !== 'string') throw new TypeError('添加记录无效，请刷新。')
  if (value.article_count !== undefined && (!Number.isSafeInteger(value.article_count) || (value.article_count as number) < 0)) throw new TypeError('文章数量无效。')
  if (value.article_state !== undefined && !['waiting', 'ready', 'empty'].includes(String(value.article_state))) throw new TypeError('文章状态无效。')
  return value as unknown as Addition
}
function recommendation(value: unknown): Recommendation {
  if (!isRecord(value) || typeof value.candidate_id !== 'string' || typeof value.name !== 'string' || typeof value.feed_url !== 'string'
    || !positive(value.version) || !positive(value.category_id) || !reviewStates.has(String(value.state))
    || typeof value.can_review !== 'boolean' || typeof value.can_verify !== 'boolean') throw new TypeError('推荐记录无效，请刷新。')
  return value as unknown as Recommendation
}
function reviewer(value: unknown): Reviewer {
  if (!isRecord(value) || typeof value.username !== 'string' || typeof value.active !== 'boolean'
    || (value.id !== null && !positive(value.id)) || (value.version !== null && !positive(value.version))) throw new TypeError('授权数据无效，请刷新。')
  return value as unknown as Reviewer
}
function page<T>(value: unknown, parse: (item: unknown) => T): Page<T> {
  if (!isRecord(value) || !Array.isArray(value.results) || !Number.isSafeInteger(value.count) || (value.count as number) < 0
    || !positive(value.page) || ![25, 50].includes(value.page_size as number)) throw new TypeError('列表数据无效，请刷新。')
  return { ...value, results: value.results.map(parse) } as Page<T>
}
const post = (path: string, viewer: number, body: object, key: string) => workspaceRequest<unknown>(path, { method: 'POST', viewer, body, idempotencyKey: key })
export const rssReviewKey = (viewer: number) => ['private', 'rss-review', viewer] as const
export const fetchAdditions = async (search: string, signal?: AbortSignal) => page(await workspaceRequest<unknown>('/me/rss-additions/?' + search, { signal }), addition)
export const actOnAddition = async (viewer: number, id: string, action: string, version: number, key: string) => addition(await post(`/me/rss-additions/${id}/actions/`, viewer, { action, expected_version: version }, key))
export const fetchMyRecommendations = async (search: string, signal?: AbortSignal) => page(await workspaceRequest<unknown>('/me/rss-recommendations/?' + search, { signal }), recommendation)
export const submitRecommendation = async (viewer: number, data: PublicFeedInput, key: string) => recommendation(await post('/me/rss-recommendations/', viewer, data, key))
export const changeRecommendation = async (viewer: number, id: string, data: object, key: string) => recommendation(await post(`/me/rss-recommendations/${id}/actions/`, viewer, data, key))
export const fetchRecommendations = async (search: string, signal?: AbortSignal) => page(await workspaceRequest<unknown>('/admin/rss/recommendations/?' + search, { signal }), recommendation)
export const fetchRecommendation = async (id: string, signal?: AbortSignal) => recommendation(await workspaceRequest<unknown>(`/admin/rss/recommendations/${id}/`, { signal }))
export const decideRecommendation = (viewer: number, id: string, data: object, key: string) => post(`/admin/rss/recommendations/${id}/decisions/`, viewer, data, key)
export const verifyRecommendation = (viewer: number, id: string, version: number, key: string) => post(`/admin/rss/recommendations/${id}/verification/`, viewer, { expected_version: version }, key)
export const registerPublicSource = (viewer: number, data: PublicFeedInput, key: string) => post('/admin/rss/sources/', viewer, data, key)
export async function fetchReviewers(search = '', signal?: AbortSignal): Promise<Reviewer[]> {
  const value = await workspaceRequest<unknown>('/admin/rss/reviewers/?' + search, { signal })
  if (!isRecord(value) || !Array.isArray(value.results)) throw new TypeError('授权列表无效。')
  return value.results.map(reviewer)
}
export const setReviewer = (viewer: number, data: { username: string; expected_version: number | null }, key: string) => post('/admin/rss/reviewers/', viewer, data, key)
export const revokeReviewer = (viewer: number, id: number, version: number, key: string) => post(`/admin/rss/reviewers/${id}/revoke/`, viewer, { expected_version: version }, key)
export async function fetchReviewCategories(signal?: AbortSignal): Promise<CategoryOption[]> {
  const value = await workspaceRequest<unknown>('/categories/', { signal })
  const rows = Array.isArray(value) ? value : isRecord(value) && Array.isArray(value.results) ? value.results : null
  if (!rows || rows.some(row => !isRecord(row) || !positive(row.id) || typeof row.name !== 'string')) throw new TypeError('分类列表无效。')
  return rows as CategoryOption[]
}
export const additionLabels: Record<string, string> = { pending: '等待连接', running: '连接中', retry_wait: '等待重试', unknown: '结果待核对', manual_blocked: '结果待核对', succeeded: '已连接', failed: '连接失败', cancelled: '已取消' }
export const recommendationLabels: Record<string, string> = { pending: '待审核', approved: '已通过审核，等待连接', rejected: '已驳回', withdrawn: '已撤回', published: '已公开' }
