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
  has_trusted_route: boolean; context_window_tokens: number | null; updated_at: string
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
export async function listAIModels(connection: AIConnection, signal?: AbortSignal) {
  return (await call<{ models: AIModel[] }>(modelRoot(connection), { signal })).models
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
