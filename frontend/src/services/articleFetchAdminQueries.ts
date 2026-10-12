import { queryOptions } from '@tanstack/react-query'
import { fetchArticleFetchDashboard } from '@/services/articleFetchAdminApi'

export const articleFetchAdminKeys = {
  all: ['articleFetchAdmin'] as const,
  dashboard: () => [...articleFetchAdminKeys.all, 'dashboard'] as const,
}

export const articleFetchDashboardOptions = () => queryOptions({
  queryKey: articleFetchAdminKeys.dashboard(),
  queryFn: ({ signal }) => fetchArticleFetchDashboard(signal),
  refetchInterval: () => typeof document !== 'undefined' && document.hidden ? false : 10_000,
})
