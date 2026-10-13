import { isRecord } from '@/types/news'

export type NewsScope = 'all' | 'subscribed' | 'ungrouped' | 'group'
export interface NewsPreference { scope: NewsScope; group_id: number | null }
export interface Channel {
  region: import('@/types/news').SourceRegion; reading_policy: import('@/types/news').ReadingPolicy
  id: number; name: string; description: string; language: string; source_type: string
  subscription_status: 'active' | 'inactive'; subscription_reason: string; news_count: number
}
export interface ChannelSubscription { id: number; source_id: number; group_ids: number[] }
export interface ChannelGroup { id: number; name: string; source_ids: number[] }
export const newsScopes: NewsScope[] = ['all', 'subscribed', 'ungrouped', 'group']
function numberIds(value: unknown): number[] {
  if (!Array.isArray(value) || value.some(id => typeof id !== 'number' || !Number.isSafeInteger(id) || id <= 0)) throw new TypeError('Invalid channel IDs')
  return value as number[]
}
export function parseChannels(value: unknown): Channel[] {
  if (!Array.isArray(value)) throw new TypeError('Invalid channel directory')
  return value.map(item => {
    if (!isRecord(item) || typeof item.id !== 'number' || typeof item.name !== 'string' ||
      (item.subscription_status !== 'active' && item.subscription_status !== 'inactive')) throw new TypeError('Invalid channel')
    return { region: item.region === 'domestic' ? 'domestic' : 'international', reading_policy: item.reading_policy === 'rss_summary_only' || item.reading_policy === 'public_rss' ? item.reading_policy : 'standard', id: item.id, name: item.name, description: typeof item.description === 'string' ? item.description : '',
      language: String(item.language ?? ''), source_type: String(item.source_type ?? ''), subscription_status: item.subscription_status,
      subscription_reason: String(item.subscription_reason ?? ''), news_count: Number(item.news_count ?? 0) }
  })
}
export function parseSubscriptions(value: unknown): ChannelSubscription[] {
  if (!Array.isArray(value)) throw new TypeError('Invalid subscriptions')
  return value.map(item => {
    if (!isRecord(item) || typeof item.id !== 'number' || typeof item.source_id !== 'number') throw new TypeError('Invalid subscription')
    return { id: item.id, source_id: item.source_id, group_ids: numberIds(item.group_ids) }
  })
}
export function parseGroups(value: unknown): ChannelGroup[] {
  if (!Array.isArray(value)) throw new TypeError('Invalid groups')
  return value.map(item => {
    if (!isRecord(item) || typeof item.id !== 'number' || typeof item.name !== 'string') throw new TypeError('Invalid group')
    return { id: item.id, name: item.name, source_ids: numberIds(item.source_ids) }
  })
}
export function parseNewsPreference(value: unknown): NewsPreference {
  if (!isRecord(value) || !newsScopes.includes(value.scope as NewsScope) ||
    (value.group_id !== null && typeof value.group_id !== 'number') || (value.scope === 'group' && value.group_id === null)) throw new TypeError('Invalid news preference')
  return { scope: value.scope as NewsScope, group_id: value.group_id as number | null }
}
