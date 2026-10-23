import { isRecord } from '@/types/news'

export type NewsScope = 'all' | 'subscribed' | 'ungrouped' | 'group'
export interface NewsPreference { scope: NewsScope; group_id: number | null }
export interface Channel {
  region: import('@/types/news').SourceRegion; reading_policy: import('@/types/news').ReadingPolicy
  id: number; name: string; description: string; language: string; source_type: string
  can_subscribe: boolean; rss_status: string
  subscription_status: 'active' | 'inactive'; subscription_reason: string; news_count: number
}
export interface ChannelSubscription { id: number; source_id: number; group_ids: number[]; category_id?: number | null; category_version?: number }
export interface ChannelGroupRoot {
  id: number; name: string; version: number; child_count: number; created_at: string; updated_at: string
}
export interface ChannelGroup {
  id: number; root_id: number; name: string; source_ids: number[]; version: number; created_at: string; updated_at: string
}
export const newsScopes: NewsScope[] = ['all', 'subscribed', 'ungrouped', 'group']
function numberIds(value: unknown): number[] {
  if (!Array.isArray(value) || value.some(id => typeof id !== 'number' || !Number.isSafeInteger(id) || id <= 0) ||
      new Set(value).size !== value.length) throw new TypeError('Invalid channel IDs')
  return value as number[]
}
function positiveId(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}
function validName(value: unknown): value is string {
  if (typeof value !== 'string' || value.length === 0 || value.length > 40 || value.trim() !== value) return false
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index)
    if (code < 32 || code === 127) return false
  }
  return true
}
function validVersion(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 1
}
function validTimestamp(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}
function assertUnique(rows: Array<{ id: number; name: string }>, label: string) {
  if (new Set(rows.map(row => row.id)).size !== rows.length ||
      new Set(rows.map(row => row.name.toLocaleLowerCase())).size !== rows.length) {
    throw new TypeError(`Invalid ${label} uniqueness`)
  }
}
export function parseChannels(value: unknown): Channel[] {
  if (!Array.isArray(value)) throw new TypeError('Invalid channel directory')
  return value.map(item => {
    if (!isRecord(item) || typeof item.id !== 'number' || typeof item.name !== 'string' ||
      (item.subscription_status !== 'active' && item.subscription_status !== 'inactive')) throw new TypeError('Invalid channel')
    return { can_subscribe: item.can_subscribe === true, rss_status: String(item.rss_status ?? 'unconfigured'), region: item.region === 'domestic' ? 'domestic' : 'international', reading_policy: item.reading_policy === 'rss_summary_only' || item.reading_policy === 'public_rss' ? item.reading_policy : 'standard', id: item.id, name: item.name, description: typeof item.description === 'string' ? item.description : '',
      language: String(item.language ?? ''), source_type: String(item.source_type ?? ''), subscription_status: item.subscription_status,
      subscription_reason: String(item.subscription_reason ?? ''), news_count: Number(item.news_count ?? 0) }
  })
}
export function parseSubscriptions(value: unknown): ChannelSubscription[] {
  if (!Array.isArray(value)) throw new TypeError('Invalid subscriptions')
  return value.map(item => {
    if (!isRecord(item) || typeof item.id !== 'number' || typeof item.source_id !== 'number') throw new TypeError('Invalid subscription')
    if (item.category_id != null && (!Number.isSafeInteger(item.category_id) || (item.category_id as number) <= 0)) throw new TypeError('Invalid category')
    if (item.category_version !== undefined && (!Number.isSafeInteger(item.category_version) || (item.category_version as number) < 0)) throw new TypeError('Invalid category version')
    const groupIds = numberIds(item.group_ids)
    if (groupIds.length > 3) throw new TypeError('Invalid subscription groups')
    return { id: item.id, source_id: item.source_id, group_ids: groupIds, category_id: item.category_id as number | null | undefined, category_version: (item.category_version as number | undefined) ?? 0 }
  })
}
export function parseRoots(value: unknown): ChannelGroupRoot[] {
  if (!Array.isArray(value)) throw new TypeError('Invalid group roots')
  const roots = value.map(item => {
    if (!isRecord(item) || !positiveId(item.id) || !validName(item.name) ||
        !validVersion(item.version) || typeof item.child_count !== 'number' ||
        !Number.isSafeInteger(item.child_count) || item.child_count < 0 ||
        !validTimestamp(item.created_at) || !validTimestamp(item.updated_at)) {
      throw new TypeError('Invalid group root')
    }
    return { id: item.id, name: item.name, version: item.version, child_count: item.child_count,
      created_at: item.created_at, updated_at: item.updated_at }
  })
  assertUnique(roots, 'group root')
  return roots
}
export function parseGroups(value: unknown): ChannelGroup[] {
  if (!Array.isArray(value)) throw new TypeError('Invalid groups')
  const groups = value.map(item => {
    if (!isRecord(item) || !positiveId(item.id) || !positiveId(item.root_id) ||
        !validName(item.name) || !validVersion(item.version) ||
        !validTimestamp(item.created_at) || !validTimestamp(item.updated_at)) {
      throw new TypeError('Invalid group')
    }
    return { id: item.id, root_id: item.root_id, name: item.name, source_ids: numberIds(item.source_ids),
      version: item.version, created_at: item.created_at, updated_at: item.updated_at }
  })
  assertUnique(groups, 'group')
  return groups
}
export function validateHierarchy(roots: ChannelGroupRoot[], groups: ChannelGroup[]): boolean {
  const rootIds = new Set(roots.map(root => root.id))
  const counts = new Map(roots.map(root => [root.id, 0]))
  for (const group of groups) {
    if (!rootIds.has(group.root_id)) return false
    counts.set(group.root_id, (counts.get(group.root_id) ?? 0) + 1)
  }
  return roots.every(root => counts.get(root.id) === root.child_count)
}
export function channelGroupPath(group: ChannelGroup, roots: ChannelGroupRoot[]): string {
  const root = roots.find(item => item.id === group.root_id)
  if (!root) throw new TypeError('Invalid group topology')
  return `${root.name} / ${group.name}`
}
export function parseNewsPreference(value: unknown): NewsPreference {
  if (!isRecord(value) || !newsScopes.includes(value.scope as NewsScope) ||
    (value.group_id !== null && typeof value.group_id !== 'number') || (value.scope === 'group' && value.group_id === null)) throw new TypeError('Invalid news preference')
  return { scope: value.scope as NewsScope, group_id: value.group_id as number | null }
}
