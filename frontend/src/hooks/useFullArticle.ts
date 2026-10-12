import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { fetchFullArticle, fetchFullArticleStatus, parseFullArticleFailure } from '@/services/newsWorkflowApi'
import { parseNewsId } from '@/services/newsWorkflowQueries'
import type { NewsDetail } from '@/types/news'
import { useCapability } from '@/context/CapabilitiesContext'

interface FetchState {
  ownerKey: string
  loading: boolean
  error: string
}

interface FetchRequest {
  ownerKey: string
  controller: AbortController
}

const EMPTY_FETCH_STATE: FetchState = { ownerKey: '', loading: false, error: '' }
const AUTO_ATTEMPT_PREFIX = 'newshub:full-article-auto:v1:'
const AUTO_CANCEL_PREFIX = 'newshub:full-article-cancel:v1:'
const fallbackFlags = new Set<string>()
const SERVER_FETCH_TIMEOUT_MS = 180_000
const SERVER_FETCH_POLL_MS = 1_000
const FETCH_FAILURE_MESSAGES: Record<string, string> = {
  network_error: '网络或源站暂不可达，可稍后重试',
  validation_failed: '抓取内容未通过真实性校验，等待规则优化',
  failed: '原文抓取失败，请稍后重试',
}

function fetchFailureMessage(data: Awaited<ReturnType<typeof fetchFullArticleStatus>>): string {
  return data.full_content_fetch_error?.trim()
    || FETCH_FAILURE_MESSAGES[data.full_content_fetch_status ?? '']
    || '原文抓取失败，请稍后重试'
}

function sessionFlag(prefix: string, ownerKey: string): boolean {
  const key = `${prefix}${ownerKey}`
  try {
    if (typeof window !== 'undefined' && window.sessionStorage.getItem(key) === '1') return true
  } catch {
    // Use the in-memory fallback when browser storage is unavailable.
  }
  return fallbackFlags.has(key)
}

function setSessionFlag(prefix: string, ownerKey: string, enabled: boolean): void {
  const key = `${prefix}${ownerKey}`
  if (enabled) fallbackFlags.add(key)
  else fallbackFlags.delete(key)
  try {
    if (typeof window === 'undefined') return
    if (enabled) window.sessionStorage.setItem(key, '1')
    else window.sessionStorage.removeItem(key)
  } catch {
    // The in-memory fallback still prevents re-render loops in this tab.
  }
}

function waitForNextPoll(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve()
      return
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, SERVER_FETCH_POLL_MS)
    const onAbort = () => {
      window.clearTimeout(timer)
      signal.removeEventListener('abort', onAbort)
      resolve()
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

export function useFullArticle(
  id: string | number | undefined,
  setNews: Dispatch<SetStateAction<NewsDetail | null>>,
  news?: NewsDetail | null,
) {
  const { user } = useAuth()
  const { lang } = useLanguage()
  const fullContentEnabled = useCapability('fetch_full').enabled
  const newsId = parseNewsId(id)
  const ownerKey = `${newsId ?? String(id ?? '')}:${user?.id ?? 'anonymous'}:${lang}`
  const ownerRef = useRef(ownerKey)
  const requestRef = useRef<FetchRequest | null>(null)
  const attachedOwnerRef = useRef<string | null>(null)
  const [state, setState] = useState(EMPTY_FETCH_STATE)
  const visibleState = fullContentEnabled && state.ownerKey === ownerKey ? state : EMPTY_FETCH_STATE

  useLayoutEffect(() => { ownerRef.current = ownerKey }, [ownerKey])

  useEffect(() => () => {
    if (requestRef.current?.ownerKey === ownerKey) {
      requestRef.current.controller.abort()
      requestRef.current = null
    }
    if (attachedOwnerRef.current === ownerKey) attachedOwnerRef.current = null
    setState((current) => current.ownerKey === ownerKey ? EMPTY_FETCH_STATE : current)
  }, [ownerKey])

  useEffect(() => {
    if (fullContentEnabled) return
    const request = requestRef.current
    if (request?.ownerKey === ownerKey) {
      requestRef.current = null
      request.controller.abort()
    }
    if (attachedOwnerRef.current === ownerKey) attachedOwnerRef.current = null
  }, [fullContentEnabled, ownerKey])

  const applyResult = useCallback((
    data: Awaited<ReturnType<typeof fetchFullArticle>>,
    options: { includeBody?: boolean } = {},
  ) => {
    if (newsId === null) return
    const includeBody = options.includeBody !== false
    setNews((previous) => {
      if (!previous || previous.id !== newsId) return previous
      const bodyChanged = includeBody && previous.full_content !== data.full_content
      return {
        ...previous,
        ...(includeBody ? { full_content: data.full_content } : {}),
        ...(includeBody && data.full_content_fetched_at !== undefined ? { full_content_fetched_at: data.full_content_fetched_at } : {}),
        ...(bodyChanged ? { full_content_zh: '', full_content_zh_fetched_at: null } : {}),
        ...(data.full_content_fetch_status !== undefined ? { full_content_fetch_status: data.full_content_fetch_status } : {}),
        ...(data.full_content_fetch_error !== undefined ? { full_content_fetch_error: data.full_content_fetch_error } : {}),
        ...(data.full_content_fetch_provider !== undefined ? { full_content_fetch_provider: data.full_content_fetch_provider } : {}),
        ...(data.full_content_quality_score !== undefined ? { full_content_quality_score: data.full_content_quality_score } : {}),
        ...(data.full_content_retry_count !== undefined ? { full_content_retry_count: data.full_content_retry_count } : {}),
        ...(data.last_full_content_attempt !== undefined ? { last_full_content_attempt: data.last_full_content_attempt } : {}),
      }
    })
  }, [newsId, setNews])

  const executeFetch = useCallback(async (force: boolean, attachOnly: boolean): Promise<boolean> => {
    if (!fullContentEnabled || newsId === null) return false
    if (requestRef.current?.ownerKey === ownerKey) return false
    requestRef.current?.controller.abort()

    if (!attachOnly) setSessionFlag(AUTO_CANCEL_PREFIX, ownerKey, false)
    const request: FetchRequest = { ownerKey, controller: new AbortController() }
    requestRef.current = request
    const isCurrent = () => requestRef.current === request && ownerRef.current === ownerKey
    setState({ ownerKey, loading: true, error: '' })

    const pollExistingTask = async (): Promise<boolean> => {
      const deadline = Date.now() + SERVER_FETCH_TIMEOUT_MS
      while (isCurrent() && !request.controller.signal.aborted && Date.now() < deadline) {
        const data = await fetchFullArticleStatus(newsId, request.controller.signal)
        if (!isCurrent()) return false
        if (data.full_content_fetch_status === 'fetching') {
          applyResult(data, { includeBody: false })
          await waitForNextPoll(request.controller.signal)
          continue
        }

        const hasSuccessfulBody = data.full_content.trim()
          && (data.full_content_fetch_status === 'success' || !data.full_content_fetch_status)
        if (hasSuccessfulBody) {
          applyResult(data)
          return true
        }

        applyResult(data, { includeBody: false })
        setState({ ownerKey, loading: true, error: fetchFailureMessage(data) })
        return false
      }
      if (isCurrent() && !request.controller.signal.aborted) {
        setState({
          ownerKey,
          loading: true,
          error: '原文仍在服务器抓取；可稍后继续查看，当前没有重复发起抓取。',
        })
      }
      return false
    }

    try {
      if (attachOnly) return await pollExistingTask()
      const data = await fetchFullArticle(newsId, force, request.controller.signal)
      if (!isCurrent()) return false
      if (data.full_content_fetch_status === 'fetching') {
        applyResult(data, { includeBody: false })
        return await pollExistingTask()
      }
      const hasSuccessfulBody = data.full_content.trim()
        && (data.full_content_fetch_status === 'success' || !data.full_content_fetch_status)
      if (hasSuccessfulBody) {
        applyResult(data)
        return true
      }
      applyResult(data, { includeBody: false })
      setState({ ownerKey, loading: true, error: fetchFailureMessage(data) })
      return false
    } catch (error: unknown) {
      if (!isCurrent() || request.controller.signal.aborted) return false
      const failure = parseFullArticleFailure(error)
      if (Object.keys(failure.metadata).length > 0) {
        setNews((previous) => previous && previous.id === newsId
          ? { ...previous, ...failure.metadata }
          : previous)
      }
      setState({ ownerKey, loading: true, error: failure.message })
      return false
    } finally {
      if (isCurrent()) {
        requestRef.current = null
        setState((current) => current.ownerKey === ownerKey
          ? { ...current, loading: false }
          : current)
      }
    }
  }, [applyResult, fullContentEnabled, newsId, ownerKey, setNews])

  const handleFetchFullArticle = useCallback(
    (force = false) => executeFetch(force === true, false),
    [executeFetch],
  )
  const attachToExistingFetch = useCallback(
    () => executeFetch(false, true),
    [executeFetch],
  )

  const bodyEmpty = !news?.full_content?.trim()
  const isCurrentNews = Boolean(news && news.id === newsId)
  const canFetchInSession = Boolean(user)
  const status = news?.full_content_fetch_status || ''
  const lastAttempt = news?.last_full_content_attempt
  const retryCount = news?.full_content_retry_count ?? 0

  useEffect(() => {
    if (!fullContentEnabled || !isCurrentNews || newsId === null || !canFetchInSession || !bodyEmpty) return

    if (status === 'fetching') {
      if (sessionFlag(AUTO_CANCEL_PREFIX, ownerKey) || attachedOwnerRef.current === ownerKey) return
      const timer = window.setTimeout(() => {
        if (ownerRef.current !== ownerKey || sessionFlag(AUTO_CANCEL_PREFIX, ownerKey)
          || attachedOwnerRef.current === ownerKey) return
        attachedOwnerRef.current = ownerKey
        setSessionFlag(AUTO_ATTEMPT_PREFIX, ownerKey, true)
        void attachToExistingFetch()
      }, 0)
      return () => window.clearTimeout(timer)
    }

    const shouldAutoFetch = status === 'pending' && !lastAttempt && retryCount === 0
    if (!shouldAutoFetch || sessionFlag(AUTO_ATTEMPT_PREFIX, ownerKey) || sessionFlag(AUTO_CANCEL_PREFIX, ownerKey)) return
    const timer = window.setTimeout(() => {
      if (ownerRef.current !== ownerKey || sessionFlag(AUTO_ATTEMPT_PREFIX, ownerKey)
        || sessionFlag(AUTO_CANCEL_PREFIX, ownerKey)) return
      setSessionFlag(AUTO_ATTEMPT_PREFIX, ownerKey, true)
      void handleFetchFullArticle()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [
    attachToExistingFetch,
    bodyEmpty,
    fullContentEnabled,
    handleFetchFullArticle,
    isCurrentNews,
    canFetchInSession,
    lastAttempt,
    newsId,
    ownerKey,
    retryCount,
    status,
  ])

  const cancelFetch = useCallback(() => {
    const request = requestRef.current
    if (!request || request.ownerKey !== ownerKey) return
    setSessionFlag(AUTO_CANCEL_PREFIX, ownerKey, true)
    requestRef.current = null
    request.controller.abort()
    setState((current) => current.ownerKey === ownerKey
      ? { ...current, loading: false, error: '' }
      : current)
  }, [ownerKey])

  return {
    articleLoading: visibleState.loading,
    articleError: visibleState.error,
    handleFetchFullArticle,
    resumeExistingFetch: attachToExistingFetch,
    cancelFetch,
  }
}
