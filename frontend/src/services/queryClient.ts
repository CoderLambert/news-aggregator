import { QueryClient } from '@tanstack/react-query'
import axios from 'axios'

export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (axios.isAxiosError(error) && error.response && error.response.status < 500) return false
  return failureCount < 1
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetryQuery,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
    mutations: { retry: false },
  },
})
