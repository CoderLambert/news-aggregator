import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { newsKeys } from '@/services/newsQueries'
import { fetchNews } from '@/services/api'
import { parseNewsSummary, parsePage } from '@/types/news'
import type { Language, NewsListParams, NewsSummary, Page } from '@/types/news'

// Observe a separate first-page query so background checks never move the
// reader's list. Reuse the same viewer, filters, parser and abortable transport.
export function useNewsUpdates(params: NewsListParams, lang: Language, viewerId: number | string,
  sourceIds: number[] | null | undefined, visible: Page<NewsSummary> | undefined,
  visibleUpdatedAt: number, enabled: boolean) {
  const canCheck = enabled && Boolean(visible) && !params.search
  const latest = useQuery({
    queryKey: [...newsKeys.list({ ...params, page: 1 }, lang, viewerId, sourceIds), 'updates'],
    queryFn: async ({ signal }) => parsePage(await fetchNews({ ...params, page: 1 }, signal), parseNewsSummary),
    enabled: canCheck,
    initialData: params.page === 1 ? visible : undefined,
    initialDataUpdatedAt: params.page === 1 ? visibleUpdatedAt : undefined,
    staleTime: 30_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: 'always',
    retry: false,
  })
  const { refetch } = latest
  useEffect(() => {
    if (!canCheck) return
    const check = () => { if (!document.hidden) void refetch() }
    window.addEventListener('focus', check)
    return () => window.removeEventListener('focus', check)
  }, [canCheck, refetch])

  const hasNewArticles = canCheck && !latest.isError && latest.data && visible
    && latest.dataUpdatedAt > visibleUpdatedAt
    && (latest.data.count > visible.count || (params.page === 1
      && latest.data.results.some(item => !visible.results.some(previous => previous.id === item.id))))
  return Boolean(hasNewArticles)
}
