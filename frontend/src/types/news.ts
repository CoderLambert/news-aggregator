export type SearchMode = 'keyword' | 'semantic' | 'hybrid'
export type DisplayMode = 'zh' | 'original' | 'bilingual'
export type Language = 'zh' | 'en'
export type FavoriteType = 'like' | 'bookmark'
export type SourceType = 'news' | 'aggregator' | 'discussion'
export type SearchOrderBy = 'relevance' | 'time'

export interface NewsListParams {
  page: number
  page_size: number
  search?: string
  mode?: SearchMode
  category?: string
  source?: string
  order_by?: SearchOrderBy
  full_content?: 'true'
  publish_time_after?: string
  source__source_type?: SourceType
}
export interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface NewsSummary {
  id: number
  title: string
  content: string
  title_zh: string
  content_zh: string
  author: string | null
  publish_time: string
  source: number
  source_name: string
  source_type: string
  source_language: string
  category: number
  category_name: string
  url: string
  cover_image: string | null
  created_at: string
  related_to: number | null
  translation_status: string
  translation_error: string
  translation_retry_count: number
  full_content_fetch_status: string
  full_content_fetch_error: string
  full_content_fetch_provider: string
  full_content_quality_score: number | null
  full_content_retry_count: number
  last_full_content_attempt: string | null
}


export interface NewsDetail extends NewsSummary {
  source_url: string
  full_content: string
  full_content_fetched_at: string | null
  full_content_zh: string
  full_content_zh_fetched_at: string | null
  full_content_zh_source: string | null
  full_translation_active: boolean
}

export interface FilterOption {
  id: number
  name: string
}

export interface FavoriteStatus {
  is_liked: boolean
  is_bookmarked: boolean
  like_count: number
  bookmark_count: number
}

export interface BlockStatus {
  is_blocked: boolean
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function requiredString(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  if (typeof value !== 'string') throw new TypeError(`Invalid news response: ${key} must be a string`)
  return value
}

function requiredNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key]
  if (typeof value !== 'number') throw new TypeError(`Invalid news response: ${key} must be a number`)
  return value
}

export function parseNewsSummary(value: unknown): NewsSummary {
  if (!isRecord(value)) throw new TypeError('Invalid news response: expected an object')
  const nullableString = (key: string) => typeof value[key] === 'string' ? value[key] as string : ''
  const nullableNumber = (key: string) => typeof value[key] === 'number' ? value[key] as number : null
  return {
    id: requiredNumber(value, 'id'),
    title: requiredString(value, 'title'),
    content: nullableString('content'),
    title_zh: nullableString('title_zh'),
    content_zh: nullableString('content_zh'),
    author: typeof value.author === 'string' ? value.author : null,
    publish_time: requiredString(value, 'publish_time'),
    source: requiredNumber(value, 'source'),
    source_name: requiredString(value, 'source_name'),
    source_type: nullableString('source_type'),
    source_language: nullableString('source_language'),
    category: requiredNumber(value, 'category'),
    category_name: requiredString(value, 'category_name'),
    url: nullableString('url'),
    cover_image: typeof value.cover_image === 'string' ? value.cover_image : null,
    created_at: nullableString('created_at'),
    related_to: nullableNumber('related_to'),
    translation_status: nullableString('translation_status'),
    translation_error: nullableString('translation_error'),
    translation_retry_count: typeof value.translation_retry_count === 'number' ? value.translation_retry_count : 0,
    full_content_fetch_status: nullableString('full_content_fetch_status'),
    full_content_fetch_error: nullableString('full_content_fetch_error'),
    full_content_fetch_provider: nullableString('full_content_fetch_provider'),
    full_content_quality_score: nullableNumber('full_content_quality_score'),
    full_content_retry_count: typeof value.full_content_retry_count === 'number' ? value.full_content_retry_count : 0,
    last_full_content_attempt: typeof value.last_full_content_attempt === 'string' ? value.last_full_content_attempt : null,
  }
}

export function parsePage<T>(value: unknown, parseItem: (item: unknown) => T): Page<T> {
  if (Array.isArray(value)) return { count: value.length, next: null, previous: null, results: value.map(parseItem) }
  if (!isRecord(value) || !Array.isArray(value.results)) {
    throw new TypeError('Invalid list response: expected results array')
  }
  return {
    count: typeof value.count === 'number' ? value.count : value.results.length,
    next: typeof value.next === 'string' ? value.next : null,
    previous: typeof value.previous === 'string' ? value.previous : null,
    results: value.results.map(parseItem),
  }
}

export function parseFilterOptions(value: unknown): FilterOption[] {
  const values = Array.isArray(value) ? value : isRecord(value) && Array.isArray(value.results) ? value.results : null
  if (!values) throw new TypeError('Invalid filter response: expected an array')
  return values.flatMap((item) => {
    if (!isRecord(item) || typeof item.id !== 'number' || typeof item.name !== 'string') return []
    return [{ id: item.id, name: item.name }]
  })
}

export function parseNewsDetail(value: unknown): NewsDetail {
  if (!isRecord(value)) throw new TypeError('Invalid detail response: expected an object')
  const summary = parseNewsSummary(value)
  const nullableDate = (key: string) => typeof value[key] === 'string' ? value[key] as string : null
  return {
    ...summary,
    source_url: typeof value.source_url === 'string' ? value.source_url : '',
    full_content: typeof value.full_content === 'string' ? value.full_content : '',
    full_content_fetched_at: nullableDate('full_content_fetched_at'),
    full_content_zh: typeof value.full_content_zh === 'string' ? value.full_content_zh : '',
    full_content_zh_fetched_at: nullableDate('full_content_zh_fetched_at'),
    full_content_zh_source: typeof value.full_content_zh_source === 'string' ? value.full_content_zh_source : null,
    full_translation_active: typeof value.full_translation_active === 'boolean' ? value.full_translation_active : false,
  }
}
// Response parsing stays centralized at the API boundary.
