import { useCallback, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { fetchSuggestedQuestions } from '@/services/newsWorkflowApi'
import { newsWorkflowKeys, parseNewsId, suggestedQuestionOptions } from '@/services/newsWorkflowQueries'

export function useSuggestedQuestions(newsId: string | number | null | undefined, enabled: boolean) {
  const queryClient = useQueryClient()
  const { loading: authLoading } = useAuth()
  const { lang } = useLanguage()
  const parsedId = parseNewsId(newsId)
  const queryKey = parsedId === null
    ? ['newsWorkflow', 'suggestedQuestions', 'disabled'] as const
    : newsWorkflowKeys.suggestedQuestions(parsedId, lang)
  const query = useQuery<string[]>({
    queryKey,
    queryFn: ({ signal }) => parsedId === null
      ? Promise.resolve([])
      : fetchSuggestedQuestions(parsedId, { signal }),
    enabled: (currentQuery) => enabled && !authLoading && parsedId !== null && currentQuery.state.status !== 'error',
    staleTime: Infinity,
    retry: false,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  const refreshLock = useRef(false)

  const refresh = useCallback(async () => {
    if (parsedId === null || authLoading || refreshLock.current || query.isFetching) return false
    refreshLock.current = true
    try {
      await queryClient.fetchQuery({
        ...suggestedQuestionOptions(parsedId, lang),
        queryFn: ({ signal }) => fetchSuggestedQuestions(parsedId, { force: true, signal }),
        staleTime: 0,
      })
      return true
    } catch {
      // TanStack Query keeps the prior successful data when a forced refresh fails.
      return false
    } finally {
      refreshLock.current = false
    }
  }, [authLoading, lang, parsedId, queryClient, query.isFetching])

  return {
    questions: query.data ?? [],
    loading: query.isFetching,
    error: query.error,
    refresh,
  }
}
