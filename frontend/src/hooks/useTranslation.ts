import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import {
  SSE_PROGRESS_THROTTLE_MS,
  TRANSLATION_COMPLETE_MIN_LENGTH,
  translationPausedMarkerKey,
} from '@/constants'
import { translateFullArticleStream } from '@/services/newsWorkflowApi'
import { parseNewsId } from '@/services/newsWorkflowQueries'
import type { NewsDetail } from '@/types/news'

interface TranslationState {
  ownerKey: string
  translating: boolean
  paused: boolean
  error: string
  progress: string
  showOriginal: boolean
}

interface TranslationRequest {
  ownerKey: string
  controller: AbortController
}

const EMPTY_TRANSLATION_STATE: TranslationState = {
  ownerKey: '', translating: false, paused: false, error: '', progress: '', showOriginal: false,
}

export function useTranslation(
  id: string | number | undefined,
  news: NewsDetail | null,
  setNews: Dispatch<SetStateAction<NewsDetail | null>>,
  loading: boolean,
) {
  const { user } = useAuth()
  const { lang } = useLanguage()
  const newsId = parseNewsId(id)
  const viewerId = user?.id ?? 'anonymous'
  const ownerKey = `${newsId ?? String(id ?? '')}:${viewerId}:${lang}`
  const pausedKey = newsId === null ? '' : translationPausedMarkerKey(newsId, viewerId, lang)
  const ownerRef = useRef(ownerKey)
  const requestRef = useRef<TranslationRequest | null>(null)
  const autoResumeArticleRef = useRef('')
  const progressRef = useRef('')
  const lastProgressUpdateRef = useRef(0)
  const [state, setState] = useState(EMPTY_TRANSLATION_STATE)
  const visibleState = state.ownerKey === ownerKey ? state : EMPTY_TRANSLATION_STATE

  useLayoutEffect(() => { ownerRef.current = ownerKey }, [ownerKey])

  const updateState = useCallback((update: Partial<Omit<TranslationState, 'ownerKey'>>) => {
    if (ownerRef.current !== ownerKey) return
    setState((current) => ({
      ...(current.ownerKey === ownerKey ? current : { ...EMPTY_TRANSLATION_STATE, ownerKey }),
      ...update,
      ownerKey,
    }))
  }, [ownerKey])

  const handleTranslate = useCallback(async (force = false): Promise<boolean> => {
    if (newsId === null || !news || news.id !== newsId || !news.full_content) return false
    if (requestRef.current?.ownerKey === ownerKey) return false
    requestRef.current?.controller.abort()

    const request: TranslationRequest = { ownerKey, controller: new AbortController() }
    requestRef.current = request
    const isCurrent = () => requestRef.current === request && ownerRef.current === ownerKey
    autoResumeArticleRef.current = ownerKey
    progressRef.current = ''
    lastProgressUpdateRef.current = 0
    if (pausedKey) localStorage.removeItem(pausedKey)
    updateState({ translating: true, paused: false, error: '', progress: '' })

    try {
      for await (const event of translateFullArticleStream(newsId, { force, signal: request.controller.signal })) {
        if (!isCurrent()) return false
        if (event.type === 'error') {
          updateState({ translating: false, paused: false, error: event.message })
          return false
        }
        if (event.type === 'complete') {
          setNews((previous) => previous && previous.id === newsId
            ? { ...previous, full_content_zh: event.fullContentZh, full_content_zh_fetched_at: event.fetchedAt }
            : previous)
          if (pausedKey) localStorage.removeItem(pausedKey)
          updateState({ translating: false, paused: false, error: '', progress: '' })
          return true
        }
        if (event.type === 'progress') {
          progressRef.current = event.text
          const now = Date.now()
          if (now - lastProgressUpdateRef.current >= SSE_PROGRESS_THROTTLE_MS) {
            lastProgressUpdateRef.current = now
            updateState({ progress: event.text })
          }
        }
      }

      if (!isCurrent()) return false
      if (progressRef.current) updateState({ progress: progressRef.current })
      if (pausedKey) localStorage.setItem(pausedKey, JSON.stringify({ stoppedAt: Date.now() }))
      updateState({ translating: false, paused: true, error: '' })
      return false
    } catch (error: unknown) {
      if (!isCurrent() || request.controller.signal.aborted) return false
      const message = error instanceof Error ? error.message : '翻译失败'
      updateState({ translating: false, paused: false, error: message })
      return false
    } finally {
      if (isCurrent()) requestRef.current = null
    }
  }, [news, newsId, ownerKey, pausedKey, setNews, updateState])

  const stopTranslationWait = useCallback(() => {
    const request = requestRef.current
    if (!request || request.ownerKey !== ownerKey) return
    requestRef.current = null
    request.controller.abort()
    if (pausedKey) localStorage.setItem(pausedKey, JSON.stringify({ stoppedAt: Date.now() }))
    updateState({ translating: false, paused: true, error: '' })
  }, [ownerKey, pausedKey, updateState])

  const setShowOriginal = useCallback((showOriginal: boolean) => {
    updateState({ showOriginal })
  }, [updateState])

  useEffect(() => () => {
    if (requestRef.current?.ownerKey === ownerKey) {
      requestRef.current.controller.abort()
      requestRef.current = null
    }
    progressRef.current = ''
    lastProgressUpdateRef.current = 0
    if (autoResumeArticleRef.current === ownerKey) autoResumeArticleRef.current = ''
    setState((current) => current.ownerKey === ownerKey ? EMPTY_TRANSLATION_STATE : current)
  }, [ownerKey])

  useEffect(() => {
    if (loading || !news || news.id !== newsId || autoResumeArticleRef.current === ownerKey) return
    autoResumeArticleRef.current = ownerKey

    const paused = pausedKey ? localStorage.getItem(pausedKey) : null
    if (paused) {
      const completed = !news.full_translation_active &&
        (news.full_content_zh?.length ?? 0) > TRANSLATION_COMPLETE_MIN_LENGTH
      if (completed && pausedKey) localStorage.removeItem(pausedKey)
      else {
        updateState({ translating: false, paused: true })
        return
      }
    }

    if (news.full_translation_active) {
      void handleTranslate(false)
    }
  }, [handleTranslate, loading, news, newsId, ownerKey, pausedKey, updateState])

  return {
    translating: visibleState.translating,
    translationPaused: visibleState.paused,
    translateError: visibleState.error,
    translationProgress: visibleState.progress,
    showOriginal: visibleState.showOriginal,
    setShowOriginal,
    handleTranslate,
    stopTranslationWait,
  }
}
