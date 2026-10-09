import { queryOptions } from '@tanstack/react-query'
import { fetchCategories, fetchNews, fetchNewsDetail, fetchSources } from '@/services/api'
import { isRecord, parseFilterOptions, parsePage, parseNewsDetail, parseNewsSummary } from '@/types/news'
import type { FilterOption, Language, NewsDetail, NewsListParams, Page, NewsSummary } from '@/types/news'

export const newsKeys = {
  all: ['news'] as const,
  lists: () => [...newsKeys.all, 'list'] as const,
  viewerLists: (viewerId: number | string) => [...newsKeys.lists(), { viewerId }] as const,
  list: (params: NewsListParams, lang: Language, viewerId: number | string) =>
    [...newsKeys.lists(), { ...params, lang, viewerId }] as const,
  details: () => [...newsKeys.all, 'detail'] as const,
  viewerDetails: (viewerId: number | string) => [...newsKeys.details(), { viewerId }] as const,
  detail: (id: number, lang: Language, viewerId: number | string) =>
    [...newsKeys.details(), { id, lang, viewerId }] as const,
  categories: (lang: Language) => [...newsKeys.all, 'categories', lang] as const,
  sources: (lang: Language) => [...newsKeys.all, 'sources', lang] as const,
}

export const newsListOptions = (params: NewsListParams, lang: Language, viewerId: number | string) =>
  queryOptions({
    queryKey: newsKeys.list(params, lang, viewerId),
    queryFn: async ({ signal }): Promise<Page<NewsSummary>> =>
      parsePage(await fetchNews(params, signal), parseNewsSummary),
  })

export const newsDetailOptions = (id: number, lang: Language, viewerId: number | string) =>
  queryOptions({
    queryKey: newsKeys.detail(id, lang, viewerId),
    queryFn: async ({ signal }): Promise<NewsDetail> => parseNewsDetail(await fetchNewsDetail(id, signal)),
    staleTime: 15_000,
  })

export const newsListPlaceholderData = (viewerId: number | string, lang: Language) =>
  (previousData: Page<NewsSummary> | undefined, previousQuery?: { queryKey: readonly unknown[] }) => {
    const previousScope = previousQuery?.queryKey[2]
    return isRecord(previousScope) && previousScope.viewerId === viewerId && previousScope.lang === lang
      ? previousData
      : undefined
  }

export const categoryOptions = (lang: Language) =>
  queryOptions({
    queryKey: newsKeys.categories(lang),
    queryFn: async ({ signal }): Promise<FilterOption[]> => parseFilterOptions(await fetchCategories(signal)),
  })

export const sourceOptions = (lang: Language) =>
  queryOptions({
    queryKey: newsKeys.sources(lang),
    queryFn: async ({ signal }): Promise<FilterOption[]> => parseFilterOptions(await fetchSources(signal)),
  })
