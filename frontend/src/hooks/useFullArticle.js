import { useState, useRef, useCallback } from 'react'
import { fetchFullArticle } from '../services/api'

const FULL_CONTENT_FETCH_FIELDS = [
  'full_content_fetch_status',
  'full_content_fetch_error',
  'full_content_fetch_provider',
  'full_content_quality_score',
  'full_content_retry_count',
  'last_full_content_attempt',
]

function pickFetchMetadata(data = {}) {
  return FULL_CONTENT_FETCH_FIELDS.reduce((acc, field) => {
    if (Object.prototype.hasOwnProperty.call(data, field)) acc[field] = data[field]
    return acc
  }, {})
}

/**
 * Trigger "fetch full article" via Jina Reader, merging response into news state.
 * Supports abort via AbortController so the user can cancel a stuck fetch.
 */
export function useFullArticle(id, setNews) {
  const [articleLoading, setArticleLoading] = useState(false)
  const [articleError, setArticleError] = useState('')
  const abortRef = useRef(null)

  async function handleFetchFullArticle(force = false) {
    // Abort any in-flight request first
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setArticleLoading(false)
      return
    }

    const controller = new AbortController()
    abortRef.current = controller

    setArticleLoading(true)
    setArticleError('')
    try {
      const data = await fetchFullArticle(id, force, controller.signal)
      setNews(prev => ({
        ...prev,
        full_content: data.full_content,
        full_content_fetched_at: data.full_content_fetched_at,
        // Invalidate translation when re-fetching — the content changed.
        ...(force ? { full_content_zh: '', full_content_zh_fetched_at: null } : {}),
        ...pickFetchMetadata(data),
      }))
    } catch (err) {
      if (err.name === 'AbortError' || err.name === 'CanceledError') {
        // User cancelled — treat as non-error
        return
      }
      const responseData = err.response?.data || {}
      const metadata = pickFetchMetadata(responseData)
      if (Object.keys(metadata).length > 0) {
        setNews(prev => ({
          ...prev,
          ...metadata,
        }))
      }
      const msg = responseData.error || err.message || '获取失败'
      setArticleError(msg)
    } finally {
      abortRef.current = null
      setArticleLoading(false)
    }
  }

  const cancelFetch = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setArticleLoading(false)
    }
  }, [])

  return { articleLoading, articleError, handleFetchFullArticle, cancelFetch }
}
