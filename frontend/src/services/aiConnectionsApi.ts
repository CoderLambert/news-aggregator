import { WorkspaceError, workspaceRequest } from '@/services/workspaceApi'

export type AIAuthMode = 'api_key' | 'none'
export interface AIProviderProfile {
  provider_id: string; provider_name: string; profile_id: string; region_name: string; version: number
  network_zone?: 'public_https' | 'same_host' | 'trusted_private'
  auth_modes?: AIAuthMode[]; protocol_family?: string; data_destination_label?: string
}
export interface AIConnection {
  id: string; provider_id: string; provider_name: string; endpoint_profile: string; endpoint_profile_version: number
  display_name: string; region_name: string; key_saved: boolean; masked_key: string; is_enabled: boolean
  revision: number; credential_epoch: number; verification_status: 'not_tested'; updated_at: string
  auth_mode?: AIAuthMode; model_discovery_supported?: boolean; data_destination_label?: string
}
export type NewConnection = { provider_id: string; endpoint_profile: string; display_name: string; request_id: string } &
  ({ auth_mode?: 'api_key'; api_key: string } | { auth_mode: 'none'; api_key?: never })
export function hasAIConnectionAuthentication(connection: AIConnection) {
  return connection.auth_mode === 'none' ? connection.key_saved === false
    : (connection.auth_mode === undefined || connection.auth_mode === 'api_key') && connection.key_saved === true
}
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
  const { providers } = await call<{ providers: AIProviderProfile[] }>('/me/ai/providers/', { signal })
  if (!Array.isArray(providers) || providers.some(profile => profile.auth_modes !== undefined &&
    (!Array.isArray(profile.auth_modes) || profile.auth_modes.length === 0 || profile.auth_modes.length > 2 ||
      new Set(profile.auth_modes).size !== profile.auth_modes.length ||
      profile.auth_modes.some(mode => mode !== 'api_key' && mode !== 'none')))) throw new ConnectionRequestError(0)
  return providers
}
export async function listAIConnections(signal?: AbortSignal) {
  const { connections } = await call<{ connections: AIConnection[] }>('/me/ai/connections/', { signal })
  if (!Array.isArray(connections) || connections.some(connection =>
    connection.auth_mode !== undefined && connection.auth_mode !== 'api_key' && connection.auth_mode !== 'none' ||
    connection.auth_mode === 'none' && connection.key_saved !== false)) throw new ConnectionRequestError(0)
  return connections
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
  delivery_mode?: 'streaming' | 'buffered' | 'unavailable' | 'unknown'; stream_verified?: boolean; protocol_family?: string | null
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
  return models.map(model => {
    const raw = model as Record<string, unknown>
    const capabilities = typeof raw.capabilities === 'object' && raw.capabilities !== null
      ? raw.capabilities as Record<string, unknown> : {}
    const capability = (value: unknown): AIModelCapability =>
      value === 'supported' || value === 'unsupported' ? value : 'unknown'
    const hasRoute = raw.has_trusted_route === true
    const knownMode = raw.delivery_mode === 'streaming' || raw.delivery_mode === 'buffered'
    const knownProtocol = raw.protocol_family === undefined || ['chat_completions_v1', 'openai-responses-v1',
      'anthropic-messages-v1'].includes(String(raw.protocol_family))
    return {
      ...model, has_trusted_route: hasRoute,
      capabilities: { text: capability(capabilities.text), tools: capability(capabilities.tools) },
      article_chat_supported: raw.article_chat_supported === true && hasRoute && knownProtocol &&
        (raw.delivery_mode === undefined || knownMode),
      ...(Object.hasOwn(model, 'delivery_mode') ? { delivery_mode: knownMode ? raw.delivery_mode : 'unknown' } : {}),
      ...(Object.hasOwn(model, 'stream_verified') ? {
        stream_verified: raw.stream_verified === true && hasRoute && knownProtocol && raw.delivery_mode === 'streaming',
      } : {}),
    }
  }) as AIModel[]
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

export async function discoverAIModels(connection: AIConnection, viewer: number, signal?: AbortSignal) {
  const result = await call<{ models: string[]; truncated: boolean }>(modelRoot(connection) + 'discover/',
    { method: 'POST', body: {}, viewer, signal })
  if (!Array.isArray(result.models) || result.models.length > 100 || result.models.some(id =>
    typeof id !== 'string' || id.length === 0 || id.length > 160)) throw new ConnectionRequestError(0)
  return result
}
export interface AIConnectionDiagnostics {
  connection_status: 'active' | 'authorization_unavailable'
  endpoint_status: 'approved' | 'unavailable'; protocol_family: string | null
  auth_mode: AIAuthMode; data_destination_label: string; inference_test_status: 'not_run'
}
export function getAIConnectionDiagnostics(connection: AIConnection, signal?: AbortSignal) {
  return call<AIConnectionDiagnostics>(`/me/ai/connections/${connection.id}/diagnostics/`, { signal })
}

export type AITaskKind = 'default' | 'article_qa' | 'full_translation' | 'deep_research' | 'question_suggestions'
export type AITaskSelectionState = 'unset' | 'inherit_default' | 'available' | 'needs_reselection' | 'needs_verification'
export interface AITaskPreference {
  task_kind: AITaskKind
  model_config_id: string | null
  selection_state: AITaskSelectionState
  model: { id: string; connection_id: string; model_id: string; display_name: string; research_eligible?: boolean } | null
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
  route_metadata?: { protocol_family?: string; delivery_mode?: string; auth_mode?: AIAuthMode; terminal_verified?: boolean }
}
export interface AIUsage {
  summary: { calls: number; input_tokens: number | null; output_tokens: number | null
    input_tokens_unknown_calls: number; output_tokens_unknown_calls: number }
  attempts: AIUsageAttempt[]; has_more: boolean
  page?: number; page_size?: number; count?: number; page_count?: number
}
export function listAIUsage(signal?: AbortSignal, page?: number, limit = 20) {
  return call<AIUsage>(`/me/ai/usage/${page === undefined ? '' : `?page=${page}&limit=${limit}`}`, { signal })
}
