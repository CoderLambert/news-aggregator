import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import {
  SSE_PROGRESS_THROTTLE_MS,
  TRANSLATION_COMPLETE_MIN_LENGTH,
  translationPausedMarkerKey,
} from '@/constants'
import {
  cancelTranslationJob,
  getTranslationJob,
  translateFullArticleStream,
} from '@/services/newsWorkflowApi'
import { parseNewsId } from '@/services/newsWorkflowQueries'
import type { NewsDetail } from '@/types/news'
import { useCapability } from '@/context/CapabilitiesContext'

interface TranslationState {
  ownerKey: string
  translating: boolean
  waitingShared: boolean
  paused: boolean
  error: string
  progress: string
  showOriginal: boolean
}

interface TranslationRequest {
  ownerKey: string
  controller: AbortController
  jobId: string | null
  stopping: boolean
  cancelWhenIdentified: boolean
}

const EMPTY_TRANSLATION_STATE: TranslationState = {
  ownerKey: '', translating: false, waitingShared: false, paused: false, error: '', progress: '', showOriginal: false,
}

function translationRecoveryKey(viewerId: string | number, newsId: number): string {
  return `translating_recovery_v1:${encodeURIComponent(String(viewerId))}:${newsId}`
}

function saveTranslationRecovery(viewerId: string | number, newsId: number, jobId: string): void {
  try {
    localStorage.setItem(translationRecoveryKey(viewerId, newsId), JSON.stringify({
      viewerId: String(viewerId),
      newsId,
      jobId,
    }))
  } catch {
    // The active view can still recover while mounted if storage is unavailable.
  }
}

function loadTranslationRecovery(viewerId: string | number, newsId: number): string | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(translationRecoveryKey(viewerId, newsId)) ?? 'null')
    if (typeof value === 'object' && value !== null && 'viewerId' in value && 'newsId' in value &&
      'jobId' in value && value.viewerId === String(viewerId) && value.newsId === newsId &&
      typeof value.jobId === 'string' && value.jobId.length > 0) {
      return value.jobId
    }
  } catch {
    // Private recovery is optional if browser storage is blocked or malformed.
  }
  return null
}

function clearTranslationRecovery(viewerId: string | number, newsId: number): void {
  try {
    localStorage.removeItem(translationRecoveryKey(viewerId, newsId))
  } catch {
    // Storage is optional.
  }
}

function clearViewerTranslationRecovery(viewerId: string | number): void {
  const prefix = `translating_recovery_v1:${encodeURIComponent(String(viewerId))}:`
  try {
    const keys: string[] = []
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index)
      if (key?.startsWith(prefix)) keys.push(key)
    }
    keys.forEach((key) => localStorage.removeItem(key))
  } catch {
    // Owner-namespaced keys remain isolated if browser storage is unavailable.
  }
}


export function useTranslation(
  id: string | number | undefined,
  news: NewsDetail | null,
  setNews: Dispatch<SetStateAction<NewsDetail | null>>,
  loading: boolean,
) {
  const { user } = useAuth()
  const { lang } = useLanguage()
  const translationEnabled = useCapability('translation').enabled
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
  const previousViewerIdRef = useRef(viewerId)
  useEffect(() => {
    const previousViewerId = previousViewerIdRef.current
    if (previousViewerId === viewerId) return
    previousViewerIdRef.current = viewerId
    if (previousViewerId !== 'anonymous') clearViewerTranslationRecovery(previousViewerId)
  }, [viewerId])


  const updateState = useCallback((update: Partial<Omit<TranslationState, 'ownerKey'>>) => {
    if (ownerRef.current !== ownerKey) return
    setState((current) => ({
      ...(current.ownerKey === ownerKey ? current : { ...EMPTY_TRANSLATION_STATE, ownerKey }),
      ...update,
      ownerKey,
    }))
  }, [ownerKey])

  const finishExplicitStop = useCallback(async (
    request: TranslationRequest,
    activeViewerId: string | number,
    activeNewsId: number,
  ) => {
    if (!request.jobId) return
    let confirmed = false
    let succeeded = false
    let terminalStatus: string | null = null
    let outcomeMessage = '无法确认翻译任务已取消；可重新连接查看状态。'
    try {
      const current = await getTranslationJob(request.jobId, new AbortController().signal)
      const terminal = await cancelTranslationJob(request.jobId, current.generation)
      terminalStatus = terminal.status
      confirmed = ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(terminal.status)
      if (terminal.status === 'succeeded') {
        const translated = terminal.result.full_content_zh
        if (typeof translated === 'string') {
          setNews((previous) => previous && previous.id === activeNewsId
            ? {
                ...previous,
                full_content_zh: translated,
                full_content_zh_fetched_at: typeof terminal.result.full_content_zh_fetched_at === 'string'
                  ? terminal.result.full_content_zh_fetched_at : null,
                full_content_zh_scope: typeof terminal.result.full_content_zh_scope === 'string'
                  ? terminal.result.full_content_zh_scope : previous.full_content_zh_scope,
                full_content_zh_source: typeof terminal.result.full_content_zh_source === 'string'
                  ? terminal.result.full_content_zh_source : previous.full_content_zh_source,
                full_translation_active: false,
              }
            : previous)
          succeeded = true
          outcomeMessage = ''
        } else {
          outcomeMessage = '翻译任务已结束，但没有可用的完整译文。'
        }
      } else if (terminal.status === 'cancelled') {
        outcomeMessage = '本次翻译已取消；可以重新发起。'
      } else if (terminal.status === 'failed' || terminal.status === 'interrupted') {
        outcomeMessage = terminal.errorMessage || '翻译任务已结束；可以重新发起。'
      }
      if (confirmed) clearTranslationRecovery(activeViewerId, activeNewsId)
    } catch {
      confirmed = false
    } finally {
      if (requestRef.current === request) requestRef.current = null
      request.controller.abort()
      if (ownerRef.current === request.ownerKey) {
        if (pausedKey) {
          try {
            if (confirmed && succeeded) {
              localStorage.removeItem(pausedKey)
            } else {
              localStorage.setItem(pausedKey, JSON.stringify({
                stoppedAt: Date.now(),
                ...(confirmed ? { terminalStatus, message: outcomeMessage } : {}),
              }))
            }
          } catch {
            // Local UI state does not depend on storage.
          }
        }
        updateState({
          translating: false,
          paused: false,
          error: confirmed ? outcomeMessage : '无法确认翻译任务已取消；可重新连接查看状态。',
          progress: succeeded ? '' : progressRef.current,
        })
      }
    }
  }, [pausedKey, setNews, updateState])

  const handleTranslate = useCallback(async (force = false): Promise<boolean> => {
    if (!translationEnabled || newsId === null || !news || news.id !== newsId || !news.full_content) return false
    if (requestRef.current?.ownerKey === ownerKey) return false
    requestRef.current?.controller.abort()

    const storedJobId = force ? null : loadTranslationRecovery(viewerId, newsId)
    if (force) clearTranslationRecovery(viewerId, newsId)
    const request: TranslationRequest = {
      ownerKey,
      controller: new AbortController(),
      jobId: storedJobId,
      stopping: false,
      cancelWhenIdentified: false,
    }
    requestRef.current = request
    const isCurrent = () => requestRef.current === request && ownerRef.current === ownerKey
    autoResumeArticleRef.current = ownerKey
    progressRef.current = ''
    lastProgressUpdateRef.current = 0
    if (pausedKey) localStorage.removeItem(pausedKey)
    updateState({ translating: true, waitingShared: false, paused: false, error: '', progress: '' })

    const applyStoredResult = (result: Record<string, unknown>) => {
      if (typeof result.full_content_zh !== 'string') return false
      setNews((previous) => previous && previous.id === newsId
        ? {
            ...previous,
            full_content_zh: result.full_content_zh as string,
            full_content_zh_fetched_at: typeof result.full_content_zh_fetched_at === 'string'
              ? result.full_content_zh_fetched_at : null,
            full_content_zh_scope: typeof result.full_content_zh_scope === 'string'
              ? result.full_content_zh_scope : previous.full_content_zh_scope,
            full_content_zh_source: typeof result.full_content_zh_source === 'string'
              ? result.full_content_zh_source : previous.full_content_zh_source,
            full_translation_active: false,
          }
        : previous)
      clearTranslationRecovery(viewerId, newsId)
      updateState({ translating: false, paused: false, error: '', progress: '' })
      return true
    }

    try {
      if (storedJobId) {
        const storedTask = await getTranslationJob(storedJobId, request.controller.signal)
        if (!isCurrent()) return false
        progressRef.current = storedTask.progress
        if (storedTask.progress) updateState({ progress: storedTask.progress })
        if (storedTask.status === 'succeeded' && applyStoredResult(storedTask.result)) return true
        if (['failed', 'cancelled', 'interrupted', 'succeeded'].includes(storedTask.status)) {
          clearTranslationRecovery(viewerId, newsId)
          updateState({
            translating: false,
            paused: false,
            error: storedTask.errorMessage || '翻译任务已结束，请明确重试。',
          })
          return false
        }
      }

      for await (const event of translateFullArticleStream(newsId, {
        force,
        signal: request.controller.signal,
        onJobId: (jobId) => {
          if (!isCurrent()) return
          request.jobId = jobId
          saveTranslationRecovery(viewerId, newsId, jobId)
          if (request.cancelWhenIdentified) {
            void finishExplicitStop(request, viewerId, newsId)
          }
        },
      })) {
        if (!isCurrent()) return false
        if (request.stopping && (request.jobId !== null || event.type !== 'complete')) continue
        if (event.type === 'waiting_shared') {
          updateState({ waitingShared: true })
          continue
        }
        if (event.type === 'error') {
          updateState({ translating: false, paused: false, error: event.message })
          return false
        }
        if (event.type === 'complete') {
          setNews((previous) => previous && previous.id === newsId
            ? { ...previous, full_content_zh: event.fullContentZh, full_content_zh_fetched_at: event.fetchedAt,
              full_content_zh_scope: event.scope ?? previous.full_content_zh_scope,
              full_content_zh_source: event.source ?? previous.full_content_zh_source,
              full_translation_active: false }
            : previous)
          clearTranslationRecovery(viewerId, newsId)
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
      if (request.stopping && !request.jobId) {
        if (requestRef.current === request) requestRef.current = null
        request.controller.abort()
        if (pausedKey) localStorage.setItem(pausedKey, JSON.stringify({ stoppedAt: Date.now() }))
        updateState({ translating: false, paused: true, error: '' })
        return false
      }
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
  }, [finishExplicitStop, news, newsId, ownerKey, pausedKey, setNews, translationEnabled, updateState, viewerId])

  const cancelTranslation = useCallback(async () => {
    const request = requestRef.current
    if (!request || request.ownerKey !== ownerKey) return
    request.stopping = true
    if (newsId === null) {
      requestRef.current = null
      request.controller.abort()
      return
    }
    if (!request.jobId) {
      request.cancelWhenIdentified = true
      return
    }
    await finishExplicitStop(request, viewerId, newsId)
  }, [finishExplicitStop, newsId, ownerKey, viewerId])

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
    if (translationEnabled) return
    const request = requestRef.current
    if (request?.ownerKey === ownerKey) {
      requestRef.current = null
      request.controller.abort()
    }
    autoResumeArticleRef.current = ''
    updateState({ translating: false, waitingShared: false, error: '', progress: '' })
  }, [ownerKey, translationEnabled, updateState])

  useEffect(() => {
    if (!translationEnabled || loading || !news || news.id !== newsId || autoResumeArticleRef.current === ownerKey) return
    autoResumeArticleRef.current = ownerKey

    const storedJobId = newsId === null ? null : loadTranslationRecovery(viewerId, newsId)
    if (storedJobId) {
      void handleTranslate(false)
      return
    }

    const paused = pausedKey ? localStorage.getItem(pausedKey) : null
    if (paused) {
      let terminalStatus: string | null = null
      let terminalMessage = ''
      try {
        const marker: unknown = JSON.parse(paused)
        if (typeof marker === 'object' && marker !== null && 'terminalStatus' in marker) {
          if (typeof marker.terminalStatus === 'string') terminalStatus = marker.terminalStatus
          if ('message' in marker && typeof marker.message === 'string') terminalMessage = marker.message
        }
      } catch {
        // Legacy pause markers contain only a timestamp.
      }
      if (terminalStatus && ['cancelled', 'failed', 'interrupted', 'succeeded'].includes(terminalStatus)) {
        updateState({
          translating: false,
          paused: false,
          error: terminalMessage || '翻译任务已结束；可以重新发起。',
        })
        return
      }
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
  }, [handleTranslate, loading, news, newsId, ownerKey, pausedKey, translationEnabled, updateState, viewerId])

  return {
    translating: visibleState.translating,
    translationWaitingShared: visibleState.waitingShared,
    translationPaused: visibleState.paused,
    translateError: visibleState.error,
    translationProgress: visibleState.progress,
    showOriginal: visibleState.showOriginal,
    setShowOriginal,
    handleTranslate,
    cancelTranslation,
  }
}
