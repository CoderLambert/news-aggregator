import { queryOptions } from '@tanstack/react-query'
import { fetchChatHistory, fetchSuggestedQuestions, type NewsId } from '@/services/newsWorkflowApi'
import type { Language } from '@/types/news'

export type ViewerId = number | 'anonymous'

export const newsWorkflowKeys = {
  all: ['newsWorkflow'] as const,
  chatHistories: () => [...newsWorkflowKeys.all, 'chatHistory'] as const,
  chatHistory: (newsId: number, lang: Language, viewerId: ViewerId) =>
    [...newsWorkflowKeys.all, 'chatHistory', { newsId, lang, viewerId }] as const,
  suggestedQuestions: (newsId: number, lang: Language) =>
    [...newsWorkflowKeys.all, 'suggestedQuestions', { newsId, lang }] as const,
}

export function chatHistoryOptions(newsId: number, lang: Language, viewerId: ViewerId) {
  return queryOptions({
    queryKey: newsWorkflowKeys.chatHistory(newsId, lang, viewerId),
    queryFn: ({ signal }) => fetchChatHistory(newsId, signal),
    staleTime: 30_000,
    retry: false,
  })
}

export function suggestedQuestionOptions(newsId: number, lang: Language) {
  return queryOptions({
    queryKey: newsWorkflowKeys.suggestedQuestions(newsId, lang),
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
