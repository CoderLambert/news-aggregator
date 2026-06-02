import { useState } from 'react'
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
 */
export function useFullArticle(id, setNews) {
  const [articleLoading, setArticleLoading] = useState(false)
  const [articleError, setArticleError] = useState('')

  async function handleFetchFullArticle() {
    setArticleLoading(true)
    setArticleError('')
    try {
      const data = await fetchFullArticle(id)
      setNews(prev => ({
        ...prev,
        full_content: data.full_content,
        full_content_fetched_at: data.full_content_fetched_at,
        ...pickFetchMetadata(data),
      }))
    } catch (err) {
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
      setArticleLoading(false)
    }
  }

  return { articleLoading, articleError, handleFetchFullArticle }
}
