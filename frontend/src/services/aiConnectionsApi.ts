import { WorkspaceError, workspaceRequest } from '@/services/workspaceApi'

export interface AIProviderProfile { provider_id: string; provider_name: string; profile_id: string; region_name: string; version: number }
export interface AIConnection {
  id: string; provider_id: string; provider_name: string; endpoint_profile: string; endpoint_profile_version: number
  display_name: string; region_name: string; key_saved: boolean; masked_key: string; is_enabled: boolean
  revision: number; credential_epoch: number; verification_status: 'not_tested'; updated_at: string
}
export interface NewConnection { provider_id: string; endpoint_profile: string; display_name: string; api_key: string; request_id: string }
export class ConnectionRequestError extends Error {
  constructor(readonly status: number) {
    super(status === 403 ? '连接管理未启用、站点只读或安全会话已过期，请联系管理员或重新登录。'
      : status === 409 ? '连接已变化，请重新读取后再操作。'
      : status === 429 ? '连接数量或操作频率达到上限。'
      : status === 400 ? '连接信息格式不正确，请检查名称、服务商和 Key。'
      : status === 404 ? '连接已删除或不可访问。'
      : '操作结果未确认，请重新读取连接状态。')
    this.name = 'ConnectionRequestError'
  }
}
async function call<T>(path: string, options: Parameters<typeof workspaceRequest>[1]): Promise<T> {
  try { return await workspaceRequest<T>(path, options) }
  catch (error) { throw new ConnectionRequestError(error instanceof WorkspaceError ? error.status : 0) }
}
export async function listAIProviders(signal?: AbortSignal) {
  return (await call<{ providers: AIProviderProfile[] }>('/me/ai/providers/', { signal })).providers
}
export async function listAIConnections(signal?: AbortSignal) {
  return (await call<{ connections: AIConnection[] }>('/me/ai/connections/', { signal })).connections
}
export function createAIConnection(body: NewConnection, viewer: number, signal?: AbortSignal) {
  return call<AIConnection>('/me/ai/connections/', { method: 'POST', body, viewer, signal })
}
export function patchAIConnection(connection: AIConnection, body: { display_name?: string; is_enabled?: boolean }, viewer: number, signal?: AbortSignal) {
  return call<AIConnection>(`/me/ai/connections/${connection.id}/`, { method: 'PATCH', body: { ...body, revision: connection.revision }, viewer, signal })
}
export function replaceAIConnectionKey(connection: AIConnection, apiKey: string, viewer: number, signal?: AbortSignal) {
  return call<AIConnection>(`/me/ai/connections/${connection.id}/key/`, { method: 'PUT', body: { api_key: apiKey, revision: connection.revision }, viewer, signal })
}
export function deleteAIConnection(connection: AIConnection, viewer: number, signal?: AbortSignal) {
  return call<{ deleted: true }>(`/me/ai/connections/${connection.id}/`, { method: 'DELETE', body: { revision: connection.revision }, viewer, signal })
}

export type AIModelCapability = 'unknown' | 'supported' | 'unsupported'
export interface AIModel {
  id: string; connection_id: string; model_id: string; display_name: string; catalog_model_id: string
  config_revision: number; capabilities: { text: AIModelCapability; tools: AIModelCapability }
  has_trusted_route: boolean; article_chat_supported: boolean
  context_window_tokens: number | null; updated_at: string
}
export interface AIModelCatalogEntry {
  model_id: string; display_name: string; catalog_version: string; context_window_tokens: number | null
  text: 'unknown'; tools: 'unknown'
}
export interface AIModelProbeReceipt {
  attempt_id: string; request_id: string; model_id: string; probe_kind: 'text' | 'tools'
  status: 'started' | 'succeeded' | 'unsupported' | 'unknown' | 'not_sent' | 'stale'
  capability?: AIModelCapability; stale?: boolean; safe_error_code: string
  input_tokens: number | null; output_tokens: number | null; latency_ms: number | null
  billing_notice: 'provider_may_bill'
}

const modelRoot = (connection: AIConnection) => `/me/ai/connections/${connection.id}/models/`
const modelUrl = (connection: AIConnection, model: AIModel) => `${modelRoot(connection)}${model.id}/`

export function listAIModelCatalog(connection: AIConnection, signal?: AbortSignal) {
  return call<{ catalog_version: string; models: AIModelCatalogEntry[] }>(
    `/me/ai/connections/${connection.id}/model-catalog/`, { signal })
}
function parseAIModelList(value: unknown): AIModel[] {
  if (typeof value !== 'object' || value === null) throw new ConnectionRequestError(0)
  const models = (value as { models?: unknown }).models
  if (!Array.isArray(models) || models.some(model => typeof model !== 'object' || model === null)) {
    throw new ConnectionRequestError(0)
  }
  // Older T02 payloads remain usable for model settings/probes, but cannot
  // opt into T04 unless the server explicitly returns the boolean capability.
  return models.map(model => ({
    ...model,
    article_chat_supported: (model as { article_chat_supported?: unknown })
      .article_chat_supported === true,
  })) as AIModel[]
}
export async function listAIModels(connection: AIConnection, signal?: AbortSignal) {
  return parseAIModelList(await call<unknown>(modelRoot(connection), { signal }))
}
export function createAIModel(connection: AIConnection, model_id: string, viewer: number, signal?: AbortSignal) {
  return call<AIModel>(modelRoot(connection), { method: 'POST', body: { model_id }, viewer, signal })
}
export function patchAIModel(connection: AIConnection, model: AIModel, values: { model_id?: string; display_name?: string }, viewer: number, signal?: AbortSignal) {
  return call<AIModel>(modelUrl(connection, model), {
    method: 'PATCH', body: { revision: model.config_revision, ...values }, viewer, signal })
}
export function deleteAIModel(connection: AIConnection, model: AIModel, viewer: number, signal?: AbortSignal) {
  return call<{ deleted: true }>(modelUrl(connection, model), {
    method: 'DELETE', body: { revision: model.config_revision }, viewer, signal })
}
export function probeAIModel(connection: AIConnection, model: AIModel, probe_kind: 'text' | 'tools',
  request_id: string, viewer: number, signal?: AbortSignal) {
  return call<AIModelProbeReceipt>(modelUrl(connection, model) + 'probe/', {
    method: 'POST', body: { revision: model.config_revision, request_id, probe_kind }, viewer, signal })
}
export function listAIModelAttempts(connection: AIConnection, model: AIModel, signal?: AbortSignal) {
  return call<{ attempts: AIModelProbeReceipt[] }>(modelUrl(connection, model) + 'attempts/', { signal })
}

export type AITaskKind = 'default' | 'article_qa' | 'full_translation' | 'deep_research' | 'question_suggestions'
export type AITaskSelectionState = 'unset' | 'inherit_default' | 'available' | 'needs_reselection' | 'needs_verification'
export interface AITaskPreference {
  task_kind: AITaskKind
  model_config_id: string | null
  selection_state: AITaskSelectionState
  model: { id: string; connection_id: string; model_id: string; display_name: string } | null
}
export interface AITaskPreferences {
  revision: number
  preferences: AITaskPreference[]
}
export type AITaskPreferenceInput = Pick<AITaskPreference, 'task_kind' | 'model_config_id'>
const TASK_PREFERENCES_PATH = '/me/ai/task-preferences/'
export function listAITaskPreferences(signal?: AbortSignal) {
  return call<AITaskPreferences>(TASK_PREFERENCES_PATH, { signal })
}
export function saveAITaskPreferences(revision: number, preferences: AITaskPreferenceInput[], viewer: number, signal?: AbortSignal) {
  return call<AITaskPreferences>(TASK_PREFERENCES_PATH, {
    method: 'PATCH', body: { revision, preferences }, viewer, signal,
  })
}


export interface AIUsageAttempt {
  id: string; source: 'business' | 'probe'; task_kind: string; model_id: string; provider_id: string
  status: string; input_tokens: number | null; output_tokens: number | null
  latency_ms: number | null; created_at: string
}
export interface AIUsage {
  summary: { calls: number; input_tokens: number | null; output_tokens: number | null
    input_tokens_unknown_calls: number; output_tokens_unknown_calls: number }
  attempts: AIUsageAttempt[]; has_more: boolean
}
export function listAIUsage(signal?: AbortSignal) {
  return call<AIUsage>('/me/ai/usage/', { signal })
}
