import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import { fetchFullArticle, parseFullArticleFailure } from '@/services/newsWorkflowApi'
import { parseNewsId } from '@/services/newsWorkflowQueries'
import type { NewsDetail } from '@/types/news'

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

export function useFullArticle(
  id: string | number | undefined,
  setNews: Dispatch<SetStateAction<NewsDetail | null>>,
) {
  const { user } = useAuth()
  const { lang } = useLanguage()
  const newsId = parseNewsId(id)
  const ownerKey = `${newsId ?? String(id ?? '')}:${user?.id ?? 'anonymous'}:${lang}`
  const ownerRef = useRef(ownerKey)
  const requestRef = useRef<FetchRequest | null>(null)
  const [state, setState] = useState(EMPTY_FETCH_STATE)
  const visibleState = state.ownerKey === ownerKey ? state : EMPTY_FETCH_STATE

  useLayoutEffect(() => { ownerRef.current = ownerKey }, [ownerKey])

  useEffect(() => () => {
    if (requestRef.current?.ownerKey === ownerKey) {
      requestRef.current.controller.abort()
      requestRef.current = null
    }
  }, [ownerKey])

  const handleFetchFullArticle = useCallback(async (force = false): Promise<boolean> => {
    if (newsId === null) return false
    if (requestRef.current?.ownerKey === ownerKey) return false
    requestRef.current?.controller.abort()

    const request: FetchRequest = { ownerKey, controller: new AbortController() }
    requestRef.current = request
    const isCurrent = () => requestRef.current === request && ownerRef.current === ownerKey
    setState({ ownerKey, loading: true, error: '' })

    try {
      const data = await fetchFullArticle(newsId, force, request.controller.signal)
      if (!isCurrent()) return false
      setNews((previous) => {
        if (!previous || previous.id !== newsId) return previous
        return {
          ...previous,
          full_content: data.full_content,
          ...(data.full_content_fetched_at !== undefined ? { full_content_fetched_at: data.full_content_fetched_at } : {}),
          ...(force ? { full_content_zh: '', full_content_zh_fetched_at: null } : {}),
          ...(data.full_content_fetch_status !== undefined ? { full_content_fetch_status: data.full_content_fetch_status } : {}),
          ...(data.full_content_fetch_error !== undefined ? { full_content_fetch_error: data.full_content_fetch_error } : {}),
          ...(data.full_content_fetch_provider !== undefined ? { full_content_fetch_provider: data.full_content_fetch_provider } : {}),
          ...(data.full_content_quality_score !== undefined ? { full_content_quality_score: data.full_content_quality_score } : {}),
          ...(data.full_content_retry_count !== undefined ? { full_content_retry_count: data.full_content_retry_count } : {}),
          ...(data.last_full_content_attempt !== undefined ? { last_full_content_attempt: data.last_full_content_attempt } : {}),
        }
      })
      return true
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
  }, [newsId, ownerKey, setNews])

  const cancelFetch = useCallback(() => {
    const request = requestRef.current
    if (!request || request.ownerKey !== ownerKey) return
    requestRef.current = null
    request.controller.abort()
    setState((current) => current.ownerKey === ownerKey
      ? { ...current, loading: false }
      : current)
  }, [ownerKey])

  return {
    articleLoading: visibleState.loading,
    articleError: visibleState.error,
    handleFetchFullArticle,
    cancelFetch,
  }
}
