import { isRecord, parsePage } from './news'

export type ResearchPhase = 'idle' | 'thinking' | 'tool_calling' | 'streaming' | 'success' | 'error' | 'cancelled'
export type ResearchActivePhase = Exclude<ResearchPhase, 'idle'>
export type ResearchId = string | number
export type JsonRecord = Record<string, unknown>

export interface ResearchArticle {
  id?: ResearchId
  title?: string
  source?: string
  source_type?: string
  publish_time?: string
  snippet?: string
  url?: string
}

export interface ResearchWebResult {
  title?: string
  source?: string
  snippet?: string
  url?: string
}

export interface ResearchToolCall {
  callId: string
  name: string
  args: JsonRecord
  summary: string
  status: 'running' | 'done'
  articles: ResearchArticle[]
  webResults: ResearchWebResult[]
  articleTitle: string
  articleId: ResearchId | null
  articleSource: string
  articleUrl: string
  contentTruncated: boolean
  originalLength: number
  contentLength: number
}

export interface ResearchMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolCalls?: ResearchToolCall[]
}

export interface ResearchSessionSummary {
  id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface StoredResearchToolCall {
  id: string
  function: { name: string; arguments: string }
}

export interface StoredResearchMessage {
  role: string
  content: string
  tool_calls?: StoredResearchToolCall[]
  tool_call_id?: string
}

export interface ResearchSessionDetail extends ResearchSessionSummary {
  messages: StoredResearchMessage[]
}

export interface ResearchSearchResult {
  id: number
  tool_name: string
  query: string
  result_type: string
  source: string
  title: string
  url: string
  hit_count: number
  result_data: JsonRecord
  created_at: string
}

export type ResearchEvent =
  | { type: 'session_created'; session_id: string }
  | { type: 'thinking'; iteration?: number }
  | { type: 'query_decomposed' }
  | { type: 'tool_call'; call_id: string; name: string; args: JsonRecord }
  | {
      type: 'tool_result'
      call_id: string
      summary: string
      articles: ResearchArticle[]
      results: ResearchWebResult[]
      title: string
      id: ResearchId | null
      source: string
      url: string
      content_truncated: boolean
      original_length: number
      length: number
    }
  | { type: 'text_delta'; text: string }
  | { type: 'complete' }
  | { type: 'error'; message: string }

function optionalString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function optionalNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function optionalId(value: unknown): ResearchId | null {
  return typeof value === 'string' || typeof value === 'number' ? value : null
}

function parseArticle(value: unknown): ResearchArticle | null {
  if (!isRecord(value)) return null
  const id = optionalId(value.id)
  return {
    ...(id !== null ? { id } : {}),
    ...(typeof value.title === 'string' ? { title: value.title } : {}),
    ...(typeof value.source === 'string' ? { source: value.source } : {}),
    ...(typeof value.source_type === 'string' ? { source_type: value.source_type } : {}),
    ...(typeof value.publish_time === 'string' ? { publish_time: value.publish_time } : {}),
    ...(typeof value.snippet === 'string' ? { snippet: value.snippet } : {}),
    ...(typeof value.url === 'string' ? { url: value.url } : {}),
  }
}

function parseWebResult(value: unknown): ResearchWebResult | null {
  if (!isRecord(value)) return null
  return {
    ...(typeof value.title === 'string' ? { title: value.title } : {}),
    ...(typeof value.source === 'string' ? { source: value.source } : {}),
    ...(typeof value.snippet === 'string' ? { snippet: value.snippet } : {}),
    ...(typeof value.url === 'string' ? { url: value.url } : {}),
  }
}

function parseStoredToolCall(value: unknown): StoredResearchToolCall | null {
  if (!isRecord(value) || typeof value.id !== 'string' || !isRecord(value.function)) return null
  if (typeof value.function.name !== 'string') return null
  return {
    id: value.id,
    function: {
      name: value.function.name,
      arguments: optionalString(value.function.arguments),
    },
  }
}

function parseStoredMessage(value: unknown): StoredResearchMessage | null {
  if (!isRecord(value) || typeof value.role !== 'string') return null
  const toolCalls = Array.isArray(value.tool_calls)
    ? value.tool_calls.map(parseStoredToolCall).filter((item): item is StoredResearchToolCall => item !== null)
    : undefined
  return {
    role: value.role,
    content: optionalString(value.content),
    ...(toolCalls ? { tool_calls: toolCalls } : {}),
    ...(typeof value.tool_call_id === 'string' ? { tool_call_id: value.tool_call_id } : {}),
  }
}

export function parseResearchSessionSummary(value: unknown): ResearchSessionSummary {
  if (!isRecord(value) || typeof value.id !== 'string') {
    throw new TypeError('Invalid research session response')
  }
  return {
    id: value.id,
    title: optionalString(value.title),
    message_count: optionalNumber(value.message_count),
    created_at: optionalString(value.created_at),
    updated_at: optionalString(value.updated_at),
  }
}

export function parseResearchSessionDetail(value: unknown): ResearchSessionDetail {
  if (!isRecord(value)) throw new TypeError('Invalid research session response')
  const summary = parseResearchSessionSummary(value)
  const messages = Array.isArray(value.messages)
    ? value.messages.map(parseStoredMessage).filter((item): item is StoredResearchMessage => item !== null)
    : []
  return { ...summary, messages }
}

export function parseResearchSessions(value: unknown) {
  return parsePage(value, parseResearchSessionSummary)
}

export function parseResearchSearchResult(value: unknown): ResearchSearchResult {
  if (!isRecord(value) || typeof value.id !== 'number' || typeof value.tool_name !== 'string') {
    throw new TypeError('Invalid research result response')
  }
  return {
    id: value.id,
    tool_name: value.tool_name,
    query: optionalString(value.query),
    result_type: optionalString(value.result_type),
    source: optionalString(value.source),
    title: optionalString(value.title),
    url: optionalString(value.url),
    hit_count: optionalNumber(value.hit_count),
    result_data: isRecord(value.result_data) ? value.result_data : {},
    created_at: optionalString(value.created_at),
  }
}

export function parseResearchSearchResults(value: unknown) {
  return parsePage(value, parseResearchSearchResult)
}

function parseArticleList(value: unknown): ResearchArticle[] {
  return Array.isArray(value)
    ? value.map(parseArticle).filter((item): item is ResearchArticle => item !== null)
    : []
}

function parseWebResults(value: unknown): ResearchWebResult[] {
  return Array.isArray(value)
    ? value.map(parseWebResult).filter((item): item is ResearchWebResult => item !== null)
    : []
}

/** Runtime boundary for the backend's JSON-over-SSE event protocol. */
export function parseResearchEvent(value: unknown): ResearchEvent | null {
  if (!isRecord(value) || typeof value.type !== 'string') return null

  switch (value.type) {
    case 'session_created':
      return typeof value.session_id === 'string' ? { type: value.type, session_id: value.session_id } : null
    case 'thinking':
      return { type: value.type, ...(typeof value.iteration === 'number' ? { iteration: value.iteration } : {}) }
    case 'query_decomposed':
      return { type: value.type }
    case 'tool_call':
      if (typeof value.call_id !== 'string' || typeof value.name !== 'string') return null
      return {
        type: value.type,
        call_id: value.call_id,
        name: value.name,
        args: isRecord(value.args) ? value.args : {},
      }
    case 'tool_result':
      if (typeof value.call_id !== 'string') return null
      return {
        type: value.type,
        call_id: value.call_id,
        summary: optionalString(value.summary),
        articles: parseArticleList(value.articles),
        results: parseWebResults(value.results),
        title: optionalString(value.title),
        id: optionalId(value.id),
        source: optionalString(value.source),
        url: optionalString(value.url),
        content_truncated: value.content_truncated === true,
        original_length: optionalNumber(value.original_length),
        length: optionalNumber(value.length),
      }
    case 'text_delta':
      return typeof value.text === 'string' ? { type: value.type, text: value.text } : null
    case 'complete':
      return { type: value.type }
    case 'error':
      return { type: value.type, message: optionalString(value.message) }
    default:
      return null
  }
}
