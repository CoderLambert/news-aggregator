import { isRecord, parsePage } from '@/types/news'
import type { FavoriteType, Page } from '@/types/news'

export interface FavoriteNewsItem {
  id: number
  title: string
  title_zh: string
  content: string
  content_zh: string
  url: string
  cover_image: string
  source_name: string
  category_name: string
  publish_time: string
  created_at: string
}

export interface UserFavorite {
  id: number
  news: FavoriteNewsItem
  type: FavoriteType
  created_at: string
}

export interface BlockedNewsItem {
  id: number
  news: FavoriteNewsItem
  created_at: string
}

export interface FavoriteToggleResult {
  created: boolean
  removed: boolean
  favorite?: UserFavorite
}

export interface BlockMutationResult {
  created: boolean
  removed: boolean
}

function requiredNumber(value: Record<string, unknown>, key: string): number {
  if (typeof value[key] !== 'number' || !Number.isSafeInteger(value[key])) {
    throw new TypeError(`Invalid user-news response: ${key} must be an integer`)
  }
  return value[key] as number
}

function requiredString(value: Record<string, unknown>, key: string): string {
  if (typeof value[key] !== 'string') throw new TypeError(`Invalid user-news response: ${key} must be a string`)
  return value[key] as string
}

function parseFavoriteNews(value: unknown): FavoriteNewsItem {
  if (!isRecord(value)) throw new TypeError('Invalid favorite response: news must be an object')
  return {
    id: requiredNumber(value, 'id'),
    title: requiredString(value, 'title'),
    title_zh: typeof value.title_zh === 'string' ? value.title_zh : '',
    content: typeof value.content === 'string' ? value.content : '',
    content_zh: typeof value.content_zh === 'string' ? value.content_zh : '',
    url: typeof value.url === 'string' ? value.url : '',
    cover_image: typeof value.cover_image === 'string' ? value.cover_image : '',
    source_name: typeof value.source_name === 'string'
      ? value.source_name
      : isRecord(value.source) && typeof value.source.name === 'string' ? value.source.name : '',
    category_name: typeof value.category_name === 'string'
      ? value.category_name
      : isRecord(value.category) && typeof value.category.name === 'string' ? value.category.name : '',
    publish_time: requiredString(value, 'publish_time'),
    created_at: typeof value.created_at === 'string' ? value.created_at : '',
  }
}

export function parseUserFavorite(value: unknown): UserFavorite {
  if (!isRecord(value) || (value.type !== 'like' && value.type !== 'bookmark')) {
    throw new TypeError('Invalid favorite response')
  }
  return {
    id: requiredNumber(value, 'id'),
    news: parseFavoriteNews(value.news),
    type: value.type,
    created_at: requiredString(value, 'created_at'),
  }
}

export function parseBlockedNews(value: unknown): BlockedNewsItem {
  if (!isRecord(value)) throw new TypeError('Invalid blocked-news response')
  return {
    id: requiredNumber(value, 'id'),
    news: parseFavoriteNews(value.news),
    created_at: requiredString(value, 'created_at'),
  }
}

export function parseUserFavorites(value: unknown): Page<UserFavorite> {
  return parsePage(value, parseUserFavorite)
}

export function parseBlockedNewsPage(value: unknown): Page<BlockedNewsItem> {
  return parsePage(value, parseBlockedNews)
}

export function parseFavoriteStatus(value: unknown) {
  if (!isRecord(value)
    || typeof value.is_liked !== 'boolean'
    || typeof value.is_bookmarked !== 'boolean'
    || typeof value.like_count !== 'number'
    || typeof value.bookmark_count !== 'number') {
    throw new TypeError('Invalid favorite-status response')
  }
  return {
    is_liked: value.is_liked,
    is_bookmarked: value.is_bookmarked,
    like_count: value.like_count,
    bookmark_count: value.bookmark_count,
  }
}

export function parseBlockStatus(value: unknown) {
  if (!isRecord(value) || typeof value.is_blocked !== 'boolean') {
    throw new TypeError('Invalid block-status response')
  }
  return { is_blocked: value.is_blocked }
}

function parseMutationFlags(value: unknown, endpoint: string): { created: boolean; removed: boolean } {
  if (!isRecord(value)
    || (value.created !== undefined && typeof value.created !== 'boolean')
    || (value.removed !== undefined && typeof value.removed !== 'boolean')
    || (value.created === undefined && value.removed === undefined)) {
    throw new TypeError(`Invalid ${endpoint} mutation response`)
  }
  return {
    created: value.created === true,
    removed: value.removed === true,
  }
}

export function parseFavoriteToggleResult(value: unknown): FavoriteToggleResult {
  const result = parseMutationFlags(value, 'favorite')
  if (result.created && result.removed) throw new TypeError('Invalid favorite mutation response')
  return {
    ...result,
    ...(result.created && isRecord(value) && 'news' in value ? { favorite: parseUserFavorite(value) } : {}),
  }
}

export function parseBlockMutationResult(value: unknown): BlockMutationResult {
  return parseMutationFlags(value, 'block')
}
