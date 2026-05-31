import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchSuggestedQuestions } from '../services/api'

/**
 * Lazy-loads LLM-generated suggested questions for an article. Cached per
 * newsId for the lifetime of the hook, so re-opening the chat panel doesn't
 * thrash the backend.
 *
 * Why "enabled" instead of always-on?
 *   The suggestion endpoint hits an LLM if the article doesn't have cached
 *   questions yet — that's a couple-second + tokens cost. Most readers never
 *   open the chat panel, so we hold the fetch until the panel is actually
 *   opened (enabled = isChatOpen).
 *
 * refresh():
 *   Imperative "换一批" — re-invokes the LLM with force=true on the backend
 *   to bypass the cache. On failure, the previous questions are preserved
 *   so the UI never goes blank. Caller can await it to drive a spinner.
 *
 * Caller falls back to the hardcoded default list if `questions` is empty —
 * see ChatMessageList for that behavior.
 */
export function useSuggestedQuestions(newsId, enabled) {
  const [questions, setQuestions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  // Tracks which newsIds we've already auto-fetched in this hook instance.
  // refresh() doesn't touch this set — it always re-fetches on demand.
  const fetchedFor = useRef(new Set())

  useEffect(() => {
    if (!enabled || !newsId) return
    if (fetchedFor.current.has(newsId)) return

    let cancelled = false
    fetchedFor.current.add(newsId)
    setLoading(true)
    setError(null)

    ;(async () => {
      try {
        const data = await fetchSuggestedQuestions(newsId)
        if (cancelled) return
        setQuestions(Array.isArray(data?.questions) ? data.questions : [])
      } catch (e) {
        if (cancelled) return
        setError(e)
        // Allow retry on next enable cycle for this newsId
        fetchedFor.current.delete(newsId)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [newsId, enabled])

  const refresh = useCallback(async () => {
    if (!newsId) return
    setLoading(true)
    setError(null)
    try {
      const data = await fetchSuggestedQuestions(newsId, { force: true })
      const next = Array.isArray(data?.questions) ? data.questions : []
      // Only overwrite when we actually got something — preserve old chips on empty.
      if (next.length > 0) setQuestions(next)
    } catch (e) {
      setError(e)
      // Intentionally keep existing questions — better stale than blank.
    } finally {
      setLoading(false)
    }
  }, [newsId])

  return { questions, loading, error, refresh }
}
