import { useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { newsDetailOptions, newsKeys } from '@/services/newsQueries'
import type { NewsDetail } from '@/types/news'
import type { SetStateAction } from 'react'

export function useNewsDetail(id: string | undefined) {
  const { lang } = useLanguage()
  const { user, loading: authLoading } = useAuth()
  const queryClient = useQueryClient()
  const parsedId = Number(id)
  const validId = Number.isSafeInteger(parsedId) && parsedId > 0
  const newsId = validId ? parsedId : -1
  const viewerId = user?.id ?? 'anonymous'
  const queryKey = newsKeys.detail(newsId, lang, viewerId)
  const query = useQuery({
    ...newsDetailOptions(newsId, lang, viewerId),
    enabled: !authLoading && validId,
  })

  const setNews = useCallback((action: SetStateAction<NewsDetail | null>) => {
    if (!validId) return

    const applyUpdate = () => queryClient.setQueryData<NewsDetail>(queryKey, (current) => {
      if (!current) return current
      const next = typeof action === 'function' ? action(current) : action
      return next ?? undefined
    })

    if (queryClient.getQueryState(queryKey)?.fetchStatus === 'fetching') {
      void queryClient.cancelQueries({ queryKey, exact: true }).then(applyUpdate)
      return
    }
    applyUpdate()
  }, [queryClient, queryKey, validId])

  return {
    news: query.data ?? null,
    setNews,
    loading: authLoading || (validId && query.isPending),
    error: query.error ?? (validId ? null : new Error('Invalid news identifier')),
    refetch: query.refetch,
  }
}
