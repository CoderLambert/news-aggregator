import axios from 'axios'
import { LANG_KEY } from '../constants'
import { streamingFetch, iterSSEEvents, iterTextChunks } from '../utils/sse'

// ---- Axios clients ---------------------------------------------------------

function addLangParam(config) {
  const lang = localStorage.getItem(LANG_KEY) || 'zh'
  if (lang) {
    config.params = config.params || {}
    config.params.lang = lang
  }
  return config
}

// Shared interceptor — injected into ALL axios instances below.
axios.interceptors.request.use(addLangParam)

/**
 * Automatically attach Django CSRF token to unsafe HTTP methods.
 *
 * After login, the browser holds a `csrftoken` cookie. Axios with
 * `withCredentials: true` sends the cookie, but Django also requires
 * the `X-CSRFToken` header on POST/PUT/DELETE/PATCH — otherwise it
 * returns 403 even when the view has `@csrf_exempt` (DRF's
 * `SessionAuthentication` enforces CSRF at the auth layer).
 */
function getCsrfFromCookie() {
  if (typeof document === 'undefined') return null
  const match = document.cookie.match(/csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

function attachCsrfToken(config) {
  const unsafe = ['post', 'put', 'patch', 'delete']
  if (unsafe.includes(config.method?.toLowerCase())) {
    const token = getCsrfFromCookie()
    if (token) {
      config.headers['X-CSRFToken'] = token
    }
  }
  return config
}

function makeApi(timeout) {
  const inst = axios.create({
    baseURL: '/api',
    timeout,
    withCredentials: true,  // send cookies for session auth
  })
  inst.interceptors.request.use(addLangParam)
  inst.interceptors.request.use(attachCsrfToken)
  return inst
}

const api      = makeApi(10_000)   // default REST
const apiFetch = makeApi(120_000)  // article fetch via Jina (2 min)
const apiLong  = makeApi(180_000)  // translation (3 min)

// ---- REST endpoints --------------------------------------------------------

export const fetchNews = (params = {}, signal) =>
  api.get('/news/', { params, signal }).then(res => res.data)

export const fetchSemanticSearch = (query, params = {}) =>
  api.get('/news/', { params: { ...params, search: query, mode: 'semantic' } }).then(res => res.data)

export const fetchNewsDetail = (id, signal) =>
  api.get(`/news/${id}/`, { signal }).then(res => res.data)

export const fetchFullArticle = (id, force = false, signal) =>
  apiFetch.post(`/news/${id}/fetch-full/`, force ? { force: true } : undefined, { signal }).then(res => res.data)

export const translateFullArticle = (id) =>
  apiLong.post(`/news/${id}/translate/`).then(res => res.data)

export const fetchCategories = (signal) =>
  api.get('/categories/', { signal }).then(res => res.data)

export const fetchSources = (signal) =>
  api.get('/sources/', { signal }).then(res => res.data)

// ---- Provider Comparisons --------------------------------------------------

export const fetchProviderComparisons = (params = {}, signal) =>
  (signal
    ? api.get('/provider-comparisons/', { params, signal })
    : api.get('/provider-comparisons/', { params })).then(res => res.data)

export const createProviderComparison = (payload, signal) =>
  (signal
    ? apiLong.post('/provider-comparisons/', payload, { signal })
    : apiLong.post('/provider-comparisons/', payload)).then(res => res.data)

export const retestProviderComparison = (id, signal) =>
  (signal
    ? apiLong.post(`/provider-comparisons/${id}/retest/`, undefined, { signal })
    : apiLong.post(`/provider-comparisons/${id}/retest/`)).then(res => res.data)

// ---- Chat (REST) -----------------------------------------------------------

export const fetchChatHistory = (newsId) =>
  api.get(`/news/${newsId}/chat/`).then(res => res.data)

export const clearChatHistory = (newsId) =>
  api.delete(`/news/${newsId}/chat/`).then(res => res.data)

export const fetchSuggestedQuestions = (newsId, { force = false } = {}) =>
  api.post(`/news/${newsId}/suggested-questions/`, null, {
    params: force ? { force: 1 } : undefined,
  }).then(res => res.data)

// ---- Streaming endpoints (SSE / token streams) -----------------------------

/**
 * Translate full article — yields { progress } | { full_content_zh, full_content_zh_fetched_at } | { error }.
 *
 *   for await (const ev of translateFullArticleStream(id, { force: true })) { ... }
 */
export async function* translateFullArticleStream(id, { force = false } = {}) {
  const res = await streamingFetch(`/api/news/${id}/translate/`, {
    body: JSON.stringify({ force }),
  })
  for await (const ev of iterSSEEvents(res)) {
    if (ev.error) {
      // Friendly fallback messages from the provider failover chain
      // should be yielded as a special event, not thrown as an exception,
      // so the UI can display them gracefully instead of a raw "翻译失败".
      yield { error: ev.error }
      return
    }
    yield ev
  }
}

/**
 * Send a chat question — yields raw text chunks as they arrive.
 *
 *   for await (const chunk of chatStream(id, "请总结这篇文章")) { accumulated += chunk; ... }
 */
export async function* chatStream(newsId, question, { webSearch = false } = {}) {
  const res = await streamingFetch(`/api/news/${newsId}/chat/`, {
    body: JSON.stringify({ question, web_search: webSearch }),
  })
  yield* iterTextChunks(res)
}

// ---- Favorites / Likes / Bookmarks ------------------------------------------

export const toggleFavorite = (newsId, type) =>
  api.post('/favorites/', { news_id: newsId, type }).then(res => res.data)

export const checkFavoriteStatus = (newsId, signal) =>
  api.get('/favorites/check/', { params: { news_id: newsId }, signal }).then(res => res.data)

export const fetchUserFavorites = (params = {}, signal) =>
  api.get('/favorites/', { params, signal }).then(res => res.data)

// ---- Blocked News -----------------------------------------------------------

export const blockNews = (newsId) =>
  api.post('/blocked/', { news_id: newsId }).then(res => res.data)

export const unblockNews = (newsId) =>
  api.delete('/blocked/', { data: { news_id: newsId } }).then(res => res.data)

export const checkBlockedStatus = (newsId, signal) =>
  api.get('/blocked/check/', { params: { news_id: newsId }, signal }).then(res => res.data)

export const fetchBlockedNews = (params = {}, signal) =>
  api.get('/blocked/', { params, signal }).then(res => res.data)

// ---- Authentication --------------------------------------------------------

export const fetchCsrfToken = () =>
  api.get('/auth/csrf/').then(res => res.data.csrfToken)

export const registerUser = (username, password, email = '') =>
  api.post('/auth/register/', { username, password, email }).then(res => res.data)

export const loginUser = (username, password) =>
  api.post('/auth/login/', { username, password }).then(res => res.data)

export const logoutUser = () =>
  api.post('/auth/logout/').then(res => res.data)

export const fetchMe = () =>
  api.get('/auth/me/').then(res => res.data)

// ---- Research Agent --------------------------------------------------------

export const listResearchSessions = (params = {}, signal) =>
  (signal
    ? api.get('/research/sessions/', { params, signal })
    : api.get('/research/sessions/', { params })).then(res => res.data)

export const getResearchSession = (sessionId, signal) =>
  (signal
    ? api.get(`/research/${sessionId}/`, { signal })
    : api.get(`/research/${sessionId}/`)).then(res => res.data)

export const deleteResearchSession = (sessionId) =>
  api.delete(`/research/${sessionId}/`).then(res => res.data)

/**
 * Create a new research session + start the agent loop — yields structured
 * SSE events: { type: 'thinking'|'tool_call'|'tool_result'|'text_delta'|'complete'|'error', ... }
 *
 *   for await (const ev of createResearchStream('LLM agents')) { ... }
 *
 * The session ID is returned in the `Session-ID` response header.
 */
export async function* createResearchStream(query, { localOnly = false, signal, onSessionId } = {}) {
  const res = await streamingFetch('/api/research/', {
    body: JSON.stringify({ query, local_only: localOnly }),
    signal,
  })
  const sessionId = res.headers.get('Session-ID')
  if (sessionId) {
    onSessionId?.(sessionId)
    yield { type: 'session_created', session_id: sessionId }
  }

  let headerSessionEventPending = Boolean(sessionId)
  for await (const ev of iterSSEEvents(res)) {
    // The current backend repeats Session-ID in its first SSE event. The
    // response header is emitted first so callers can cancel/resume by id,
    // while this duplicate is suppressed at the API boundary.
    if (headerSessionEventPending && ev?.type === 'session_created' && ev.session_id === sessionId) {
      headerSessionEventPending = false
      continue
    }
    yield ev
  }
}

/**
 * Send a follow-up message to an existing research session — yields SSE events.
 *
 *   for await (const ev of researchChatStream(sessionId, 'tell me more')) { ... }
 */
export async function* researchChatStream(sessionId, query, { localOnly = false, signal } = {}) {
  const res = await streamingFetch(`/api/research/${sessionId}/chat/`, {
    body: JSON.stringify({ query, local_only: localOnly }),
    signal,
  })
  for await (const ev of iterSSEEvents(res)) {
    yield ev
  }
}

/**
 * Resume the current in-process research job, if one is still running.
 * The backend returns the saved session as JSON when there is no active job.
 */
export async function openResearchSessionStream(sessionId, { signal } = {}) {
  const response = await streamingFetch(`/api/research/${sessionId}/stream/`, {
    method: 'GET',
    signal,
  })
  if (response.headers.get('content-type')?.includes('application/json')) {
    return { kind: 'session', data: await response.json() }
  }
  return { kind: 'stream', events: iterSSEEvents(response) }
}

/**
 * Fetch search results for a research session.
 * @param {string} sessionId - Research session UUID
 * @param {{result_type?: string, detail?: string}} [params] - Query params: result_type, detail
 * @param {AbortSignal} [signal] - Cancels the read request when its query is abandoned
 */
export const getResearchResults = (sessionId, params = {}, signal) =>
  (signal
    ? api.get(`/research/${sessionId}/results/`, { params, signal })
    : api.get(`/research/${sessionId}/results/`, { params })).then(res => res.data)
