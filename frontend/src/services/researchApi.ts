import {
  cancelResearchRun as cancelResearchRunRequest,
  createResearchStream as createResearchStreamRequest,
  deleteResearchSession as deleteResearchSessionRequest,
  getResearchResults as getResearchResultsRequest,
  getResearchSession as getResearchSessionRequest,
  listResearchSessions as listResearchSessionsRequest,
  openResearchSessionStream as openResearchSessionStreamRequest,
  researchChatStream as researchChatStreamRequest,
  resumeQueuedResearchRun as resumeQueuedResearchRunRequest,
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
  | { kind: 'queued'; runId: string | null }
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
  options: {
    localOnly: boolean
    idempotencyKey: string
    signal: AbortSignal
    onSessionId?: (sessionId: string) => void
    onRunId?: (runId: string) => void
  },
): AsyncGenerator<ResearchEvent> {
  const source = createResearchStreamRequest(query, options) as AsyncIterable<unknown>
  return typedResearchEvents(source)
}

export function researchChatStream(
  sessionId: string,
  query: string,
  options: {
    localOnly: boolean
    idempotencyKey: string
    signal: AbortSignal
    onRunId?: (runId: string) => void
  },
): AsyncGenerator<ResearchEvent> {
  const source = researchChatStreamRequest(sessionId, query, options) as AsyncIterable<unknown>
  return typedResearchEvents(source)
}

export async function openResearchSessionStream(
  sessionId: string,
  signal: AbortSignal,
  onRunId?: (runId: string) => void,
  waitForQueued = false,
): Promise<ResearchSessionStream> {
  const response: unknown = await openResearchSessionStreamRequest(
    sessionId, { signal, onRunId, waitForQueued },
  )
  if (!isRecord(response)) throw new TypeError('Invalid research stream response')
  if (response.kind === 'session') {
    return { kind: 'session', session: parseResearchSessionDetail(response.data) }
  }
  if (response.kind === 'queued' && (typeof response.runId === 'string' || response.runId === null)) {
    return { kind: 'queued', runId: response.runId }
  }
  if (response.kind === 'stream' && isRecord(response) && isAsyncIterable(response.events)) {
    return { kind: 'events', events: typedResearchEvents(response.events) }
  }
  throw new TypeError('Invalid research stream response')
}

export async function cancelResearchRun(sessionId: string, runId: string): Promise<unknown> {
  return cancelResearchRunRequest(sessionId, runId)
}

export async function resumeQueuedResearchRun(sessionId: string, runId: string): Promise<void> {
  const response: unknown = await resumeQueuedResearchRunRequest(sessionId, runId)
  if (!isRecord(response) || response.run_id !== runId ||
      (response.status !== 'queued' && response.status !== 'running' && response.status !== 'succeeded')) {
    throw new TypeError('Invalid queued research recovery result')
  }
}
