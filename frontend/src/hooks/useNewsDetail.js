import { useState, useEffect } from 'react'
import { fetchNewsDetail } from '../services/api'
import { useLanguage } from '../context/useLanguage'

/**
 * Load news detail by id. Refetches on lang change so backend can swap
 * title_zh / content_zh as needed.
 *
 * Returns { news, setNews, loading } — caller mutates `news` directly when
 * fetching full content or applying streaming translation results.
 *
 * Resets (setNews(null) / setLoading(true)) happen inside async IIFEs so
 * they fire on a microtask boundary, not synchronously in the effect body
 * (per React 19's react-hooks/set-state-in-effect rule).
 */
export function useNewsDetail(id) {
  const { lang } = useLanguage()
  const [news, setNews] = useState(null)
  const [loading, setLoading] = useState(true)

  // Initial load on id change
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const data = await fetchNewsDetail(id)
        if (!cancelled) setNews(data)
      } catch (err) {
        if (!cancelled) console.error('fetchNewsDetail:', err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [id])

  // Refetch when language changes (post-mount only). We skip the very first
  // run because the id-effect already fetched. `news` being null on first
  // render means we haven't loaded yet — let the id-effect own that path.
  useEffect(() => {
    if (!news) return
    let cancelled = false
    ;(async () => {
      try {
        const data = await fetchNewsDetail(id)
        if (!cancelled) setNews(data)
      } catch (err) {
        if (!cancelled) console.error('fetchNewsDetail(lang):', err)
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally only on lang
  }, [lang])

  return { news, setNews, loading }
}
