import { isRecord } from '@/types/news'
import { workspaceRequest } from '@/services/workspaceApi'

export interface PrivateTranslationTask {
  task_id: string
  request_id: string
  news_id: number
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted'
  progress: string
  error_code: string
  model_config_id: string
  target_language: 'zh'
  result: null | { result_id: number; task_id: string; content: string; scope: 'private'; provider: string; model: string }
}
const statuses = new Set(['queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted'])
export function parsePrivateTranslation(value: unknown): PrivateTranslationTask {
  if (!isRecord(value) || typeof value.task_id !== 'string' || typeof value.request_id !== 'string' || typeof value.news_id !== 'number' ||
      typeof value.status !== 'string' || !statuses.has(value.status) || typeof value.progress !== 'string' ||
      typeof value.error_code !== 'string' || typeof value.model_config_id !== 'string' ||
      value.target_language !== 'zh') throw new TypeError('Invalid private translation')
  if (value.status === 'succeeded') {
    if (!isRecord(value.result) || value.result.scope !== 'private' ||
        typeof value.result.result_id !== 'number' || value.result.task_id !== value.task_id ||
        typeof value.result.content !== 'string' || !value.result.content.trim() ||
        typeof value.result.provider !== 'string' || typeof value.result.model !== 'string') {
      throw new TypeError('Invalid completed private translation')
    }
  } else if (value.result !== null) throw new TypeError('Partial result cannot be complete')
  return value as unknown as PrivateTranslationTask
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
