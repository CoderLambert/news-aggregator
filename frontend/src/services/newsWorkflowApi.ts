import axios from 'axios'
import type { NewsId } from '@/services/api'
export type { NewsId } from '@/services/api'
import {
  cancelChatGPTTranslationTask as cancelTranslationTaskRequest,
  chatStream as streamChat,
  clearChatHistory as clearChatHistoryRequest,
  fetchChatHistory as fetchChatHistoryRequest,
  fetchNewsDetail as fetchNewsDetailRequest,
  fetchFullArticle as fetchFullArticleRequest,
  fetchSuggestedQuestions as fetchSuggestedQuestionsRequest,
  getChatGPTTranslationTask as getTranslationTaskRequest,
  translateFullArticleStream as streamTranslation,
} from '@/services/api'
import { isRecord } from '@/types/news'

export interface FullArticleResult {
  full_content: string
  full_content_fetched_at?: string | null
  full_content_fetch_status?: string
  full_content_fetch_error?: string
  full_content_fetch_provider?: string
  full_content_quality_score?: number | null
  full_content_retry_count?: number
  last_full_content_attempt?: string | null
}

export interface FullArticleFailure {
  message: string
  metadata: Partial<Omit<FullArticleResult, 'full_content' | 'full_content_fetched_at'>> & {
    last_full_content_attempt?: string | null
  }
}

export interface WebSource {
  title: string
  url?: string
  snippet?: string
  source?: string
}

export interface ChatMessage {
  id?: string | number
  role: 'user' | 'assistant'
  content: string
  web_search?: boolean
  web_sources?: WebSource[]
}

export interface ChatHistory {
  messages: ChatMessage[]
}

export type TranslationEvent =
  | { type: 'progress'; text: string }
  | { type: 'complete'; fullContentZh: string; fetchedAt: string | null; scope?: string; source?: string }
  | { type: 'waiting_shared' }
  | { type: 'error'; message: string }
  | { type: 'ignored' }


export interface TranslationJobSnapshot {
  id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted'
  generation: number
  progress: string
  result: Record<string, unknown>
  errorCode: string
  errorMessage: string
}

function parseTranslationJob(value: unknown): TranslationJobSnapshot {
  if (
    !isRecord(value) ||
    typeof value.id !== 'string' ||
    typeof value.status !== 'string' ||
    !['queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted'].includes(value.status) ||
    typeof value.generation !== 'number' ||
    !Number.isInteger(value.generation) ||
    value.generation < 1
  ) {
    throw new TypeError('Invalid translation job response')
  }
  return {
    id: value.id,
    status: value.status as TranslationJobSnapshot['status'],
    generation: value.generation,
    progress: typeof value.progress === 'string' ? value.progress : '',
    result: isRecord(value.result) ? value.result : {},
    errorCode: typeof value.error_code === 'string' ? value.error_code : '',
    errorMessage: typeof value.error_message === 'string' ? value.error_message : '',
  }
}
function optionalString(record: Record<string, unknown>, key: string): string | undefined {
  return typeof record[key] === 'string' ? record[key] : undefined
}

function optionalDate(record: Record<string, unknown>, key: string): string | null | undefined {
  return record[key] === null ? null : optionalString(record, key)
}

function optionalNumber(record: Record<string, unknown>, key: string): number | undefined {
  return typeof record[key] === 'number' ? record[key] : undefined
}

export function parseFullArticleResult(value: unknown): FullArticleResult {
  if (!isRecord(value) || typeof value.full_content !== 'string') {
    throw new TypeError('Invalid full-article response: expected full_content')
  }
  const result: FullArticleResult = { full_content: value.full_content }
  const fetchedAt = optionalDate(value, 'full_content_fetched_at')
  const status = optionalString(value, 'full_content_fetch_status')
  const error = optionalString(value, 'full_content_fetch_error')
  const provider = optionalString(value, 'full_content_fetch_provider')
  const quality = value.full_content_quality_score === null ? null : optionalNumber(value, 'full_content_quality_score')
  const retryCount = optionalNumber(value, 'full_content_retry_count')
  const lastAttempt = optionalDate(value, 'last_full_content_attempt')
  if (fetchedAt !== undefined) result.full_content_fetched_at = fetchedAt
  if (status !== undefined) result.full_content_fetch_status = status
  if (error !== undefined) result.full_content_fetch_error = error
  if (provider !== undefined) result.full_content_fetch_provider = provider
  if (quality !== undefined) result.full_content_quality_score = quality
  if (retryCount !== undefined) result.full_content_retry_count = retryCount
  if (lastAttempt !== undefined) result.last_full_content_attempt = lastAttempt
  return result
}

export function parseFullArticleFailure(error: unknown): FullArticleFailure {
  let responseBody: unknown
  if (axios.isAxiosError(error)) responseBody = error.response?.data
  const body = isRecord(responseBody) ? responseBody : {}
  const metadata: FullArticleFailure['metadata'] = {}
  const status = optionalString(body, 'full_content_fetch_status')
  const fetchError = optionalString(body, 'full_content_fetch_error')
  const provider = optionalString(body, 'full_content_fetch_provider')
  const quality = body.full_content_quality_score === null ? null : optionalNumber(body, 'full_content_quality_score')
  const retryCount = optionalNumber(body, 'full_content_retry_count')
  const lastAttempt = optionalDate(body, 'last_full_content_attempt')
  if (status !== undefined) metadata.full_content_fetch_status = status
  if (fetchError !== undefined) metadata.full_content_fetch_error = fetchError
  if (provider !== undefined) metadata.full_content_fetch_provider = provider
  if (quality !== undefined) metadata.full_content_quality_score = quality
  if (retryCount !== undefined) metadata.full_content_retry_count = retryCount
  if (lastAttempt !== undefined) metadata.last_full_content_attempt = lastAttempt

  const responseMessage = optionalString(body, 'error')
  const errorMessage = error instanceof Error ? error.message : ''
  return {
    message: responseMessage || errorMessage || '获取失败',
    metadata,
  }
}

export function parseWebSources(value: unknown): WebSource[] | undefined {
  if (!Array.isArray(value)) return undefined
  const sources = value.flatMap((item) => {
    if (!isRecord(item) || typeof item.title !== 'string') return []
    return [{
      title: item.title,
      ...(typeof item.url === 'string' ? { url: item.url } : {}),
      ...(typeof item.snippet === 'string' ? { snippet: item.snippet } : {}),
      ...(typeof item.source === 'string' ? { source: item.source } : {}),
    }]
  })
  return sources
}

function parseChatMessage(value: unknown): ChatMessage | null {
  if (!isRecord(value) || (value.role !== 'user' && value.role !== 'assistant') || typeof value.content !== 'string') {
    return null
  }
  const message: ChatMessage = { role: value.role, content: value.content }
  if (typeof value.id === 'string' || typeof value.id === 'number') message.id = value.id
  if (typeof value.web_search === 'boolean') message.web_search = value.web_search
  const sources = parseWebSources(value.web_sources)
  if (sources) message.web_sources = sources
  return message
}

export function parseChatHistory(value: unknown): ChatHistory {
  if (!isRecord(value) || !Array.isArray(value.messages)) {
    throw new TypeError('Invalid chat-history response: expected messages')
  }
  return { messages: value.messages.flatMap((item) => {
    const message = parseChatMessage(item)
    return message ? [message] : []
  }) }
}

export function parseSuggestedQuestions(value: unknown): string[] {
  if (!isRecord(value) || !Array.isArray(value.questions)) return []
  return value.questions.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
}

export function parseTranslationEvent(value: unknown): TranslationEvent {
  if (!isRecord(value)) return { type: 'ignored' }
  if (typeof value.error === 'string') return { type: 'error', message: value.error }
  if (value.waiting_shared === true) return { type: 'waiting_shared' }
  if (typeof value.full_content_zh === 'string') {
    return {
      type: 'complete',
      fullContentZh: value.full_content_zh,
      fetchedAt: typeof value.full_content_zh_fetched_at === 'string' ? value.full_content_zh_fetched_at : null,
      ...(typeof value.full_content_zh_scope === 'string' ? { scope: value.full_content_zh_scope } : {}),
      ...(typeof value.full_content_zh_source === 'string' ? { source: value.full_content_zh_source } : {}),
    }
  }
  if (typeof value.progress === 'string') return { type: 'progress', text: value.progress }
  return { type: 'ignored' }
}

export async function fetchFullArticle(id: NewsId, force: boolean, signal: AbortSignal): Promise<FullArticleResult> {
  const data: unknown = await fetchFullArticleRequest(id, force, signal)
  return parseFullArticleResult(data)
}

export async function fetchFullArticleStatus(id: NewsId, signal: AbortSignal): Promise<FullArticleResult> {
  const data: unknown = await fetchNewsDetailRequest(id, signal)
  return parseFullArticleResult(data)
}

export async function fetchChatHistory(id: NewsId, signal: AbortSignal): Promise<ChatHistory> {
  const data: unknown = await fetchChatHistoryRequest(id, signal)
  return parseChatHistory(data)
}

export async function clearChatHistory(id: NewsId, signal: AbortSignal): Promise<void> {
  await clearChatHistoryRequest(id, signal)
}

export async function fetchSuggestedQuestions(id: NewsId, options: { force?: boolean; signal: AbortSignal }): Promise<string[]> {
  const data: unknown = await fetchSuggestedQuestionsRequest(id, options)
  return parseSuggestedQuestions(data)
}

export async function* translateFullArticleStream(
  id: NewsId,
  options: { force: boolean; signal: AbortSignal; onJobId?: (jobId: string) => void },
): AsyncGenerator<TranslationEvent> {
  for await (const rawEvent of streamTranslation(id, options)) {
    const event: unknown = rawEvent
    yield parseTranslationEvent(event)
  }
}

export async function getTranslationJob(jobId: string, signal: AbortSignal): Promise<TranslationJobSnapshot> {
  return parseTranslationJob(await getTranslationTaskRequest(jobId, signal))
}

export async function cancelTranslationJob(jobId: string, generation: number): Promise<TranslationJobSnapshot> {
  return parseTranslationJob(await cancelTranslationTaskRequest(jobId, generation))
}

export async function* chatStream(
  id: NewsId,
  question: string,
  options: { webSearch: boolean; signal: AbortSignal },
): AsyncGenerator<string> {
  for await (const rawChunk of streamChat(id, question, options)) {
    if (typeof rawChunk === 'string') yield rawChunk
  }
}
