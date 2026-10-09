import { queryOptions } from '@tanstack/react-query'
import { fetchCrawlerDashboard } from '@/services/crawlerAdminApi'

export const crawlerAdminKeys = {
  all: ['crawlerAdmin'] as const,
  dashboard: () => [...crawlerAdminKeys.all, 'dashboard'] as const,
}

export const crawlerDashboardOptions = () => queryOptions({
  queryKey: crawlerAdminKeys.dashboard(),
  queryFn: ({ signal }) => fetchCrawlerDashboard(signal),
  refetchInterval: () => typeof document !== 'undefined' && document.hidden ? false : 5_000,
})
