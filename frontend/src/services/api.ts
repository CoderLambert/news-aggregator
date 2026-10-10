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
  { webSearch = false, signal }: ChatStreamOptions = {},
): AsyncGenerator<string> {
  const response = await streamingFetch(`/api/news/${newsId}/chat/`, {
    body: JSON.stringify({ question, web_search: webSearch }),
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
  while (true) {
    const response = await streamingFetch(`/api/research/${sessionId}/stream/`, { method: 'GET', signal })
    const runId = response.headers.get('Run-ID')
    if (runId) onRunId?.(runId)
    if (response.headers.get('content-type')?.includes('application/json')) {
      return { kind: 'session', data: (await response.json()) as unknown }
    }
    if (response.headers.get('Run-Status') === 'queued') {
      await response.body?.cancel()
      if (!waitForQueued) return { kind: 'queued', runId }
      await new Promise<void>((resolve) => setTimeout(resolve, 1000))
      if (signal?.aborted) throw new Error('Research stream aborted')
      continue
    }
    return { kind: 'stream', events: iterSSEEvents(response) }
  }
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
