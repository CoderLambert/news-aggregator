import { useState } from 'react'
import { fetchFullArticle } from '../services/api'

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
      }))
    } catch (err) {
      const msg = err.response?.data?.error || err.message || '获取失败'
      setArticleError(msg)
    } finally {
      setArticleLoading(false)
    }
  }

  return { articleLoading, articleError, handleFetchFullArticle }
}
