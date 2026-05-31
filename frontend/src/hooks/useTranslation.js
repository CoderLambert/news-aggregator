import { useState, useEffect, useRef } from 'react'
import { translateFullArticleStream } from '../services/api'
import {
  translatingMarkerKey,
  TRANSLATING_MARKER_TTL_MS,
  TRANSLATION_COMPLETE_MIN_LENGTH,
  SSE_PROGRESS_THROTTLE_MS,
} from '../constants'

/**
 * Translation lifecycle hook.
 *
 * @param {string}  id   — article id
 * @param {object}  news — current news state (read-only for marker checks)
 * @param {(fn: (prev: object) => object) => void} setNews — updater for news state
 * @param {boolean} loading — whether the article is still being fetched
 */
export function useTranslation(id, news, setNews, loading) {
  const [translating, setTranslating] = useState(false)
  const [translateError, setTranslateError] = useState('')
  const [translationProgress, setTranslationProgress] = useState('')
  const [showOriginal, setShowOriginal] = useState(false)

  const autoResumedRef = useRef(false)
  const progressRef = useRef('')
  const lastProgressUpdateRef = useRef(0)

  // ---- Auto-resume after page refresh / first visit ------------------------
  // Two attach paths:
  //   (a) Backend says full_translation_active === true → a worker is still
  //       running. We attach via SSE regardless of who started it (works
  //       across devices, incognito, link-shared URLs, list→detail nav).
  //   (b) localStorage marker present (started in THIS browser, may have been
  //       a brief gap before the server flag came back true). Keeps the
  //       existing single-device refresh flow snappy.
  useEffect(() => {
    if (loading || !news || autoResumedRef.current) return

    const markerKey = translatingMarkerKey(id)
    const marker = localStorage.getItem(markerKey)

    // Path (a): authoritative backend signal
    if (news.full_translation_active && !news.full_content_zh?.length) {
      autoResumedRef.current = true
      console.log('Backend reports active translation — attaching to SSE stream...')
      handleTranslate(false)
      return
    }
    if (news.full_translation_active && news.full_content_zh) {
      // Worker still running but already has some saved progress — attach
      // to keep receiving live updates as they come in.
      autoResumedRef.current = true
      console.log('Active translation with partial content — live-attaching...')
      handleTranslate(false)
      return
    }

    // Path (b): local marker fallback (same-browser refresh in the brief
    // window before serializer reflects the new job).
    if (marker && news.full_content && !news.full_content_zh) {
      try {
        const { startedAt } = JSON.parse(marker)
        if (Date.now() - startedAt < TRANSLATING_MARKER_TTL_MS) {
          autoResumedRef.current = true
          console.log('Local marker found — reattaching to translation...')
          handleTranslate(false)
        } else {
          localStorage.removeItem(markerKey)
        }
      } catch {
        localStorage.removeItem(markerKey)
      }
    } else if (marker && news.full_content_zh && news.full_content_zh.length > TRANSLATION_COMPLETE_MIN_LENGTH) {
      localStorage.removeItem(markerKey)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- guarded by autoResumedRef; we react to news arriving
  }, [news, loading])

  // ---- Cleanup stale markers ------------------------------------------------
  useEffect(() => {
    if (!news) return
    const markerKey = translatingMarkerKey(id)
    const marker = localStorage.getItem(markerKey)
    if (!marker) return
    try {
      const { startedAt } = JSON.parse(marker)
      if (
        Date.now() - startedAt > TRANSLATING_MARKER_TTL_MS ||
        (news.full_content_zh && news.full_content_zh.length > TRANSLATION_COMPLETE_MIN_LENGTH)
      ) {
        localStorage.removeItem(markerKey)
      }
    } catch {
      localStorage.removeItem(markerKey)
    }
  }, [news, id])

  // ---- Translate handler ----------------------------------------------------
  async function handleTranslate(force = false) {
    setTranslating(true)
    setTranslateError('')
    setTranslationProgress('')
    progressRef.current = ''
    lastProgressUpdateRef.current = 0

    localStorage.setItem(translatingMarkerKey(id), JSON.stringify({ startedAt: Date.now() }))
    // Only clear existing translation when user explicitly forces a re-translate.
    // On reattach (force=false), keep what's already on screen so the user sees
    // the saved progress immediately and the stream picks up from there.
    if (force) {
      setNews(prev => ({ ...prev, full_content_zh: '' }))
    }

    try {
      for await (const ev of translateFullArticleStream(id, { force })) {
        if (ev.full_content_zh) {
          setNews(prev => ({
            ...prev,
            full_content_zh: ev.full_content_zh,
            full_content_zh_fetched_at: ev.full_content_zh_fetched_at,
          }))
          setTranslationProgress('')
          setTranslating(false)
          localStorage.removeItem(translatingMarkerKey(id))
          return
        }
        if (ev.progress !== undefined) {
          progressRef.current = ev.progress
          const now = Date.now()
          if (now - lastProgressUpdateRef.current > SSE_PROGRESS_THROTTLE_MS) {
            lastProgressUpdateRef.current = now
            setTranslationProgress(ev.progress)
          }
        }
      }
      // Stream ended without final payload — flush pending progress
      if (progressRef.current) {
        setTranslationProgress(progressRef.current)
      }
    } catch (err) {
      console.error('Translation failed:', err)
      setTranslateError(err.message || '翻译失败')
      setTranslating(false)
    }
  }

  return {
    translating,
    translateError,
    translationProgress,
    showOriginal,
    setShowOriginal,
    handleTranslate,
  }
}
