import { workspaceRequest } from '@/services/workspaceApi'
import { isRecord } from '@/types/news'

export type VerificationStatus = 'unverified' | 'verifying' | 'passed' | 'failed' | 'unknown' | 'paused'
export interface VerificationHistory {
  id: string; state: string; phase: string; attempts: number; error_code: string
  created_at: string; updated_at: string; resolved_at: string | null; resolution: string; recovery_of: string | null
}
export interface VerificationFeed {
  id: string; feed_url: string; effective_feed_url?: string; status: VerificationStatus; policy_version: number
  connection_state: string; error_code: string; operation_state: string | null; execution_phase: string
  checked_at: string | null; cooldown_until: string | null; can_verify: boolean; action_reason: string
  recovery_requires_boundary: boolean; history?: VerificationHistory[]
}
export interface VerificationSource {
  source_id: number; name: string; status: VerificationStatus; feeds: VerificationFeed[]
  can_subscribe: boolean; can_verify: boolean; pending: boolean; expected_versions: Record<string, number>
}
export interface VerificationList {
  results: VerificationSource[]; count: number; counts: Record<string, number>; page: number; page_size: number; server_time: string
}
export interface VerificationBatch {
  id: string; items: { source_id?: number; name?: string; binding_id?: string; status: string; reason: string; operation_id?: string | null }[]
  counts: Record<string, number>; done: boolean
}
export const verificationLabels: Record<string, string> = {
  pending: '待处理', unverified: '未核验', verifying: '核验中', passed: '已通过', failed: '失败', unknown: '结果未知', paused: '已暂停', all: '全部',
}
export const phaseLabels: Record<string, string> = { missing: '缺少执行记录', not_sent: '尚未发送请求', possibly_sent: '请求可能已发送，正在核对', final_response: '已收到最终响应' }
export const actionReasons: Record<string, string> = {
  paused: '频道已暂停，请先确认采集设置。', in_progress: '正在执行，请等待本次核验完成。', cooldown: '刚提交过核验，请等待冷却结束。',
  cancelled: '原请求已取消，请先由管理员确认取消原因。', unsupported_association_policy: '当前频道筛选策略不支持自动恢复。',
  source_collection_not_permitted: '来源策略不允许采集。', full_content_disabled: '当前实例已关闭正文采集。',
  full_content_policy_not_permitted: '来源策略不允许当前正文模式。',
}
export function verificationError(code: string): string {
  return ({ feed_source_not_found: 'RSSHub 路由不存在或源站返回 404，请核对该路由的参数。',
    feed_source_forbidden: '来源拒绝访问（403），可能有访问限制或需要站点认证。',
    feed_source_auth_required: '来源需要认证（401），请由站点管理员配置；不要把凭据粘贴到地址中。',
    feed_source_unavailable: 'RSSHub 或源站暂不可用（503）；可能缺少路由所需配置，请稍后重试或查看站点配置。',
    feed_parse_failed: '来源返回的内容不是有效 RSS，解析失败。', create_unknown: '连接请求超时，结果仍需核对。', create_outcome_unproven: '尚未找到可确认的连接；旧请求结束前不能再次创建。',
    authentication: 'RSS 引擎认证失败，请检查服务配置。', forbidden: 'RSS 引擎拒绝访问。', rate_limited: '源站或引擎限流，将按要求等待后重试。',
    upstream_http: '引擎返回抓取或解析失败，请检查来源是否可用。', identity_conflict: '引擎中存在多个匹配连接，需要人工确认。',
    stale_remote_outcome_unknown: '频道设置已改变，旧结果未提交。', network: '暂时无法连接 RSS 引擎。',
  } as Record<string, string>)[code] ?? (code ? '核验尚未成功，请查看记录后重试。' : '')
}
const statuses = new Set(['unverified', 'verifying', 'passed', 'failed', 'unknown', 'paused'])
function parseSource(value: unknown): VerificationSource {
  if (!isRecord(value) || typeof value.source_id !== 'number' || typeof value.name !== 'string'
      || !statuses.has(String(value.status)) || !Array.isArray(value.feeds) || !isRecord(value.expected_versions)
      || Object.values(value.expected_versions).some(v => !Number.isSafeInteger(v) || (v as number) < 1)
      || value.feeds.some(f => !isRecord(f) || typeof f.id !== 'string' || typeof f.feed_url !== 'string'
        || !statuses.has(String(f.status)) || typeof f.can_verify !== 'boolean' || typeof f.action_reason !== 'string'
        || typeof f.execution_phase !== 'string' || typeof f.error_code !== 'string')) throw new TypeError('频道核验数据无效。')
  return value as unknown as VerificationSource
}
export async function fetchVerificationList(search: string, signal?: AbortSignal): Promise<VerificationList> {
  const value = await workspaceRequest<unknown>('/admin/rss/sources/?' + search, { signal })
  if (!isRecord(value) || !Array.isArray(value.results) || !isRecord(value.counts) || typeof value.count !== 'number'
      || typeof value.page !== 'number' || typeof value.page_size !== 'number' || typeof value.server_time !== 'string') throw new TypeError('频道列表数据无效。')
  return { ...value, results: value.results.map(parseSource) } as VerificationList
}
export async function fetchVerificationDetail(source: number, signal?: AbortSignal): Promise<VerificationSource> {
  return parseSource(await workspaceRequest<unknown>(`/admin/rss/sources/${source}/verification/`, { signal }))
}
export const rssAdminKey = (viewer: number) => ['private', 'rss-admin-verification', viewer] as const
