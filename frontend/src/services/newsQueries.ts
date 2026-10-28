import { queryOptions, type QueryClient } from '@tanstack/react-query'
import { fetchCategories, fetchNews, fetchNewsDetail, fetchSources } from '@/services/api'
import { isRecord, parseFilterOptions, parsePage, parseNewsDetail, parseNewsSummary } from '@/types/news'
import type { FilterOption, Language, NewsDetail, NewsListParams, Page, NewsSummary } from '@/types/news'

export const newsKeys = {
  all: ['news'] as const,
  lists: () => [...newsKeys.all, 'list'] as const,
  viewerLists: (viewerId: number | string) => [...newsKeys.lists(), { viewerId }] as const,
  list: (params: NewsListParams, lang: Language, viewerId: number | string, scopeSources?: number[] | null) =>
    [...newsKeys.lists(), { ...params, lang, viewerId, scopeSources }] as const,
  details: () => [...newsKeys.all, 'detail'] as const,
  viewerDetails: (viewerId: number | string) => [...newsKeys.details(), { viewerId }] as const,
  detail: (id: number, lang: Language, viewerId: number | string) =>
    [...newsKeys.details(), { id, lang, viewerId }] as const,
  categories: (lang: Language) => [...newsKeys.all, 'categories', lang] as const,
  sources: (lang: Language, viewerId: number | string, purpose: 'subscribe' | 'history' = 'history') =>
    [...newsKeys.all, 'sources', { lang, viewerId, purpose }] as const,
}

export const newsListOptions = (params: NewsListParams, lang: Language, viewerId: number | string, scopeSources?: number[] | null) =>
  queryOptions({
    queryKey: newsKeys.list(params, lang, viewerId, scopeSources),
    queryFn: async ({ signal }): Promise<Page<NewsSummary>> =>
      parsePage(await fetchNews(params, signal), parseNewsSummary),
  })

export const newsDetailOptions = (id: number, lang: Language, viewerId: number | string) =>
  queryOptions({
    queryKey: newsKeys.detail(id, lang, viewerId),
    queryFn: async ({ signal }): Promise<NewsDetail> => parseNewsDetail(await fetchNewsDetail(id, signal)),
    staleTime: 15_000,
  })

const DETAIL_PREFETCH_DELAY_MS = 180

interface ScheduledDetailPrefetch {
  timer: ReturnType<typeof setTimeout> | null
  id: number
  lang: Language
  viewerId: number | string
}

let scheduledDetailPrefetch: ScheduledDetailPrefetch | null = null

function detailQueryHasObserver(queryClient: QueryClient, id: number, lang: Language, viewerId: number | string) {
  const query = queryClient.getQueryCache().find({ queryKey: newsKeys.detail(id, lang, viewerId), exact: true })
  return (query?.getObserversCount() ?? 0) > 0
}

function cancelPrefetchRequest(queryClient: QueryClient, scheduled: ScheduledDetailPrefetch) {
  if (detailQueryHasObserver(queryClient, scheduled.id, scheduled.lang, scheduled.viewerId)) return
  void queryClient.cancelQueries({ queryKey: newsKeys.detail(scheduled.id, scheduled.lang, scheduled.viewerId), exact: true })
}

function sameCard(scheduled: ScheduledDetailPrefetch, id: number, lang: Language, viewerId: number | string) {
  return scheduled.id === id && scheduled.lang === lang && scheduled.viewerId === viewerId
}

/** Drop a hover/focus prefetch that has not started. A started read stays until another card replaces it. */
export function cancelScheduledNewsDetailPrefetch(_queryClient: QueryClient, id: number, lang: Language, viewerId: number | string) {
  const scheduled = scheduledDetailPrefetch
  if (!scheduled || !sameCard(scheduled, id, lang, viewerId) || !scheduled.timer) return
  clearTimeout(scheduled.timer)
  scheduledDetailPrefetch = null
}

export function resetScheduledNewsDetailPrefetch() {
  if (scheduledDetailPrefetch?.timer) clearTimeout(scheduledDetailPrefetch.timer)
  scheduledDetailPrefetch = null
}

/**
 * Prefetch at most one article detail. Sliding across the feed replaces the
 * previous card instead of issuing a request per row.
 */
export function scheduleNewsDetailPrefetch(queryClient: QueryClient, id: number, lang: Language, viewerId: number | string) {
  const current = scheduledDetailPrefetch
  if (current && sameCard(current, id, lang, viewerId)) return
  if (current) {
    if (current.timer) clearTimeout(current.timer)
    scheduledDetailPrefetch = null
    cancelPrefetchRequest(queryClient, current)
  }
  const key = newsKeys.detail(id, lang, viewerId)
  const existing = queryClient.getQueryState(key)
  if (existing?.status === 'success' && Date.now() - existing.dataUpdatedAt < 15_000) return
  const scheduled: ScheduledDetailPrefetch = { id, lang, viewerId, timer: null }
  scheduled.timer = setTimeout(() => {
    if (scheduledDetailPrefetch !== scheduled) return
    scheduled.timer = null
    void queryClient.prefetchQuery(newsDetailOptions(id, lang, viewerId)).catch(() => undefined)
  }, DETAIL_PREFETCH_DELAY_MS)
  scheduledDetailPrefetch = scheduled
}

export const newsListPlaceholderData = (viewerId: number | string, lang: Language, scope = 'all', groupId?: number, region = 'all') =>
  (previousData: Page<NewsSummary> | undefined, previousQuery?: { queryKey: readonly unknown[] }) => {
    const previousScope = previousQuery?.queryKey[2]
    return isRecord(previousScope) && previousScope.viewerId === viewerId && previousScope.lang === lang
      && (previousScope.scope ?? 'all') === scope && previousScope.group_id === groupId && (previousScope.region ?? 'all') === region
      ? previousData
      : undefined
  }

export const categoryOptions = (lang: Language) =>
  queryOptions({
    queryKey: newsKeys.categories(lang),
    queryFn: async ({ signal }): Promise<FilterOption[]> => parseFilterOptions(await fetchCategories(signal)),
  })

export const sourceOptions = (lang: Language, viewerId: number | string, purpose: 'subscribe' | 'history' = 'history') =>
  queryOptions({
    queryKey: newsKeys.sources(lang, viewerId, purpose),
    queryFn: async ({ signal }): Promise<FilterOption[]> => parseFilterOptions(await fetchSources(signal, purpose)),
  })
