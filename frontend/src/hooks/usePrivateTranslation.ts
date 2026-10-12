import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useAuth } from '@/context/AuthContext'
import {
  cancelPrivateTranslationJob,
  getPrivateTranslationJob,
  translatePrivateFullArticleStream,
} from '@/services/newsWorkflowApi'
import { parseNewsId } from '@/services/newsWorkflowQueries'
import { isRecord, type NewsDetail } from '@/types/news'

interface PrivateTranslationState {
  ownerKey: string
  active: boolean
  error: string
  progress: string
  result: string
  resultId: string
  jobId: string
}

interface PrivateTranslationRequest {
  ownerKey: string
  controller: AbortController
  jobId: string | null
}

const EMPTY_STATE: PrivateTranslationState = {
  ownerKey: '', active: false, error: '', progress: '', result: '', resultId: '', jobId: '',
}

function recoveryKey(viewerId: string | number, newsId: number): string {
  return `byok_translation_recovery_v1:${encodeURIComponent(String(viewerId))}:${newsId}`
}

function readRecovery(viewerId: string | number, newsId: number): string | null {
  try {
    const id = localStorage.getItem(recoveryKey(viewerId, newsId))
    return id && /^[0-9a-f-]{36}$/i.test(id) ? id : null
  } catch {
    return null
  }
}

function saveRecovery(viewerId: string | number, newsId: number, jobId: string): void {
  try {
    localStorage.setItem(recoveryKey(viewerId, newsId), jobId)
  } catch {
    // Private results remain available from the active task response.
  }
}

function resultFromTask(task: { result: Record<string, unknown> }): { text: string; id: string } | null {
  const text = task.result.full_content_zh
  const id = task.result.result_id
  return typeof text === 'string' && text.trim() && typeof id === 'string'
    ? { text, id }
    : null
}

function sleep(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve()
    const onAbort = () => {
      clearTimeout(timer)
      resolve()
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, milliseconds)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

function safeErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) return fallback
  try {
    const parsed: unknown = JSON.parse(error.message)
    if (isRecord(parsed) && typeof parsed.error === 'string') return parsed.error
  } catch {
    // Streaming transport errors may already be safe plain text.
  }
  return error.message || fallback
}

export function usePrivateTranslation(
  id: string | number | undefined,
  news: NewsDetail | null,
  enabled: boolean,
  loading: boolean,
) {
  const { user } = useAuth()
  const newsId = parseNewsId(id)
  const viewerId = user?.id ?? 'anonymous'
  const isAuthenticated = Boolean(user)
  const ownerKey = `${newsId ?? String(id ?? '')}:${viewerId}`
  const ownerRef = useRef(ownerKey)
  const requestRef = useRef<PrivateTranslationRequest | null>(null)
  const [state, setState] = useState(EMPTY_STATE)
  const visible = state.ownerKey === ownerKey ? state : EMPTY_STATE

  useLayoutEffect(() => { ownerRef.current = ownerKey }, [ownerKey])

  const updateState = useCallback((update: Partial<Omit<PrivateTranslationState, 'ownerKey'>>) => {
    if (ownerRef.current !== ownerKey) return
    setState((current) => ({
      ...(current.ownerKey === ownerKey ? current : { ...EMPTY_STATE, ownerKey }),
      ...update,
      ownerKey,
    }))
  }, [ownerKey])

  const finishFromTask = useCallback((task: Awaited<ReturnType<typeof getPrivateTranslationJob>>) => {
    const completedResult = task.status === 'succeeded' ? resultFromTask(task) : null
    updateState({
      active: false,
      progress: task.progress,
      jobId: task.id,
      ...(completedResult
        ? { result: completedResult.text, resultId: completedResult.id, error: '' }
        : task.status === 'succeeded'
          ? { result: '', resultId: '', error: '翻译任务结束，但没有可恢复的完整译文。' }
          : { error: task.errorMessage || (task.status === 'cancelled' ? '本次个人翻译已取消。' : '个人翻译任务未完成。') }),
    })
  }, [updateState])

  const followTask = useCallback(async (
    jobId: string,
    controller: AbortController,
    request: PrivateTranslationRequest,
  ) => {
    try {
      while (!controller.signal.aborted && requestRef.current === request && ownerRef.current === ownerKey) {
        const task = await getPrivateTranslationJob(jobId, controller.signal)
        if (controller.signal.aborted || requestRef.current !== request || ownerRef.current !== ownerKey) return
        updateState({ active: ['queued', 'running'].includes(task.status), progress: task.progress, jobId: task.id })
        if (!['queued', 'running'].includes(task.status)) {
          finishFromTask(task)
          return
        }
        await sleep(1200, controller.signal)
      }
    } catch (error: unknown) {
      if (controller.signal.aborted) return
      updateState({ active: false, error: safeErrorMessage(error, '无法读取个人翻译任务。') })
    } finally {
      if (requestRef.current === request) requestRef.current = null
    }
  }, [finishFromTask, ownerKey, updateState])

  useEffect(() => {
    if (!enabled || loading || !isAuthenticated || newsId === null || news?.id !== newsId) return
    const storedJobId = readRecovery(viewerId, newsId)
    if (!storedJobId) return
    const request: PrivateTranslationRequest = {
      ownerKey,
      controller: new AbortController(),
      jobId: storedJobId,
    }
    requestRef.current?.controller.abort()
    requestRef.current = request
    updateState({ active: true, error: '', jobId: storedJobId })
    void followTask(storedJobId, request.controller, request)
    return () => {
      if (requestRef.current === request) {
        request.controller.abort()
        requestRef.current = null
      }
    }
  }, [enabled, followTask, isAuthenticated, loading, news?.id, newsId, ownerKey, updateState, viewerId])

  const startPrivateTranslation = useCallback(async () => {
    if (!enabled || !isAuthenticated || newsId === null || !news || news.id !== newsId || !news.full_content) return
    requestRef.current?.controller.abort()
    const controller = new AbortController()
    const request: PrivateTranslationRequest = { ownerKey, controller, jobId: null }
    requestRef.current = request
    const cryptoApi = globalThis.crypto
    const idempotencyKey = cryptoApi?.randomUUID
      ? cryptoApi.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    updateState({ active: true, error: '', progress: '', jobId: '' })

    try {
      let terminal = false
      for await (const event of translatePrivateFullArticleStream(newsId, idempotencyKey, {
        signal: controller.signal,
        onJobId: (jobId) => {
          if (requestRef.current !== request || ownerRef.current !== ownerKey) return
          request.jobId = jobId
          saveRecovery(viewerId, newsId, jobId)
          updateState({ jobId })
        },
      })) {
        if (controller.signal.aborted || requestRef.current !== request || ownerRef.current !== ownerKey) return
        if (event.type === 'progress') {
          updateState({ progress: event.text })
        } else if (event.type === 'error') {
          terminal = true
          updateState({ active: false, error: event.message })
        } else if (event.type === 'complete') {
          const result = resultFromTask({ result: event.result })
          terminal = true
          if (!result) {
            updateState({ active: false, error: '个人翻译没有返回可保存的完整译文。' })
          } else {
            updateState({ active: false, error: '', result: result.text, resultId: result.id })
          }
        }
      }
      if (!terminal && request.jobId && !controller.signal.aborted) {
        await followTask(request.jobId, controller, request)
      } else if (!terminal && !controller.signal.aborted) {
        updateState({ active: false, error: '无法确认个人翻译任务状态；请查看任务后再决定是否重试。' })
      }
    } catch (error: unknown) {
      if (!controller.signal.aborted) {
        updateState({ active: false, error: safeErrorMessage(error, '个人翻译失败。') })
      }
    } finally {
      if (requestRef.current === request) requestRef.current = null
    }
  }, [enabled, followTask, isAuthenticated, news, newsId, ownerKey, updateState, viewerId])

  const cancelPrivateTranslation = useCallback(async () => {
    const request = requestRef.current
    if (!request || request.ownerKey !== ownerKey || !request.jobId) return
    try {
      const current = await getPrivateTranslationJob(request.jobId, new AbortController().signal)
      const terminal = await cancelPrivateTranslationJob(request.jobId, current.generation)
      request.controller.abort()
      requestRef.current = null
      if (terminal.status === 'succeeded') finishFromTask(terminal)
      else updateState({ active: false, error: terminal.errorMessage || '本次个人翻译已取消。' })
    } catch (error: unknown) {
      updateState({ active: false, error: safeErrorMessage(error, '无法取消个人翻译任务。') })
    }
  }, [finishFromTask, ownerKey, updateState])

  useEffect(() => () => {
    if (requestRef.current?.ownerKey === ownerKey) {
      requestRef.current.controller.abort()
      requestRef.current = null
    }
  }, [ownerKey])

  return {
    privateTranslationActive: visible.active,
    privateTranslationError: visible.error,
    privateTranslationProgress: visible.progress,
    privateTranslationResult: visible.result,
    privateTranslationResultId: visible.resultId,
    privateTranslationJobId: visible.jobId,
    startPrivateTranslation,
    cancelPrivateTranslation,
  }
}
