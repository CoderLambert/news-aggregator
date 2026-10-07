import { queryOptions } from '@tanstack/react-query'
import { checkBlockedStatus, checkFavoriteStatus, fetchBlockedNews, fetchUserFavorites } from '@/services/api'
import { parseBlockStatus, parseBlockedNewsPage, parseFavoriteStatus, parseUserFavorites } from '@/types/userNews'
import type { FavoriteType } from '@/types/news'

export type FavoriteFilter = 'all' | FavoriteType

export const privateNewsKeys = {
  all: ['private'] as const,
  favorites: (viewerId: number, filter: FavoriteFilter = 'all') =>
    [...privateNewsKeys.all, 'favorites', { viewerId, filter }] as const,
  favoriteLists: (viewerId: number) => [...privateNewsKeys.all, 'favorites', { viewerId }] as const,
  blocked: (viewerId: number) => [...privateNewsKeys.all, 'blocked', { viewerId }] as const,
  favoriteStatus: (viewerId: number, newsId: number) =>
    [...privateNewsKeys.all, 'favorite-status', { viewerId, newsId }] as const,
  blockStatus: (viewerId: number, newsId: number) =>
    [...privateNewsKeys.all, 'block-status', { viewerId, newsId }] as const,
}

export const favoriteStatusOptions = (viewerId: number, newsId: number) =>
  queryOptions({
    queryKey: privateNewsKeys.favoriteStatus(viewerId, newsId),
    queryFn: async ({ signal }) => parseFavoriteStatus(await checkFavoriteStatus(newsId, signal)),
  })

export const blockStatusOptions = (viewerId: number, newsId: number) =>
  queryOptions({
    queryKey: privateNewsKeys.blockStatus(viewerId, newsId),
    queryFn: async ({ signal }) => parseBlockStatus(await checkBlockedStatus(newsId, signal)),
  })

export const favoritesOptions = (viewerId: number, filter: FavoriteFilter) =>
  queryOptions({
    queryKey: privateNewsKeys.favorites(viewerId, filter),
    queryFn: async ({ signal }) => parseUserFavorites(await fetchUserFavorites(filter === 'all' ? {} : { type: filter }, signal)),
  })

export const blockedNewsOptions = (viewerId: number) =>
  queryOptions({
    queryKey: privateNewsKeys.blocked(viewerId),
    queryFn: async ({ signal }) => parseBlockedNewsPage(await fetchBlockedNews({}, signal)),
  })
