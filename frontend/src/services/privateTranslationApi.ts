import { isRecord } from '@/types/news'
import { workspaceRequest } from '@/services/workspaceApi'

export interface PrivateTranslationResult {
  result_id: number
  task_id: string
  content: string
  scope: 'private'
  provider: string
  model: string
  skipped_reason?: 'mostly_chinese'
}
export interface PrivateTranslationTask {
  task_id: string
  request_id: string
  news_id: number
  generation: number
  retry_of: string | null
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted'
  progress: string
  error_code: string
  model_config_id: string
  target_language: 'zh'
  result: null | PrivateTranslationResult
  previous_result: null | PrivateTranslationResult
}
const statuses = new Set(['queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted'])
function parseResult(value: unknown): PrivateTranslationResult {
  if (!isRecord(value) || value.scope !== 'private' || typeof value.result_id !== 'number' ||
      typeof value.task_id !== 'string' || typeof value.content !== 'string' || !value.content.trim() ||
      typeof value.provider !== 'string' || typeof value.model !== 'string' ||
      (value.skipped_reason !== undefined && value.skipped_reason !== 'mostly_chinese')) {
    throw new TypeError('Invalid private translation result')
  }
  return value as unknown as PrivateTranslationResult
}
export function parsePrivateTranslation(value: unknown): PrivateTranslationTask {
  if (!isRecord(value) || typeof value.task_id !== 'string' || typeof value.request_id !== 'string' ||
      typeof value.news_id !== 'number' || !Number.isInteger(value.generation) || (value.generation as number) < 1 ||
      !('retry_of' in value) || (value.retry_of !== null && typeof value.retry_of !== 'string') ||
      typeof value.status !== 'string' || !statuses.has(value.status) || typeof value.progress !== 'string' ||
      typeof value.error_code !== 'string' || typeof value.model_config_id !== 'string' ||
      value.target_language !== 'zh' || !('previous_result' in value)) {
    throw new TypeError('Invalid private translation')
  }
  const result = value.result === null ? null : parseResult(value.result)
  const previousResult = value.previous_result === null ? null : parseResult(value.previous_result)
  if (value.status === 'succeeded') {
    if (result === null || result.task_id !== value.task_id) throw new TypeError('Invalid completed private translation')
  } else if (result !== null) throw new TypeError('Partial result cannot be complete')
  return { ...value, result, previous_result: previousResult } as unknown as PrivateTranslationTask
}
export async function latestPrivateTranslation(newsId: number, signal?: AbortSignal) {
  const value = await workspaceRequest<unknown>(`/news/${newsId}/byok-translation/`, { signal })
  if (!isRecord(value) || !('task' in value)) throw new TypeError('Invalid translation recovery')
  return value.task === null ? null : parsePrivateTranslation(value.task)
}
export async function startPrivateTranslation(newsId: number, modelId: string, requestId: string,
  viewer: number, signal?: AbortSignal) {
  return parsePrivateTranslation(await workspaceRequest<unknown>(`/news/${newsId}/byok-translation/`, {
    method: 'POST', viewer, signal, idempotencyKey: requestId,
    body: { model_config_id: modelId, billing_consent: true, target_language: 'zh' },
  }))
}
export interface PrivateTranslationCancelReceipt {
  task_id: string
  status: PrivateTranslationTask['status']
  error_code: string
}
export async function cancelPrivateTranslation(taskId: string, generation: number, viewer: number,
  signal?: AbortSignal): Promise<PrivateTranslationCancelReceipt> {
  const value = await workspaceRequest<unknown>(
    `/me/ai/translations/${encodeURIComponent(taskId)}/cancel/`, {
      method: 'POST', viewer, signal, body: { generation },
    },
  )
  if (!isRecord(value) || value.task_id !== taskId || typeof value.status !== 'string' ||
      !statuses.has(value.status) || typeof value.error_code !== 'string') {
    throw new TypeError('Invalid private translation cancellation receipt')
  }
  return value as unknown as PrivateTranslationCancelReceipt
}
export async function retryPrivateTranslation(taskId: string, modelId: string, requestId: string,
  viewer: number, signal?: AbortSignal) {
  return parsePrivateTranslation(await workspaceRequest<unknown>(
    `/me/ai/translations/${encodeURIComponent(taskId)}/retry/`, {
      method: 'POST', viewer, signal, idempotencyKey: requestId,
      body: { model_config_id: modelId, billing_consent: true, target_language: 'zh' },
    },
  ))
}
