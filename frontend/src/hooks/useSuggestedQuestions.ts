import { useCallback, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { fetchSuggestedQuestions, type SuggestedQuestionsSnapshot } from '@/services/newsWorkflowApi'
import { newsWorkflowKeys, parseNewsId, suggestedQuestionOptions } from '@/services/newsWorkflowQueries'

const EMPTY_SUGGESTIONS: SuggestedQuestionsSnapshot = {
  questions: [], contextScope: 'summary', revision: null, generated: false,
}

export function useSuggestedQuestions(newsId: string | number | null | undefined, enabled: boolean, contentRevision = 0) {
  const queryClient = useQueryClient()
  const { user, loading: authLoading } = useAuth()
  const viewerId = user?.id ?? 'anonymous'
  const revision = Number.isSafeInteger(contentRevision) && contentRevision >= 0 ? contentRevision : 0
  const { lang } = useLanguage()
  const parsedId = parseNewsId(newsId)
  const queryKey = parsedId === null
    ? ['newsWorkflow', 'suggestedQuestions', 'disabled'] as const
    : newsWorkflowKeys.suggestedQuestions(parsedId, lang, viewerId, revision)
  const query = useQuery<SuggestedQuestionsSnapshot>({
    queryKey,
    queryFn: ({ signal }) => parsedId === null
      ? Promise.resolve(EMPTY_SUGGESTIONS)
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
        ...suggestedQuestionOptions(parsedId, lang, viewerId, revision),
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
  }, [authLoading, lang, parsedId, queryClient, query.isFetching, viewerId, revision])

  return {
    questions: query.data?.questions ?? [],
    contextScope: query.data?.contextScope,
    generated: query.data?.generated,
    loading: query.isFetching,
    error: query.error,
    refresh,
  }
}
