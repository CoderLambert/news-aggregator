import { queryOptions } from '@tanstack/react-query'
import { fetchChatHistory, fetchSuggestedQuestions, type NewsId } from '@/services/newsWorkflowApi'
import type { ChatTranslationMode } from '@/services/api'
import type { Language } from '@/types/news'

export type ViewerId = number | 'anonymous'

export const newsWorkflowKeys = {
  all: ['newsWorkflow'] as const,
  chatHistories: () => [...newsWorkflowKeys.all, 'chatHistory'] as const,
  chatHistory: (newsId: number, lang: Language, viewerId: ViewerId,
    translationResultId: number | null = null, translationMode: ChatTranslationMode = 'current') =>
    [...newsWorkflowKeys.all, 'chatHistory', { newsId, lang, viewerId, translationResultId, translationMode }] as const,
  suggestedQuestions: (newsId: number, lang: Language, viewerId: ViewerId, revision: number) =>
    [...newsWorkflowKeys.all, 'suggestedQuestions', { newsId, lang, viewerId, revision }] as const,
}

export function chatHistoryOptions(newsId: number, lang: Language, viewerId: ViewerId,
  translationResultId: number | null = null, translationMode: ChatTranslationMode = 'current') {
  return queryOptions({
    queryKey: newsWorkflowKeys.chatHistory(newsId, lang, viewerId, translationResultId, translationMode),
    queryFn: ({ signal }) => fetchChatHistory(newsId, signal, { translationResultId, translationMode }),
    staleTime: 30_000,
    retry: false,
  })
}

export function suggestedQuestionOptions(newsId: number, lang: Language, viewerId: ViewerId, revision: number) {
  return queryOptions({
    queryKey: newsWorkflowKeys.suggestedQuestions(newsId, lang, viewerId, revision),
    queryFn: ({ signal }) => fetchSuggestedQuestions(newsId, { signal }),
    staleTime: Infinity,
    retry: false,
  })
}

export function parseNewsId(id: NewsId | null | undefined): number | null {
  if (id === null || id === undefined || id === '') return null
  const parsed = Number(id)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}
