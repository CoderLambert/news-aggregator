import { queryOptions } from '@tanstack/react-query'
import { fetchCrawlerDashboard, fetchRecentCrawlBatches } from '@/services/crawlerAdminApi'

export const crawlerAdminKeys = {
  all: ['crawlerAdmin'] as const,
  dashboard: () => [...crawlerAdminKeys.all, 'dashboard'] as const,
}

export const crawlerDashboardOptions = () => queryOptions({
  queryKey: crawlerAdminKeys.dashboard(),
  queryFn: ({ signal }) => fetchCrawlerDashboard(signal),
  refetchInterval: () => typeof document !== 'undefined' && document.hidden ? false : 5_000,
})

export const crawlerHistoryOptions = () => queryOptions({
  queryKey: [...crawlerAdminKeys.all, 'history'],
  queryFn: ({ signal }) => fetchRecentCrawlBatches(signal),
  staleTime: 15_000,
  refetchInterval: () => typeof document !== 'undefined' && document.hidden ? false : 15_000,
})
