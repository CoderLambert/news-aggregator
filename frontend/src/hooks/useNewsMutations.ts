import { useMutation, useQueryClient } from '@tanstack/react-query'
import { blockNews, toggleFavorite, unblockNews } from '@/services/api'
import { newsKeys } from '@/services/newsQueries'
import { privateNewsKeys } from '@/services/userNewsQueries'
import { isRecord } from '@/types/news'
import type { BlockStatus, FavoriteStatus, FavoriteType, Page } from '@/types/news'
import { parseBlockMutationResult, parseFavoriteToggleResult } from '@/types/userNews'
import type { FavoriteFilter } from '@/services/userNewsQueries'
import type { UserFavorite } from '@/types/userNews'

interface NewsMutationVariables {
  newsId: number
  viewerId: number
}

interface FavoriteMutationVariables extends NewsMutationVariables {
  type: FavoriteType
}

function assertVariables({ newsId, viewerId }: NewsMutationVariables) {
  if (!Number.isSafeInteger(newsId) || newsId < 1 || !Number.isSafeInteger(viewerId) || viewerId < 1) {
    throw new Error('Sign in to change your news preferences.')
  }
}

export function useToggleFavorite() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ newsId, viewerId, type }: FavoriteMutationVariables) => {
      assertVariables({ newsId, viewerId })
      const result = parseFavoriteToggleResult(await toggleFavorite(newsId, type))
      return { newsId, viewerId, type, result }
    },
    onSuccess: async ({ newsId, viewerId, type, result }) => {
      const favoriteListsKey = privateNewsKeys.favoriteLists(viewerId)
      const favoriteStatusKey = privateNewsKeys.favoriteStatus(viewerId, newsId)
      if (!result.created && !result.removed) {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: favoriteListsKey }),
          queryClient.invalidateQueries({ queryKey: favoriteStatusKey, exact: true }),
        ])
        return
      }

      queryClient.setQueryData<FavoriteStatus>(privateNewsKeys.favoriteStatus(viewerId, newsId), (current) => {
        if (!current) return current
        const field = type === 'like' ? 'is_liked' : 'is_bookmarked'
        const count = type === 'like' ? 'like_count' : 'bookmark_count'
        const delta = result.created ? 1 : -1
        return { ...current, [field]: result.created, [count]: Math.max(0, current[count] + delta) }
      })

      const cachedFavorites = queryClient.getQueriesData<Page<UserFavorite>>({
        queryKey: privateNewsKeys.favoriteLists(viewerId),
      })
      for (const [queryKey, current] of cachedFavorites) {
        if (!current) continue
        const scope = queryKey[2]
        const filter = isRecord(scope) && (scope.filter === 'all' || scope.filter === 'like' || scope.filter === 'bookmark')
          ? scope.filter as FavoriteFilter
          : 'all'
        if ((result.removed || result.created) && filter !== 'all' && filter !== type) continue

        const containsFavorite = current.results.some((favorite) => favorite.news.id === newsId && favorite.type === type)
        const results = current.results.filter((favorite) => favorite.news.id !== newsId || favorite.type !== type)
        if (result.created && result.favorite && !containsFavorite) results.unshift(result.favorite)
        const countDelta = result.created ? 1 : -1
        queryClient.setQueryData(queryKey, {
          ...current,
          count: Math.max(0, current.count + countDelta),
          results,
        })
      }

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: favoriteListsKey }),
        queryClient.invalidateQueries({ queryKey: favoriteStatusKey, exact: true }),
      ])
    },
  })
}

export function useBlockNews() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ newsId, viewerId }: NewsMutationVariables) => {
      assertVariables({ newsId, viewerId })
      const result = parseBlockMutationResult(await blockNews(newsId))
      return { newsId, viewerId, result }
    },
    onMutate: async ({ newsId, viewerId }) => {
      await queryClient.cancelQueries({ queryKey: privateNewsKeys.blockStatus(viewerId, newsId), exact: true })
    },
    onSuccess: async ({ newsId, viewerId }) => {
      const blockStatusKey = privateNewsKeys.blockStatus(viewerId, newsId)
      await queryClient.cancelQueries({ queryKey: blockStatusKey, exact: true })
      queryClient.setQueryData<BlockStatus>(blockStatusKey, { is_blocked: true })
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: blockStatusKey, exact: true }),
        queryClient.invalidateQueries({ queryKey: newsKeys.viewerLists(viewerId) }),
        queryClient.invalidateQueries({ queryKey: privateNewsKeys.blocked(viewerId) }),
      ]).catch(() => undefined)
    },
  })
}

export function useUnblockNews() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ newsId, viewerId }: NewsMutationVariables) => {
      assertVariables({ newsId, viewerId })
      const result = parseBlockMutationResult(await unblockNews(newsId))
      return { newsId, viewerId, result }
    },
    onMutate: async ({ newsId, viewerId }) => {
      await queryClient.cancelQueries({ queryKey: privateNewsKeys.blockStatus(viewerId, newsId), exact: true })
    },
    onSuccess: async ({ newsId, viewerId }) => {
      const blockStatusKey = privateNewsKeys.blockStatus(viewerId, newsId)
      await queryClient.cancelQueries({ queryKey: blockStatusKey, exact: true })
      queryClient.setQueryData<BlockStatus>(blockStatusKey, { is_blocked: false })
      queryClient.setQueriesData({ queryKey: privateNewsKeys.blocked(viewerId) }, (current) => {
        if (!current || typeof current !== 'object' || !('results' in current) || !Array.isArray(current.results)) return current
        return {
          ...current,
          results: current.results.filter((entry) =>
            typeof entry !== 'object'
            || entry === null
            || !('news' in entry)
            || typeof entry.news !== 'object'
            || entry.news === null
            || !('id' in entry.news)
            || entry.news.id !== newsId),
        }
      })
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: blockStatusKey, exact: true }),
        queryClient.invalidateQueries({ queryKey: newsKeys.viewerLists(viewerId) }),
        queryClient.invalidateQueries({ queryKey: privateNewsKeys.blocked(viewerId) }),
      ]).catch(() => undefined)
    },
  })
}
