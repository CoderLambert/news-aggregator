import { useState, useEffect } from 'react'
import { fetchNewsDetail } from '../services/api'
import { useLanguage } from '../context/LanguageContext'

/**
 * Load news detail by id. Refetches on lang change so backend can swap
 * title_zh / content_zh as needed.
 *
 * Returns { news, setNews, loading } — caller mutates `news` directly when
 * fetching full content or applying streaming translation results.
 */
export function useNewsDetail(id) {
  const { lang } = useLanguage()
  const [news, setNews] = useState(null)
  const [loading, setLoading] = useState(true)

  // Initial load on id change
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchNewsDetail(id)
      .then(data => { if (!cancelled) setNews(data) })
      .catch(err => console.error('fetchNewsDetail:', err))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [id])

  // Refetch when language changes (post-mount only)
  useEffect(() => {
    if (loading || !news) return
    let cancelled = false
    fetchNewsDetail(id)
      .then(data => { if (!cancelled) setNews(data) })
      .catch(err => console.error('fetchNewsDetail(lang):', err))
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally only on lang
  }, [lang])

  return { news, setNews, loading }
}
