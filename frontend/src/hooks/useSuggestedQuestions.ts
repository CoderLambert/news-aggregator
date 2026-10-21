import { useCallback, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { fetchSuggestedQuestions, type SuggestedQuestionsSnapshot } from '@/services/newsWorkflowApi'
import { listAITaskPreferences } from '@/services/aiConnectionsApi'
import { newsWorkflowKeys, parseNewsId } from '@/services/newsWorkflowQueries'

const EMPTY_SUGGESTIONS: SuggestedQuestionsSnapshot = {
  questions: [], contextScope: 'summary', revision: null, generated: false,
}

export function useSuggestedQuestions(newsId: string | number | null | undefined, enabled: boolean, contentRevision = 0) {
  const queryClient = useQueryClient()
  const { user, loading: authLoading } = useAuth()
  const viewerId = user?.id ?? 'anonymous'
  const revision = Number.isSafeInteger(contentRevision) && contentRevision >= 0 ? contentRevision : 0
  const { lang } = useLanguage()
  const preferences = useQuery({
    queryKey: ['ai-task-preferences', viewerId],
    queryFn: ({ signal }) => listAITaskPreferences(signal),
    enabled: enabled && Boolean(user) && !authLoading,
    retry: false,
  })
  const task = preferences.data?.preferences.find(item => item.task_kind === 'question_suggestions')
  const selected = task?.selection_state === 'available' ? task
    : task?.selection_state === 'inherit_default'
      ? preferences.data?.preferences.find(item => item.task_kind === 'default' && item.selection_state === 'available') : null
  const modelConfigId = selected?.model_config_id ?? undefined
  const modelLabel = selected?.model ? selected.model.display_name === selected.model.model_id ? selected.model.display_name : `${selected.model.display_name} (${selected.model.model_id})` : null
  const parsedId = parseNewsId(newsId)
  const queryKey = parsedId === null
    ? ['newsWorkflow', 'suggestedQuestions', 'disabled'] as const
    : [...newsWorkflowKeys.suggestedQuestions(parsedId, lang, viewerId, revision), modelConfigId ?? null, preferences.data?.revision ?? null]
  const query = useQuery<SuggestedQuestionsSnapshot>({
    queryKey,
    queryFn: ({ signal }) => parsedId === null
      ? Promise.resolve(EMPTY_SUGGESTIONS)
      : fetchSuggestedQuestions(parsedId, { signal, ...(modelConfigId ? { modelConfigId } : {}) }),
    enabled: (currentQuery) => enabled && !authLoading && (!user || !preferences.isPending) && parsedId !== null && currentQuery.state.status !== 'error',
    staleTime: Infinity,
    retry: false,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  const refreshLock = useRef(false)

  const refresh = useCallback(async (consent?: boolean) => {
    if (parsedId === null || authLoading || refreshLock.current || query.isFetching || (modelConfigId && consent !== true)) return false
    refreshLock.current = true
    try {
      await queryClient.fetchQuery({
        queryKey,
        queryFn: ({ signal }) => fetchSuggestedQuestions(parsedId, { force: true, signal, ...(modelConfigId ? { modelConfigId } : {}), ...(consent === true ? { consent: true } : {}) }),
        staleTime: 0,
      })
      return true
    } catch {
      // TanStack Query keeps the prior successful data when a forced refresh fails.
      return false
    } finally {
      refreshLock.current = false
    }
  }, [authLoading, parsedId, queryClient, query.isFetching, queryKey, modelConfigId])

  return {
    questions: query.data?.questions ?? [],
    contextScope: query.data?.contextScope,
    generated: query.data?.generated,
    modelConfigId, modelLabel, modelSource: query.data?.modelSource,
    loading: query.isFetching || (enabled && Boolean(user) && preferences.isPending),
    error: query.error,
    refresh,
  }
}
