import {
  createResearchStream as createResearchStreamRequest,
  deleteResearchSession as deleteResearchSessionRequest,
  getResearchResults as getResearchResultsRequest,
  getResearchSession as getResearchSessionRequest,
  listResearchSessions as listResearchSessionsRequest,
  openResearchSessionStream as openResearchSessionStreamRequest,
  researchChatStream as researchChatStreamRequest,
} from './api'
import { isRecord } from '@/types/news'
import {
  parseResearchEvent,
  parseResearchSearchResults,
  parseResearchSessionDetail,
  parseResearchSessions,
} from '@/types/research'
import type { ResearchEvent, ResearchSearchResult, ResearchSessionDetail, ResearchSessionSummary } from '@/types/research'
import type { Page } from '@/types/news'

export type ResearchSessionStream =
  | { kind: 'session'; session: ResearchSessionDetail }
  | { kind: 'events'; events: AsyncIterable<ResearchEvent> }

function isAsyncIterable(value: unknown): value is AsyncIterable<unknown> {
  return typeof value === 'object'
    && value !== null
    && Symbol.asyncIterator in value
    && typeof value[Symbol.asyncIterator] === 'function'
}

async function* typedResearchEvents(source: AsyncIterable<unknown>): AsyncGenerator<ResearchEvent> {
  for await (const value of source) {
    const event = parseResearchEvent(value)
    if (event) yield event
  }
}

export async function listResearchSessions(signal?: AbortSignal): Promise<Page<ResearchSessionSummary>> {
  const response: unknown = await listResearchSessionsRequest({}, signal)
  return parseResearchSessions(response)
}

export async function getResearchSession(sessionId: string, signal?: AbortSignal): Promise<ResearchSessionDetail> {
  const response: unknown = await getResearchSessionRequest(sessionId, signal)
  return parseResearchSessionDetail(response)
}

export async function getResearchResults(sessionId: string, signal?: AbortSignal): Promise<Page<ResearchSearchResult>> {
  const response: unknown = await getResearchResultsRequest(sessionId, { detail: '1' }, signal)
  return parseResearchSearchResults(response)
}

export async function deleteResearchSession(sessionId: string): Promise<void> {
  await deleteResearchSessionRequest(sessionId)
}

export function createResearchStream(
  query: string,
  options: { localOnly: boolean; signal: AbortSignal },
): AsyncGenerator<ResearchEvent> {
  const source = createResearchStreamRequest(query, options) as AsyncIterable<unknown>
  return typedResearchEvents(source)
}

export function researchChatStream(
  sessionId: string,
  query: string,
  options: { localOnly: boolean; signal: AbortSignal },
): AsyncGenerator<ResearchEvent> {
  const source = researchChatStreamRequest(sessionId, query, options) as AsyncIterable<unknown>
  return typedResearchEvents(source)
}

export async function openResearchSessionStream(sessionId: string, signal: AbortSignal): Promise<ResearchSessionStream> {
  const response: unknown = await openResearchSessionStreamRequest(sessionId, { signal })
  if (!isRecord(response)) throw new TypeError('Invalid research stream response')

  if (response.kind === 'session') {
    return { kind: 'session', session: parseResearchSessionDetail(response.data) }
  }
  if (response.kind === 'stream' && isRecord(response) && isAsyncIterable(response.events)) {
    return { kind: 'events', events: typedResearchEvents(response.events) }
  }
  throw new TypeError('Invalid research stream response')
}
