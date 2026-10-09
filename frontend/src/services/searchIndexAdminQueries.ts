import { queryOptions } from '@tanstack/react-query'
import { fetchSearchIndexDashboard } from '@/services/searchIndexAdminApi'

export const searchIndexAdminKeys = {
  all: ['searchIndexAdmin'] as const,
  dashboard: () => [...searchIndexAdminKeys.all, 'dashboard'] as const,
}

export const searchIndexDashboardOptions = () => queryOptions({
  queryKey: searchIndexAdminKeys.dashboard(),
  queryFn: ({ signal }) => fetchSearchIndexDashboard(signal),
  refetchInterval: () => typeof document !== 'undefined' && document.hidden ? false : 15_000,
})
