import { queryOptions } from '@tanstack/react-query'
import { fetchCategories, fetchNews, fetchSources } from '@/services/api'
import { parseFilterOptions, parsePage, parseNewsSummary } from '@/types/news'
import type { FilterOption, Language, NewsListParams, Page, NewsSummary } from '@/types/news'

export const newsKeys = {
  all: ['news'] as const,
  lists: () => [...newsKeys.all, 'list'] as const,
  list: (params: NewsListParams, lang: Language, viewerId: number | string) =>
    [...newsKeys.lists(), { ...params, lang, viewerId }] as const,
  categories: (lang: Language) => [...newsKeys.all, 'categories', lang] as const,
  sources: (lang: Language) => [...newsKeys.all, 'sources', lang] as const,
}

export const newsListOptions = (params: NewsListParams, lang: Language, viewerId: number | string) =>
  queryOptions({
    queryKey: newsKeys.list(params, lang, viewerId),
    queryFn: async ({ signal }): Promise<Page<NewsSummary>> =>
      parsePage(await fetchNews(params, signal), parseNewsSummary),
  })

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
