import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { LANG_KEY } from '@/constants'
import { iterSSEEvents, iterTextChunks, streamingFetch } from '@/utils/sse'
import { isRecord } from '@/types/news'
import type { NewsListParams } from '@/types/news'
import type { FavoriteType } from '@/types/news'

export type NewsId = string | number
export type ApiQueryParams = Readonly<Record<string, string | number | boolean | undefined>>

export const CAPABILITY_FEATURE_NAMES = [
  'news',
  'keyword_search',
  'semantic_search',
  'accounts',
  'signup',
  'favorites',
  'blocked_news',
  'chat_history',
  'fetch_full',
  'translation',
  'chat',
  'suggested_questions',
  'tts',
  'research',
  'provider_comparisons',
  'admin',
  'chatgpt_subscription',
  'ai_byok',
] as const

export type CapabilityName = (typeof CAPABILITY_FEATURE_NAMES)[number]
export type CapabilityReason =
  | 'public_read_only'
  | 'ai_disabled'
  | 'semantic_search_disabled'
  | 'signup_disabled'
  | 'chatgpt_auth_disabled'
  | 'hosted_integration_unapproved'
  | 'chatgpt_plan_usage_disabled'
  | 'byok_disabled'
  | 'capabilities_unavailable'

export interface CapabilityFeature {
  enabled: boolean
  reason: CapabilityReason | null
}

export interface SiteCapabilities {
  site_mode: 'full' | 'read_only'
  chatgpt_auth_mode: 'disabled' | 'local_oss' | 'website'
  features: Record<CapabilityName, CapabilityFeature>
}

const CAPABILITY_REASONS = new Set<CapabilityReason>([
  'public_read_only',
  'ai_disabled',
  'semantic_search_disabled',
  'signup_disabled',
  'chatgpt_auth_disabled',
  'hosted_integration_unapproved',
  'chatgpt_plan_usage_disabled',
  'byok_disabled',
  'capabilities_unavailable',
])

export function parseCapabilities(value: unknown): SiteCapabilities {
  if (!isRecord(value) || (value.site_mode !== 'full' && value.site_mode !== 'read_only') ||
    (value.chatgpt_auth_mode !== 'disabled' && value.chatgpt_auth_mode !== 'local_oss' && value.chatgpt_auth_mode !== 'website') ||
    !isRecord(value.features)) {
    throw new TypeError('Invalid site capabilities response')
  }

  const featureNames = Object.keys(value.features)
  if (featureNames.length !== CAPABILITY_FEATURE_NAMES.length ||
    CAPABILITY_FEATURE_NAMES.some((name) => !Object.prototype.hasOwnProperty.call(value.features, name))) {
    throw new TypeError('Invalid site capabilities response')
  }

  const features = {} as Record<CapabilityName, CapabilityFeature>
  for (const name of CAPABILITY_FEATURE_NAMES) {
    const feature: unknown = value.features[name]
    if (!isRecord(feature) || typeof feature.enabled !== 'boolean') {
      throw new TypeError('Invalid site capabilities response')
    }
    if (feature.enabled) {
      if (feature.reason !== null) throw new TypeError('Invalid site capabilities response')
      features[name] = { enabled: true, reason: null }
      continue
    }
    if (typeof feature.reason !== 'string' || !CAPABILITY_REASONS.has(feature.reason as CapabilityReason)) {
      throw new TypeError('Invalid site capabilities response')
    }
    features[name] = { enabled: false, reason: feature.reason as CapabilityReason }
  }

  return {
    site_mode: value.site_mode,
    chatgpt_auth_mode: value.chatgpt_auth_mode,
    features,
  }
}

export interface ProviderComparisonParams extends ApiQueryParams {
  page?: number
  page_size?: number
  search?: string
}

export type ProviderComparisonInput = { news_id: string } | { url: string }

export interface ResearchResultsParams extends ApiQueryParams {
  result_type?: string
  detail?: string
}

export interface ResearchStreamOptions {
  localOnly?: boolean
  idempotencyKey?: string
  signal?: AbortSignal
  onSessionId?: (sessionId: string) => void
  onRunId?: (runId: string) => void
}

export interface ResearchChatStreamOptions {
  localOnly?: boolean
  idempotencyKey?: string
  signal?: AbortSignal
  onRunId?: (runId: string) => void
}

export interface OpenResearchSessionStreamOptions {
  signal?: AbortSignal
  onRunId?: (runId: string) => void
  waitForQueued?: boolean
}

export type OpenResearchSessionStreamResponse =
  | { kind: 'session'; data: unknown }
  | { kind: 'queued'; runId: string | null }
  | { kind: 'stream'; events: AsyncIterable<unknown> }

interface SuggestedQuestionsOptions {
  force?: boolean
  signal?: AbortSignal
}

interface ChatStreamOptions {
  webSearch?: boolean
  modelConfigId?: string | null
  signal?: AbortSignal
}

function addLangParam(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  const lang = typeof localStorage === 'undefined' ? 'zh' : localStorage.getItem(LANG_KEY) || 'zh'
  if (config.params instanceof URLSearchParams) {
    config.params.set('lang', lang)
  } else {
    config.params = { ...(config.params ?? {}), lang }
  }
  return config
}

/** Attach Django's session-bound CSRF cookie to unsafe Axios requests. */
function attachCsrfToken(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  const unsafeMethods = new Set(['post', 'put', 'patch', 'delete'])
  if (!unsafeMethods.has(config.method?.toLowerCase() ?? '')) return config
  if (typeof document === 'undefined') return config

  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  if (match) config.headers.set('X-CSRFToken', decodeURIComponent(match[1]))
  return config
}

function makeApi(timeout: number): AxiosInstance {
  const instance = axios.create({
    baseURL: '/api',
    timeout,
    withCredentials: true,
  })
  instance.interceptors.request.use(addLangParam)
  instance.interceptors.request.use(attachCsrfToken)
  return instance
}

const api = makeApi(10_000)
const apiFetch = makeApi(120_000)
const apiLong = makeApi(180_000)

export async function fetchCapabilities(): Promise<SiteCapabilities> {
  const value: unknown = (await api.get<unknown>('/capabilities/')).data
  return parseCapabilities(value)
}

export interface AIProviderProfile {
  provider_id: string
  provider_name: string
  profile_id: string
  region_name: string
  base_url: string
  version: number
}

export interface AIConnection {
  id: string
  provider_id: string
  provider_name: string
  endpoint_profile: string
  region_name: string
  display_name: string
  key_saved: boolean
  masked_key: string
  is_enabled: boolean
  verification_status: 'not_tested'
  updated_at: string
}

export interface CreateAIConnectionInput {
  provider_id: string
  endpoint_profile: string
  display_name: string
  api_key: string
}

export interface AIModelPreset {
  catalog_model_id: string
  provider_id: string
  model_id: string
  display_name: string
  context_window_tokens: number | null
  max_output_tokens: number | null
  catalog_version: string
  source_url: string
  provider_claims: Record<string, unknown>
}

export interface AIModelCatalog {
  catalog_version: string
  models: AIModelPreset[]
  catalog_available: boolean
}

export type AIModelCapability = 'unknown' | 'supported' | 'unsupported'
export type AIModelVerificationStatus = 'not_tested' | 'verified' | 'failed' | 'stale'

export interface AIModelConfig {
  id: string
  connection_id: string
  model_id: string
  display_name: string
  source: 'catalog' | 'manual'
  catalog_model_id: string
  catalog_version: string
  catalog_source_url: string
  provider_claims: Record<string, unknown>
  context_window_tokens: number | null
  max_output_tokens: number | null
  has_trusted_context_limit: boolean
  config_revision: number
  verification_status: AIModelVerificationStatus
  capabilities: {
    text: AIModelCapability
    tools: AIModelCapability
    structured_output: AIModelCapability
    thinking: AIModelCapability
    stream: AIModelCapability
  }
  last_tested_at: string | null
  updated_at: string
}

export type CreateAIModelInput =
  | { connection_id: string; catalog_model_id: string; display_name?: string }
  | { connection_id: string; model_id: string; display_name?: string }

export type AIModelProbeKind = 'text' | 'tools'

export interface AIModelTestResult {
  attempt_id: string
  probe_kind: AIModelProbeKind
  status: 'succeeded' | 'failed' | 'unknown' | 'not_sent' | 'stale'
  verification_status: AIModelVerificationStatus
  capability: AIModelCapability
  stale: boolean
  safe_error_code: string
  latency_ms: number
  input_tokens: number | null
  output_tokens: number | null
  billing_notice: 'provider_may_bill'
}

export type AITaskKind = 'default' | 'article_qa' | 'full_translation' | 'deep_research' | 'question_suggestions'
export type AITaskPreferenceState = 'available' | 'needs_reselection' | 'inherit_default' | 'unset'

export interface AITaskPreference {
  task_kind: AITaskKind
  model_config_id: string | null
  selection_state: AITaskPreferenceState
  model: {
    id: string
    model_id: string
    display_name: string
    connection_id: string
  } | null
}

export interface SaveAITaskPreference {
  task_kind: AITaskKind
  model_config_id: string | null
}

const AI_TASK_KINDS: AITaskKind[] = [
  'default', 'article_qa', 'full_translation', 'deep_research', 'question_suggestions',
]

function parseAITaskPreference(value: unknown): AITaskPreference {
  if (!isRecord(value) ||
    !AI_TASK_KINDS.includes(value.task_kind as AITaskKind) ||
    !(value.model_config_id === null || typeof value.model_config_id === 'string') ||
    !['available', 'needs_reselection', 'inherit_default', 'unset'].includes(String(value.selection_state)) ||
    !(value.model === null || isRecord(value.model)) ||
    Object.keys(value).some((key) => !['task_kind', 'model_config_id', 'selection_state', 'model'].includes(key))) {
    throw new TypeError('Invalid AI task preference response')
  }
  let model: AITaskPreference['model'] = null
  if (value.model !== null) {
    const candidate = value.model
    if (typeof candidate.id !== 'string' || typeof candidate.model_id !== 'string' ||
      typeof candidate.display_name !== 'string' || typeof candidate.connection_id !== 'string' ||
      Object.keys(candidate).some((key) => !['id', 'model_id', 'display_name', 'connection_id'].includes(key)) ||
      value.model_config_id !== candidate.id) {
      throw new TypeError('Invalid AI task preference response')
    }
    model = {
      id: candidate.id,
      model_id: candidate.model_id,
      display_name: candidate.display_name,
      connection_id: candidate.connection_id,
    }
  }
  return {
    task_kind: value.task_kind as AITaskKind,
    model_config_id: value.model_config_id,
    selection_state: value.selection_state as AITaskPreferenceState,
    model,
  }
}

function parseAITaskPreferences(value: unknown): AITaskPreference[] {
  if (!isRecord(value) || !Array.isArray(value.preferences)) throw new TypeError('Invalid AI task preferences response')
  const preferences = value.preferences.map(parseAITaskPreference)
  if (preferences.length !== AI_TASK_KINDS.length ||
    new Set(preferences.map((item) => item.task_kind)).size !== AI_TASK_KINDS.length ||
    !AI_TASK_KINDS.every((taskKind) => preferences.some((item) => item.task_kind === taskKind))) {
    throw new TypeError('Invalid AI task preferences response')
  }
  return preferences
}

export async function fetchAITaskPreferences(signal?: AbortSignal): Promise<AITaskPreference[]> {
  const value: unknown = (await api.get<unknown>('/ai/preferences/', { signal })).data
  return parseAITaskPreferences(value)
}

export async function saveAITaskPreferences(preferences: SaveAITaskPreference[]): Promise<AITaskPreference[]> {
  const safePreferences = preferences.map(({ task_kind, model_config_id }) => ({ task_kind, model_config_id }))
  const value: unknown = (await api.patch<unknown>('/ai/preferences/', { preferences: safePreferences })).data
  return parseAITaskPreferences(value)
}

function parseAIProviderProfiles(value: unknown): AIProviderProfile[] {
  if (!isRecord(value) || !Array.isArray(value.providers)) throw new TypeError('Invalid AI provider catalog')
  return value.providers.map((entry): AIProviderProfile => {
    if (!isRecord(entry) || typeof entry.provider_id !== 'string' || typeof entry.provider_name !== 'string' ||
      typeof entry.profile_id !== 'string' || typeof entry.region_name !== 'string' ||
      typeof entry.base_url !== 'string' || typeof entry.version !== 'number') {
      throw new TypeError('Invalid AI provider catalog')
    }
    return {
      provider_id: entry.provider_id,
      provider_name: entry.provider_name,
      profile_id: entry.profile_id,
      region_name: entry.region_name,
      base_url: entry.base_url,
      version: entry.version,
    }
  })
}

function parseAIConnection(value: unknown): AIConnection {
  if (!isRecord(value) || Object.keys(value).some((key) =>
    ['api_key', 'raw_key', 'credential_ciphertext', 'encrypted_api_key'].includes(key)) ||
    typeof value.id !== 'string' || typeof value.provider_id !== 'string' ||
    typeof value.provider_name !== 'string' || typeof value.endpoint_profile !== 'string' ||
    typeof value.region_name !== 'string' || typeof value.display_name !== 'string' ||
    typeof value.key_saved !== 'boolean' || typeof value.masked_key !== 'string' ||
    typeof value.is_enabled !== 'boolean' || value.verification_status !== 'not_tested' ||
    typeof value.updated_at !== 'string') {
    throw new TypeError('Invalid AI connection response')
  }
  return {
    id: value.id,
    provider_id: value.provider_id,
    provider_name: value.provider_name,
    endpoint_profile: value.endpoint_profile,
    region_name: value.region_name,
    display_name: value.display_name,
    key_saved: value.key_saved,
    masked_key: value.masked_key,
    is_enabled: value.is_enabled,
    verification_status: 'not_tested',
    updated_at: value.updated_at,
  }
}

export async function fetchAIProviderProfiles(signal?: AbortSignal): Promise<AIProviderProfile[]> {
  const value: unknown = (await api.get<unknown>('/ai/providers/', { signal })).data
  return parseAIProviderProfiles(value)
}

export async function fetchAIConnections(signal?: AbortSignal): Promise<AIConnection[]> {
  const value: unknown = (await api.get<unknown>('/ai/connections/', { signal })).data
  if (!isRecord(value) || !Array.isArray(value.connections)) throw new TypeError('Invalid AI connections response')
  return value.connections.map(parseAIConnection)
}

export async function createAIConnection(input: CreateAIConnectionInput): Promise<AIConnection> {
  const value: unknown = (await api.post<unknown>('/ai/connections/', input)).data
  return parseAIConnection(value)
}

export async function replaceAIConnectionKey(connectionId: string, apiKey: string): Promise<AIConnection> {
  const value: unknown = (await api.put<unknown>(`/ai/connections/${connectionId}/key/`, { api_key: apiKey })).data
  return parseAIConnection(value)
}

export async function updateAIConnection(
  connectionId: string,
  patch: { display_name?: string; is_enabled?: boolean },
): Promise<AIConnection> {
  const value: unknown = (await api.patch<unknown>(`/ai/connections/${connectionId}/`, patch)).data
  return parseAIConnection(value)
}

export async function deleteAIConnection(connectionId: string): Promise<{ deleted: boolean }> {
  const value: unknown = (await api.delete<unknown>(`/ai/connections/${connectionId}/`)).data
  if (!isRecord(value) || value.deleted !== true) throw new TypeError('Invalid AI delete response')
  return { deleted: true }
}

function parseAIModelPreset(value: unknown): AIModelPreset {
  if (!isRecord(value) || Object.keys(value).some((key) => ['proxy_model_alias', 'api_key', 'credential_ciphertext'].includes(key)) ||
    typeof value.catalog_model_id !== 'string' || typeof value.provider_id !== 'string' ||
    typeof value.model_id !== 'string' || typeof value.display_name !== 'string' ||
    !(value.context_window_tokens === null || typeof value.context_window_tokens === 'number') ||
    !(value.max_output_tokens === null || typeof value.max_output_tokens === 'number') ||
    typeof value.catalog_version !== 'string' || typeof value.source_url !== 'string' ||
    !isRecord(value.provider_claims)) {
    throw new TypeError('Invalid AI model catalog')
  }
  return {
    catalog_model_id: value.catalog_model_id,
    provider_id: value.provider_id,
    model_id: value.model_id,
    display_name: value.display_name,
    context_window_tokens: value.context_window_tokens,
    max_output_tokens: value.max_output_tokens,
    catalog_version: value.catalog_version,
    source_url: value.source_url,
    provider_claims: value.provider_claims,
  }
}

function parseAIModel(value: unknown): AIModelConfig {
  if (!isRecord(value)) throw new TypeError('Invalid AI model response')
  const capabilityValue = value.capabilities
  if (!isRecord(capabilityValue) || Object.keys(value).some((key) =>
    ['api_key', 'raw_key', 'credential_ciphertext', 'encrypted_api_key', 'proxy_model_alias'].includes(key)) ||
    typeof value.id !== 'string' || typeof value.connection_id !== 'string' ||
    typeof value.model_id !== 'string' || typeof value.display_name !== 'string' ||
    (value.source !== 'catalog' && value.source !== 'manual') ||
    typeof value.catalog_model_id !== 'string' || typeof value.catalog_version !== 'string' ||
    typeof value.catalog_source_url !== 'string' || !isRecord(value.provider_claims) ||
    !(value.context_window_tokens === null || typeof value.context_window_tokens === 'number') ||
    !(value.max_output_tokens === null || typeof value.max_output_tokens === 'number') ||
    typeof value.has_trusted_context_limit !== 'boolean' || typeof value.config_revision !== 'number' ||
    !['not_tested', 'verified', 'failed', 'stale'].includes(String(value.verification_status)) ||
    !(['text', 'tools', 'structured_output', 'thinking', 'stream'] as const).every((name) =>
      ['unknown', 'supported', 'unsupported'].includes(String(capabilityValue[name]))) ||
    !(value.last_tested_at === null || typeof value.last_tested_at === 'string') ||
    typeof value.updated_at !== 'string') {
    throw new TypeError('Invalid AI model response')
  }
  return {
    id: value.id,
    connection_id: value.connection_id,
    model_id: value.model_id,
    display_name: value.display_name,
    source: value.source,
    catalog_model_id: value.catalog_model_id,
    catalog_version: value.catalog_version,
    catalog_source_url: value.catalog_source_url,
    provider_claims: value.provider_claims,
    context_window_tokens: value.context_window_tokens,
    max_output_tokens: value.max_output_tokens,
    has_trusted_context_limit: value.has_trusted_context_limit,
    config_revision: value.config_revision,
    verification_status: value.verification_status as AIModelVerificationStatus,
    capabilities: {
      text: capabilityValue.text as AIModelCapability,
      tools: capabilityValue.tools as AIModelCapability,
      structured_output: capabilityValue.structured_output as AIModelCapability,
      thinking: capabilityValue.thinking as AIModelCapability,
      stream: capabilityValue.stream as AIModelCapability,
    },
    last_tested_at: value.last_tested_at,
    updated_at: value.updated_at,
  }
}

export async function fetchAIModelCatalog(signal?: AbortSignal): Promise<AIModelCatalog> {
  const value: unknown = (await api.get<unknown>('/ai/models/catalog/', { signal })).data
  if (!isRecord(value) || typeof value.catalog_version !== 'string' || !Array.isArray(value.models) ||
    (value.catalog_available !== undefined && typeof value.catalog_available !== 'boolean')) {
    throw new TypeError('Invalid AI model catalog')
  }
  return {
    catalog_version: value.catalog_version,
    models: value.models.map(parseAIModelPreset),
    catalog_available: value.catalog_available !== false,
  }
}

export async function fetchAIModels(signal?: AbortSignal): Promise<AIModelConfig[]> {
  const value: unknown = (await api.get<unknown>('/ai/models/', { signal })).data
  if (!isRecord(value) || !Array.isArray(value.models)) throw new TypeError('Invalid AI model list')
  return value.models.map(parseAIModel)
}

export async function createAIModel(input: CreateAIModelInput): Promise<AIModelConfig> {
  const value: unknown = (await api.post<unknown>('/ai/models/', input)).data
  return parseAIModel(value)
}

export async function updateAIModel(
  modelId: string,
  patch: { model_id?: string; display_name?: string },
): Promise<AIModelConfig> {
  const value: unknown = (await api.patch<unknown>(`/ai/models/${modelId}/`, patch)).data
  return parseAIModel(value)
}

export async function deleteAIModel(modelId: string): Promise<{ deleted: boolean }> {
  const value: unknown = (await api.delete<unknown>(`/ai/models/${modelId}/`)).data
  if (!isRecord(value) || value.deleted !== true) throw new TypeError('Invalid AI model delete response')
  return { deleted: true }
}

function parseAIModelTestResult(value: unknown): AIModelTestResult {
  if (!isRecord(value) ||
    typeof value.attempt_id !== 'string' ||
    !['text', 'tools'].includes(String(value.probe_kind)) ||
    !['succeeded', 'failed', 'unknown', 'not_sent', 'stale'].includes(String(value.status)) ||
    !['not_tested', 'verified', 'failed', 'stale'].includes(String(value.verification_status)) ||
    !['unknown', 'supported', 'unsupported'].includes(String(value.capability)) ||
    typeof value.stale !== 'boolean' || typeof value.safe_error_code !== 'string' ||
    typeof value.latency_ms !== 'number' ||
    !(value.input_tokens === null || typeof value.input_tokens === 'number') ||
    !(value.output_tokens === null || typeof value.output_tokens === 'number') ||
    value.billing_notice !== 'provider_may_bill' ||
    Object.keys(value).some((key) => ['api_key', 'provider_key', 'raw_response', 'response_body'].includes(key))) {
    throw new TypeError('Invalid AI model test response')
  }
  return {
    attempt_id: value.attempt_id,
    probe_kind: value.probe_kind as AIModelProbeKind,
    status: value.status as AIModelTestResult['status'],
    verification_status: value.verification_status as AIModelVerificationStatus,
    capability: value.capability as AIModelCapability,
    stale: value.stale,
    safe_error_code: value.safe_error_code,
    latency_ms: value.latency_ms,
    input_tokens: value.input_tokens,
    output_tokens: value.output_tokens,
    billing_notice: 'provider_may_bill',
  }
}

export async function testAIModel(modelId: string, probeKind: AIModelProbeKind): Promise<AIModelTestResult> {
  const value: unknown = (await api.post<unknown>(`/ai/models/${modelId}/test/`, { probe_kind: probeKind })).data
  return parseAIModelTestResult(value)
}

// ---- News -----------------------------------------------------------------

export function fetchNews(params: Partial<NewsListParams> = {}, signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>('/news/', { params, signal }).then(({ data }) => data)
}

export function fetchSemanticSearch(query: string, params: Partial<NewsListParams> = {}): Promise<unknown> {
  return api.get<unknown>('/news/', { params: { ...params, search: query, mode: 'semantic' } }).then(({ data }) => data)
}

export function fetchNewsDetail(id: NewsId, signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>(`/news/${id}/`, { signal }).then(({ data }) => data)
}

export function fetchFullArticle(id: NewsId, force = false, signal?: AbortSignal): Promise<unknown> {
  return apiFetch.post<unknown>(`/news/${id}/fetch-full/`, force === true ? { force: true } : undefined, { signal }).then(({ data }) => data)
}

export function translateFullArticle(id: NewsId): Promise<unknown> {
  return apiLong.post<unknown>(`/news/${id}/translate/`).then(({ data }) => data)
}

export function fetchCategories(signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>('/categories/', { signal }).then(({ data }) => data)
}

export function fetchSources(signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>('/sources/', { signal }).then(({ data }) => data)
}

// ---- Provider comparisons -------------------------------------------------

export function fetchProviderComparisons(params: ProviderComparisonParams = {}, signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>('/provider-comparisons/', { params, signal }).then(({ data }) => data)
}

export function createProviderComparison(payload: ProviderComparisonInput, signal?: AbortSignal): Promise<unknown> {
  const request = signal
    ? apiLong.post<unknown>('/provider-comparisons/', payload, { signal })
    : apiLong.post<unknown>('/provider-comparisons/', payload)
  return request.then(({ data }) => data)
}

export function retestProviderComparison(id: NewsId, signal?: AbortSignal): Promise<unknown> {
  const request = signal
    ? apiLong.post<unknown>(`/provider-comparisons/${id}/retest/`, undefined, { signal })
    : apiLong.post<unknown>(`/provider-comparisons/${id}/retest/`)
  return request.then(({ data }) => data)
}

// ---- Chat -----------------------------------------------------------------

export function fetchChatHistory(newsId: NewsId, signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>(`/news/${newsId}/chat/`, { signal }).then(({ data }) => data)
}

export function clearChatHistory(newsId: NewsId, signal?: AbortSignal): Promise<unknown> {
  return api.delete<unknown>(`/news/${newsId}/chat/`, { signal }).then(({ data }) => data)
}

export function fetchSuggestedQuestions(newsId: NewsId, { force = false, signal }: SuggestedQuestionsOptions = {}): Promise<unknown> {
  return api.post<unknown>(`/news/${newsId}/suggested-questions/`, null, {
    params: force ? { force: 1 } : undefined,
    signal,
  }).then(({ data }) => data)
}

export async function* translateFullArticleStream(
  id: NewsId,
  { force = false, signal, onJobId }: {
    force?: boolean
    signal?: AbortSignal
    onJobId?: (jobId: string) => void
  } = {},
): AsyncGenerator<unknown> {
  const response = await streamingFetch(`/api/news/${id}/translate/`, {
    body: JSON.stringify({ force }),
    signal,
  })
  const jobId = response.headers.get('Job-ID')
  if (jobId) onJobId?.(jobId)
  // Only translation uses the bounded fragmented envelope. Research retains
  // its independently limited 32-KiB/16-KiB event contract.
  const encoder = new TextEncoder()
  const maxMessageBytes = 32 * 1024 * 1024
  let fragments = 0
  let fragmentBytes = 0
  let fragmentPayload = ''
  let progress = ''
  for await (const incoming of iterSSEEvents(response)) {
    let event: unknown = incoming
    if (isRecord(incoming) && Object.prototype.hasOwnProperty.call(incoming, '__translation_sse_fragment_v1')) {
      const fragment = incoming.__translation_sse_fragment_v1
      if (typeof fragment !== 'string' || incoming.index !== fragments || typeof incoming.last !== 'boolean') {
        throw new TypeError('Invalid translation SSE fragment sequence')
      }
      fragmentBytes += encoder.encode(fragment).byteLength
      if (fragmentBytes > maxMessageBytes) throw new RangeError('Translation SSE message exceeded 32 MiB')
      fragmentPayload += fragment
      fragments += 1
      if (!incoming.last) continue
      try {
        event = JSON.parse(fragmentPayload) as unknown
      } finally {
        fragmentPayload = ''
        fragments = 0
        fragmentBytes = 0
      }
    } else if (fragments !== 0) {
      throw new TypeError('Interrupted translation SSE fragment sequence')
    }
    if (isRecord(event) && typeof event.progress_delta === 'string') {
      progress += event.progress_delta
      yield { progress }
      continue
    }
    if (isRecord(event) && typeof event.progress === 'string') progress = event.progress
    if (isRecord(event) && typeof event.error === 'string') {
      // Provider errors remain data for the UI, not transport failures.
      yield { error: event.error }
      return
    }
    yield event
  }
  if (fragments !== 0) throw new TypeError('Incomplete translation SSE fragment sequence')
}

export async function* chatStream(
  newsId: NewsId,
  question: string,
  { webSearch = false, modelConfigId = null, signal }: ChatStreamOptions = {},
): AsyncGenerator<string> {
  const response = await streamingFetch(`/api/news/${newsId}/chat/`, {
    body: JSON.stringify({
      question,
      web_search: webSearch,
      ...(modelConfigId ? { model_config_id: modelConfigId } : {}),
    }),
    signal,
  })
  yield* iterTextChunks(response)
}

// ---- Favorites and blocks -------------------------------------------------

export function toggleFavorite(newsId: NewsId, type: FavoriteType): Promise<unknown> {
  return api.post<unknown>('/favorites/', { news_id: newsId, type }).then(({ data }) => data)
}

export function checkFavoriteStatus(newsId: NewsId, signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>('/favorites/check/', { params: { news_id: newsId }, signal }).then(({ data }) => data)
}

export function fetchUserFavorites(params: ApiQueryParams = {}, signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>('/favorites/', { params, signal }).then(({ data }) => data)
}

export function blockNews(newsId: NewsId): Promise<unknown> {
  return api.post<unknown>('/blocked/', { news_id: newsId }).then(({ data }) => data)
}

export function unblockNews(newsId: NewsId): Promise<unknown> {
  return api.delete<unknown>('/blocked/', { data: { news_id: newsId } }).then(({ data }) => data)
}

export function checkBlockedStatus(newsId: NewsId, signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>('/blocked/check/', { params: { news_id: newsId }, signal }).then(({ data }) => data)
}

export function fetchBlockedNews(params: ApiQueryParams = {}, signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>('/blocked/', { params, signal }).then(({ data }) => data)
}

// ---- Authentication -------------------------------------------------------

export async function fetchCsrfToken(): Promise<string> {
  const response: unknown = (await api.get<unknown>('/auth/csrf/')).data
  if (!isRecord(response) || typeof response.csrfToken !== 'string') {
    throw new TypeError('Invalid CSRF response')
  }
  return response.csrfToken
}

export function registerUser(username: string, password: string, email = '', inviteToken = ''): Promise<unknown> {
  const payload: { username: string; password: string; email: string; invite_token?: string } = { username, password, email }
  const normalizedInviteToken = inviteToken.trim()
  if (normalizedInviteToken) payload.invite_token = normalizedInviteToken
  return api.post<unknown>('/auth/register/', payload).then(({ data }) => data)
}

export function loginUser(username: string, password: string): Promise<unknown> {
  return api.post<unknown>('/auth/login/', { username, password }).then(({ data }) => data)
}

export function logoutUser(): Promise<unknown> {
  return api.post<unknown>('/auth/logout/').then(({ data }) => data)
}

export function fetchMe(): Promise<unknown> {
  return api.get<unknown>('/auth/me/').then(({ data }) => data)
}

// ---- Local ChatGPT subscription ------------------------------------------

export interface ChatGPTSubscriptionConnection {
  id: string
  account_name: string
  account_email: string
  selected_model: string
  active: boolean
  connected: boolean
  needs_reauth: boolean
  updated_at: string
}

export interface ChatGPTSubscriptionStatus {
  connections: ChatGPTSubscriptionConnection[]
  active_connection_id: string | null
}

export interface ChatGPTSubscriptionModel {
  slug: string
  display_name: string
}

export interface ChatGPTSubscriptionModels {
  models: ChatGPTSubscriptionModel[]
  selected_model: string
}

function parseChatGPTSubscriptionConnection(value: unknown): ChatGPTSubscriptionConnection {
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.active !== 'boolean' ||
    typeof value.connected !== 'boolean' || typeof value.needs_reauth !== 'boolean') {
    throw new TypeError('Invalid ChatGPT subscription connection response')
  }
  return {
    id: value.id,
    account_name: typeof value.account_name === 'string' ? value.account_name : '',
    account_email: typeof value.account_email === 'string' ? value.account_email : '',
    selected_model: typeof value.selected_model === 'string' ? value.selected_model : '',
    active: value.active,
    connected: value.connected,
    needs_reauth: value.needs_reauth,
    updated_at: typeof value.updated_at === 'string' ? value.updated_at : '',
  }
}

export async function fetchChatGPTSubscriptionStatus(): Promise<ChatGPTSubscriptionStatus> {
  const value: unknown = (await api.get<unknown>('/chatgpt-subscription/')).data
  if (!isRecord(value) || !Array.isArray(value.connections)) throw new TypeError('Invalid ChatGPT subscription status')
  const activeId = value.active_connection_id
  if (activeId !== null && typeof activeId !== 'string') throw new TypeError('Invalid active subscription ID')
  return {
    connections: value.connections.map(parseChatGPTSubscriptionConnection),
    active_connection_id: activeId as string | null,
  }
}

export interface ChatGPTSubscriptionAttemptStart {
  attempt_id: string
  handoff_token: string
  handoff_url: string
}

export interface ChatGPTSubscriptionAttemptStatus {
  id: string
  status: 'pending' | 'authorizing' | 'processing' | 'completed' | 'failed' | 'cancelled'
  message: string
  connection_id: string | null
}

function parseChatGPTSubscriptionAttemptStatus(value: unknown): ChatGPTSubscriptionAttemptStatus {
  const statuses = ['pending', 'authorizing', 'processing', 'completed', 'failed', 'cancelled'] as const
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.status !== 'string' ||
    typeof value.message !== 'string' || (value.connection_id !== null && typeof value.connection_id !== 'string') ||
    !statuses.includes(value.status as (typeof statuses)[number])) {
    throw new TypeError('Invalid ChatGPT authorization attempt status')
  }
  return {
    id: value.id,
    status: value.status as ChatGPTSubscriptionAttemptStatus['status'],
    message: value.message,
    connection_id: value.connection_id as string | null,
  }
}

export async function startChatGPTSubscriptionConnect(connectionId?: string): Promise<ChatGPTSubscriptionAttemptStart> {
  const value: unknown = (await api.post<unknown>('/chatgpt-subscription/connect/', connectionId ? { connection_id: connectionId } : {})).data
  if (!isRecord(value) || typeof value.attempt_id !== 'string' || typeof value.handoff_token !== 'string' ||
    typeof value.handoff_url !== 'string') {
    throw new TypeError('Invalid ChatGPT authorization handoff response')
  }
  const handoff = new URL(value.handoff_url)
  if (value.handoff_url !== 'http://127.0.0.1:9527/api/chatgpt-subscription/handoff/' ||
    handoff.protocol !== 'http:' || handoff.hostname !== '127.0.0.1' || handoff.port !== '9527' ||
    handoff.username || handoff.password || handoff.pathname !== '/api/chatgpt-subscription/handoff/' ||
    handoff.search || handoff.hash) {
    throw new TypeError('Invalid ChatGPT authorization handoff URL')
  }
  return { attempt_id: value.attempt_id, handoff_token: value.handoff_token, handoff_url: handoff.href }
}

export async function fetchChatGPTSubscriptionAttempt(
  attemptId: string,
  signal?: AbortSignal,
): Promise<ChatGPTSubscriptionAttemptStatus> {
  const value: unknown = (await api.get<unknown>(`/chatgpt-subscription/attempts/${attemptId}/`, { signal })).data
  return parseChatGPTSubscriptionAttemptStatus(value)
}

export async function cancelChatGPTSubscriptionAttempt(attemptId: string): Promise<ChatGPTSubscriptionAttemptStatus> {
  const value: unknown = (await api.delete<unknown>(`/chatgpt-subscription/attempts/${attemptId}/`)).data
  return parseChatGPTSubscriptionAttemptStatus(value)
}

export async function fetchChatGPTSubscriptionModels(connectionId: string): Promise<ChatGPTSubscriptionModels> {
  const value: unknown = (await api.get<unknown>(`/chatgpt-subscription/connections/${connectionId}/models/`)).data
  if (!isRecord(value) || !Array.isArray(value.models)) throw new TypeError('Invalid ChatGPT model list')
  const models = value.models.flatMap((model) =>
    isRecord(model) && typeof model.slug === 'string' && typeof model.display_name === 'string'
      ? [{ slug: model.slug, display_name: model.display_name }]
      : [],
  )
  return { models, selected_model: typeof value.selected_model === 'string' ? value.selected_model : '' }
}

export function activateChatGPTSubscriptionConnection(connectionId: string): Promise<unknown> {
  return api.post<unknown>(`/chatgpt-subscription/connections/${connectionId}/activate/`).then(({ data }) => data)
}

export function selectChatGPTSubscriptionModel(connectionId: string, slug: string): Promise<unknown> {
  return api.post<unknown>(`/chatgpt-subscription/connections/${connectionId}/select-model/`, { slug }).then(({ data }) => data)
}

export function disconnectChatGPTSubscription(connectionId: string): Promise<{ disconnected: boolean; revocation_confirmed: boolean }> {
  return api.delete<{ disconnected: boolean; revocation_confirmed: boolean }>(`/chatgpt-subscription/connections/${connectionId}/`).then(({ data }) => data)
}


export function getChatGPTTranslationTask(jobId: string, signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>(`/chatgpt-subscription/jobs/${jobId}/`, { signal }).then(({ data }) => data)
}

export function cancelChatGPTTranslationTask(jobId: string, generation: number): Promise<unknown> {
  return api.post<unknown>(`/chatgpt-subscription/jobs/${jobId}/cancel/`, { generation }).then(({ data }) => data)
}
// ---- Research -------------------------------------------------------------

export function listResearchSessions(params: ApiQueryParams = {}, signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>('/research/sessions/', { params, signal }).then(({ data }) => data)
}

export function getResearchSession(sessionId: string, signal?: AbortSignal): Promise<unknown> {
  return api.get<unknown>(`/research/${sessionId}/`, { signal }).then(({ data }) => data)
}

export function deleteResearchSession(sessionId: string): Promise<unknown> {
  return api.delete<unknown>(`/research/${sessionId}/`).then(({ data }) => data)
}

export async function* createResearchStream(
  query: string,
  { localOnly = false, idempotencyKey, signal, onSessionId, onRunId }: ResearchStreamOptions = {},
): AsyncGenerator<unknown> {
  const response = await streamingFetch('/api/research/', {
    body: JSON.stringify({ query, local_only: localOnly }),
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    signal,
  })
  const sessionId = response.headers.get('Session-ID')
  const runId = response.headers.get('Run-ID')
  if (runId) onRunId?.(runId)
  if (sessionId) {
    onSessionId?.(sessionId)
    yield { type: 'session_created', session_id: sessionId }
  }

  let headerSessionEventPending = Boolean(sessionId)
  for await (const event of iterSSEEvents(response)) {
    // Django repeats the response header in the first event; callers receive it once.
    if (headerSessionEventPending && isRecord(event) && event.type === 'session_created' && event.session_id === sessionId) {
      headerSessionEventPending = false
      continue
    }
    yield event
  }
}

export async function* researchChatStream(
  sessionId: string,
  query: string,
  { localOnly = false, idempotencyKey, signal, onRunId }: ResearchChatStreamOptions = {},
): AsyncGenerator<unknown> {
  const response = await streamingFetch(`/api/research/${sessionId}/chat/`, {
    body: JSON.stringify({ query, local_only: localOnly }),
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    signal,
  })
  const runId = response.headers.get('Run-ID')
  if (runId) onRunId?.(runId)
  yield* iterSSEEvents(response)
}

export async function openResearchSessionStream(
  sessionId: string,
  { signal, onRunId, waitForQueued = false }: OpenResearchSessionStreamOptions = {},
): Promise<OpenResearchSessionStreamResponse> {
  let queuedPolls = 0
  while (true) {
    const response = await streamingFetch(`/api/research/${sessionId}/stream/`, { method: 'GET', signal })
    const runId = response.headers.get('Run-ID')
    if (runId) onRunId?.(runId)
    if (response.headers.get('content-type')?.includes('application/json')) {
      return { kind: 'session', data: (await response.json()) as unknown }
    }
    if (response.headers.get('Run-Status') === 'queued') {
      await response.body?.cancel()
      if (!waitForQueued || ++queuedPolls >= 10) return { kind: 'queued', runId }
      await new Promise<void>((resolve) => setTimeout(resolve, 1000))
      if (signal?.aborted) throw new Error('Research stream aborted')
      continue
    }
    return { kind: 'stream', events: iterSSEEvents(response) }
  }
}

export function resumeQueuedResearchRun(sessionId: string, runId: string): Promise<unknown> {
  return api.post<unknown>('/research/' + sessionId + '/resume-queued/', { run_id: runId }).then(({ data }) => data)
}

export function cancelResearchRun(sessionId: string, runId: string): Promise<unknown> {
  return api.post<unknown>(`/research/${sessionId}/cancel/`, { run_id: runId }).then(({ data }) => data)
}

export function getResearchResults(
  sessionId: string,
  params: ResearchResultsParams = {},
  signal?: AbortSignal,
): Promise<unknown> {
  return api.get<unknown>(`/research/${sessionId}/results/`, { params, signal }).then(({ data }) => data)
}
