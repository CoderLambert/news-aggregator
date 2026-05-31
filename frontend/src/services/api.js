import axios from 'axios'
import { LANG_KEY } from '../constants'
import { streamingFetch, iterSSEEvents, iterTextChunks } from '../utils/sse'

// ---- Axios clients ---------------------------------------------------------
//
// We need three timeouts (default REST / full-article fetch / translation),
// but a SINGLE language-injection interceptor must apply to all of them —
// the previous setup attached the interceptor only to `api`, so full-article
// and translation requests silently dropped the user's lang preference.

function addLangParam(config) {
  const lang = localStorage.getItem(LANG_KEY) || 'zh'
  if (lang && lang !== 'original') {
    config.params = config.params || {}
    config.params.lang = lang
  }
  return config
}

function makeApi(timeout) {
  const inst = axios.create({ baseURL: '/api', timeout })
  inst.interceptors.request.use(addLangParam)
  return inst
}

const api      = makeApi(10_000)   // default REST
const apiFetch = makeApi(120_000)  // article fetch via Jina (2 min)
const apiLong  = makeApi(180_000)  // translation (3 min)

// ---- REST endpoints --------------------------------------------------------

export const fetchNews = (params = {}) =>
  api.get('/news/', { params }).then(res => res.data)

export const fetchSemanticSearch = (query, params = {}) =>
  api.get('/news/', { params: { ...params, search: query, mode: 'semantic' } }).then(res => res.data)

export const fetchNewsDetail = (id) =>
  api.get(`/news/${id}/`).then(res => res.data)

export const fetchFullArticle = (id) =>
  apiFetch.post(`/news/${id}/fetch-full/`).then(res => res.data)

export const translateFullArticle = (id) =>
  apiLong.post(`/news/${id}/translate/`).then(res => res.data)

export const fetchCategories = () =>
  api.get('/categories/').then(res => res.data)

export const fetchSources = () =>
  api.get('/sources/').then(res => res.data)

// ---- Chat (REST) -----------------------------------------------------------

export const fetchChatHistory = (newsId) =>
  api.get(`/news/${newsId}/chat/`).then(res => res.data)

export const clearChatHistory = (newsId) =>
  api.delete(`/news/${newsId}/chat/`).then(res => res.data)

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
    if (ev.error) throw new Error(ev.error)
    yield ev
  }
}

/**
 * Send a chat question — yields raw text chunks as they arrive.
 *
 *   for await (const chunk of chatStream(id, "请总结这篇文章")) { accumulated += chunk; ... }
 */
export async function* chatStream(newsId, question) {
  const res = await streamingFetch(`/api/news/${newsId}/chat/`, {
    body: JSON.stringify({ question }),
  })
  yield* iterTextChunks(res)
}
