import { queryOptions } from '@tanstack/react-query'
import { getResearchResults, getResearchSession, listResearchSessions } from '@/services/researchApi'
import type { Language } from '@/types/news'

export type ResearchViewerId = number | string

export const researchKeys = {
  all: ['private', 'research'] as const,
  sessions: (viewerId: ResearchViewerId, lang: Language) =>
    [...researchKeys.all, 'sessions', { viewerId, lang }] as const,
  session: (viewerId: ResearchViewerId, lang: Language, sessionId: string) =>
    [...researchKeys.all, 'session', { viewerId, lang, sessionId }] as const,
  results: (viewerId: ResearchViewerId, lang: Language, sessionId: string) =>
    [...researchKeys.all, 'results', { viewerId, lang, sessionId }] as const,
}

export const researchSessionsOptions = (viewerId: ResearchViewerId, lang: Language) =>
  queryOptions({
    queryKey: researchKeys.sessions(viewerId, lang),
    queryFn: ({ signal }) => listResearchSessions(signal),
  })

export const researchSessionOptions = (
  viewerId: ResearchViewerId,
  lang: Language,
  sessionId: string,
) => queryOptions({
  queryKey: researchKeys.session(viewerId, lang, sessionId),
  queryFn: ({ signal }) => getResearchSession(sessionId, signal),
})

export const researchResultsOptions = (
  viewerId: ResearchViewerId,
  lang: Language,
  sessionId: string,
) => queryOptions({
  queryKey: researchKeys.results(viewerId, lang, sessionId),
  queryFn: ({ signal }) => getResearchResults(sessionId, signal),
})
