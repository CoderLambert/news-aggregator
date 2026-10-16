import { queryOptions } from '@tanstack/react-query'
import { fetchSearchIndexDashboard } from '@/services/searchIndexAdminApi'

export const searchIndexAdminKeys = {
  all: ['searchIndexAdmin'] as const,
  dashboard: () => [...searchIndexAdminKeys.all, 'dashboard'] as const,
}

export const searchIndexDashboardOptions = () => queryOptions({
  queryKey: searchIndexAdminKeys.dashboard(),
  queryFn: ({ signal }) => fetchSearchIndexDashboard(signal),
  staleTime: 60_000,
  refetchInterval: () => typeof document !== 'undefined' && document.hidden ? false : 60_000,
})
