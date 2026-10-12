import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useAuth } from '@/context/AuthContext'
import {
  cancelPrivateTranslationJob,
  getPrivateTranslationResult,
  getPrivateTranslationJob,
  translatePrivateFullArticleStream,
  type PrivateTranslationResult,
} from '@/services/newsWorkflowApi'
import { parseNewsId } from '@/services/newsWorkflowQueries'
import { isRecord, type NewsDetail } from '@/types/news'

interface PrivateTranslationState {
  ownerKey: string
  sourceKey: string
  active: boolean
  cancelPending: boolean
  error: string
  progress: string
  result: string
  resultId: string
  resultCurrentMatch: boolean | null
  jobId: string
}

interface PrivateTranslationRequest {
  ownerKey: string
  sourceKey: string
  controller: AbortController
  jobId: string | null
}

const EMPTY_STATE: PrivateTranslationState = {
  ownerKey: '', sourceKey: '', active: false, cancelPending: false, error: '', progress: '', result: '', resultId: '', resultCurrentMatch: null, jobId: '',
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

function clearRecovery(viewerId: string | number, newsId: number): void {
  try {
    localStorage.removeItem(recoveryKey(viewerId, newsId))
  } catch {
    // Recovery storage is best effort.
  }
}

function resultFromTask(task: { result: Record<string, unknown> }): { text: string; id: string; currentMatch: boolean } | null {
  const text = task.result.full_content_zh
  const id = task.result.result_id
  return typeof text === 'string' && text.trim() && typeof id === 'string'
    ? { text, id, currentMatch: task.result.current_match === true }
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
  const sourceKey = news?.full_content ?? ''
  const ownerRef = useRef(ownerKey)
  const sourceRef = useRef(sourceKey)
  const requestRef = useRef<PrivateTranslationRequest | null>(null)
  const [state, setState] = useState(EMPTY_STATE)
  const [staleResult, setStaleResult] = useState<{ ownerKey: string; resultId: string; result: PrivateTranslationResult } | null>(null)
  const visible = state.ownerKey === ownerKey && state.sourceKey === sourceKey ? state : EMPTY_STATE
  const visibleStaleResult = staleResult?.ownerKey === ownerKey &&
    staleResult.resultId === news?.full_content_zh_stale_result_id
    ? staleResult.result
    : null

  useLayoutEffect(() => {
    ownerRef.current = ownerKey
    if (sourceRef.current === sourceKey) return
    sourceRef.current = sourceKey
    const request = requestRef.current
    if (request?.ownerKey === ownerKey) {
      requestRef.current = null
      request.controller.abort()
    }
    setState((current) => current.ownerKey === ownerKey
      ? { ...EMPTY_STATE, ownerKey, sourceKey }
      : current)
  }, [ownerKey, sourceKey])

  const updateState = useCallback((update: Partial<Omit<PrivateTranslationState, 'ownerKey'>>) => {
    if (ownerRef.current !== ownerKey || sourceRef.current !== sourceKey) return
    setState((current) => ({
      ...(current.ownerKey === ownerKey && current.sourceKey === sourceKey ? current : { ...EMPTY_STATE, ownerKey, sourceKey }),
      ...update,
      ownerKey,
      sourceKey,
    }))
  }, [ownerKey, sourceKey])

  const finishFromTask = useCallback((task: Awaited<ReturnType<typeof getPrivateTranslationJob>>) => {
    const completedResult = task.status === 'succeeded' ? resultFromTask(task) : null
    updateState({
      active: false,
      cancelPending: false,
      progress: task.progress,
      jobId: task.id,
      ...(completedResult
        ? { result: completedResult.text, resultId: completedResult.id, resultCurrentMatch: completedResult.currentMatch, error: '' }
        : task.status === 'succeeded'
          ? { result: '', resultId: '', resultCurrentMatch: null, error: '翻译任务结束，但没有可恢复的完整译文。' }
          : { error: task.errorMessage || (task.status === 'cancelled' ? '本次个人翻译已取消。' : '个人翻译任务未完成。') }),
    })
  }, [updateState])

  const finishRequestFromTask = useCallback((
    request: PrivateTranslationRequest,
    task: Awaited<ReturnType<typeof getPrivateTranslationJob>>,
  ) => {
    if (newsId !== null) clearRecovery(viewerId, newsId)
    if (requestRef.current === request) requestRef.current = null
    request.controller.abort()
    finishFromTask(task)
  }, [finishFromTask, newsId, viewerId])

  const getCurrentTaskRequest = useCallback(() => {
    const current = requestRef.current
    if (current?.ownerKey === ownerKey && current.sourceKey === sourceKey && current.jobId) return current
    if (!visible.active || !visible.jobId) return null
    const recovered: PrivateTranslationRequest = {
      ownerKey,
      sourceKey,
      controller: new AbortController(),
      jobId: visible.jobId,
    }
    requestRef.current = recovered
    return recovered
  }, [ownerKey, sourceKey, visible.active, visible.jobId])

  const followTask = useCallback(async (
    jobId: string,
    controller: AbortController,
    request: PrivateTranslationRequest,
  ) => {
    try {
      while (!controller.signal.aborted && requestRef.current === request
        && ownerRef.current === ownerKey && sourceRef.current === request.sourceKey) {
        const task = await getPrivateTranslationJob(jobId, controller.signal)
        if (controller.signal.aborted || requestRef.current !== request || ownerRef.current !== ownerKey
          || sourceRef.current !== request.sourceKey) return
        updateState({ active: ['queued', 'running'].includes(task.status), progress: task.progress, jobId: task.id })
        if (!['queued', 'running'].includes(task.status)) {
          finishRequestFromTask(request, task)
          return
        }
        await sleep(1200, controller.signal)
      }
    } catch (error: unknown) {
      if (controller.signal.aborted || requestRef.current !== request || sourceRef.current !== request.sourceKey) return
      updateState({
        active: true,
        jobId: request.jobId ?? jobId,
        error: safeErrorMessage(error, '无法读取个人翻译任务。') + ' 任务可能仍在运行；请重新检查状态或再次取消。',
      })
    }
  }, [finishRequestFromTask, ownerKey, updateState])

  useEffect(() => {
    if (!enabled || loading || !isAuthenticated || newsId === null || news?.id !== newsId) return
    const storedJobId = readRecovery(viewerId, newsId)
    if (!storedJobId) return
    const attached = requestRef.current
    if (attached?.ownerKey === ownerKey && attached.sourceKey === sourceKey
      && attached.jobId === storedJobId && !attached.controller.signal.aborted) return
    attached?.controller.abort()
    const request: PrivateTranslationRequest = {
      ownerKey,
      sourceKey,
      controller: new AbortController(),
      jobId: storedJobId,
    }
    requestRef.current = request
    updateState({ active: true, error: '', jobId: storedJobId })
    void followTask(storedJobId, request.controller, request)
    return () => {
      if (requestRef.current === request) {
        request.controller.abort()
        requestRef.current = null
      }
    }
  }, [enabled, followTask, isAuthenticated, loading, news?.id, newsId, ownerKey, sourceKey, updateState, viewerId])

  useEffect(() => {
    const resultId = news?.full_content_zh_stale_result_id
    if (loading || !isAuthenticated || !resultId) return
    const controller = new AbortController()
    void getPrivateTranslationResult(resultId, controller.signal)
      .then((result) => {
        if (controller.signal.aborted || ownerRef.current !== ownerKey || sourceRef.current !== sourceKey || result.currentMatch) return
        setStaleResult({ ownerKey, resultId, result })
      })
      .catch(() => {
        if (!controller.signal.aborted && ownerRef.current === ownerKey && sourceRef.current === sourceKey) setStaleResult(null)
      })
    return () => controller.abort()
  }, [isAuthenticated, loading, news?.full_content_zh_stale_result_id, ownerKey, sourceKey])

  const startPrivateTranslation = useCallback(async () => {
    if (!enabled || !isAuthenticated || newsId === null || !news || news.id !== newsId || !news.full_content) return
    if (requestRef.current?.ownerKey === ownerKey || (visible.active && visible.jobId)) return
    requestRef.current?.controller.abort()
    requestRef.current = null
    const controller = new AbortController()
    const request: PrivateTranslationRequest = { ownerKey, sourceKey, controller, jobId: null }
    requestRef.current = request
    const cryptoApi = globalThis.crypto
    const idempotencyKey = cryptoApi?.randomUUID
      ? cryptoApi.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    updateState({ active: true, cancelPending: false, error: '', progress: '', jobId: '' })

    let terminal = false
    try {
      for await (const event of translatePrivateFullArticleStream(newsId, idempotencyKey, {
        signal: controller.signal,
        onJobId: (jobId) => {
          if (requestRef.current !== request || ownerRef.current !== ownerKey || sourceRef.current !== sourceKey) return
          request.jobId = jobId
          saveRecovery(viewerId, newsId, jobId)
          updateState({ jobId })
        },
      })) {
        if (controller.signal.aborted || requestRef.current !== request || ownerRef.current !== ownerKey
          || sourceRef.current !== request.sourceKey) return
        if (event.type === 'progress') {
          updateState({ progress: event.text })
        } else if (event.type === 'error') {
          if (request.jobId) {
            updateState({
              active: true,
              cancelPending: false,
              jobId: request.jobId,
              error: event.message + ' 任务状态尚未确认；请重新检查状态或再次取消。',
            })
          } else {
            terminal = true
            clearRecovery(viewerId, newsId)
            if (requestRef.current === request) requestRef.current = null
            updateState({ active: false, cancelPending: false, error: event.message })
          }
        } else if (event.type === 'complete') {
          const result = resultFromTask({ result: event.result })
          if (!result) {
            terminal = true
            clearRecovery(viewerId, newsId)
            if (requestRef.current === request) requestRef.current = null
            updateState({ active: false, cancelPending: false, error: '个人翻译没有返回可保存的完整译文。' })
          } else {
            try {
              const verifiedResult = await getPrivateTranslationResult(result.id, controller.signal)
              if (controller.signal.aborted || requestRef.current !== request || ownerRef.current !== ownerKey
                || sourceRef.current !== request.sourceKey) return
              terminal = true
              clearRecovery(viewerId, newsId)
              requestRef.current = null
              updateState({
                active: false,
                cancelPending: false,
                error: '',
                result: verifiedResult.text,
                resultId: verifiedResult.resultId,
                resultCurrentMatch: verifiedResult.currentMatch,
              })
            } catch {
              if (controller.signal.aborted || requestRef.current !== request || ownerRef.current !== ownerKey
                || sourceRef.current !== request.sourceKey) return
              terminal = true
              clearRecovery(viewerId, newsId)
              requestRef.current = null
              updateState({
                active: false,
                cancelPending: false,
                error: '个人翻译已完成，但无法确认结果是否匹配当前原文。请重新生成当前译文。',
              })
            }
          }
        }
      }
      if (!terminal && request.jobId && !controller.signal.aborted) {
        await followTask(request.jobId, controller, request)
      } else if (!terminal && !controller.signal.aborted) {
        updateState({ active: false, cancelPending: false, error: '无法确认个人翻译任务状态；请查看任务后再决定是否重试。' })
      }
    } catch (error: unknown) {
      if (!controller.signal.aborted && requestRef.current === request
        && ownerRef.current === ownerKey && sourceRef.current === request.sourceKey) {
        updateState({
          active: Boolean(request.jobId),
          jobId: request.jobId ?? '',
          error: safeErrorMessage(error, '个人翻译失败。') +
            (request.jobId ? ' 任务可能仍在运行；请重新检查状态或再次取消。' : ''),
        })
      }
    } finally {
      if (requestRef.current === request && (terminal || !request.jobId)) requestRef.current = null
    }
  }, [enabled, followTask, isAuthenticated, news, newsId, ownerKey, sourceKey, updateState, viewerId, visible.active, visible.jobId])

  const checkPrivateTranslationStatus = useCallback(async () => {
    const request = getCurrentTaskRequest()
    if (!request?.jobId || request.ownerKey !== ownerKey || request.sourceKey !== sourceKey) return
    updateState({ cancelPending: true, error: '' })
    try {
      const current = await getPrivateTranslationJob(request.jobId, new AbortController().signal)
      if (requestRef.current !== request || ownerRef.current !== ownerKey || sourceRef.current !== request.sourceKey) return
      if (!['queued', 'running'].includes(current.status)) {
        finishRequestFromTask(request, current)
        return
      }
      updateState({
        active: true,
        cancelPending: false,
        progress: current.progress,
        jobId: current.id,
        error: '',
      })
    } catch (error: unknown) {
      if (requestRef.current !== request || ownerRef.current !== ownerKey || sourceRef.current !== request.sourceKey) return
      updateState({
        active: true,
        cancelPending: true,
        jobId: request.jobId,
        error: safeErrorMessage(error, '无法确认个人翻译任务状态。') + ' 任务可能仍在运行；请重试检查或再次取消。',
      })
    }
  }, [finishRequestFromTask, getCurrentTaskRequest, ownerKey, sourceKey, updateState])

  const cancelPrivateTranslation = useCallback(async () => {
    const request = getCurrentTaskRequest()
    if (!request?.jobId || request.ownerKey !== ownerKey || request.sourceKey !== sourceKey) return
    updateState({ cancelPending: true, error: '' })
    try {
      const current = await getPrivateTranslationJob(request.jobId, new AbortController().signal)
      if (requestRef.current !== request || ownerRef.current !== ownerKey || sourceRef.current !== request.sourceKey) return
      if (!['queued', 'running'].includes(current.status)) {
        finishRequestFromTask(request, current)
        return
      }
      const terminal = await cancelPrivateTranslationJob(request.jobId, current.generation)
      if (requestRef.current !== request || ownerRef.current !== ownerKey || sourceRef.current !== request.sourceKey) return
      if (['queued', 'running'].includes(terminal.status)) {
        updateState({ active: true, cancelPending: true, jobId: request.jobId, error: '取消状态尚未确认，任务可能仍在运行。请重试取消或重新查看任务状态。' })
        return
      }
      finishRequestFromTask(request, terminal)
    } catch (error: unknown) {
      if (requestRef.current !== request || ownerRef.current !== ownerKey || sourceRef.current !== request.sourceKey) return
      updateState({ active: true, cancelPending: true, jobId: request.jobId, error: safeErrorMessage(error, '无法确认个人翻译任务状态。') + ' 任务可能仍在运行；请重试取消或重新查看任务状态。' })
    }
  }, [finishRequestFromTask, getCurrentTaskRequest, ownerKey, sourceKey, updateState])

  useEffect(() => () => {
    if (requestRef.current?.ownerKey === ownerKey) {
      requestRef.current.controller.abort()
      requestRef.current = null
    }
  }, [ownerKey])

  return {
    privateTranslationActive: visible.active,
    privateTranslationCancelPending: visible.cancelPending,
    privateTranslationError: visible.error,
    privateTranslationProgress: visible.progress,
    privateTranslationResult: visible.result,
    privateTranslationResultId: visible.resultId,
    privateTranslationResultCurrentMatch: visible.resultCurrentMatch,
    privateTranslationStaleResult: visibleStaleResult,
    privateTranslationJobId: visible.jobId,
    startPrivateTranslation,
    checkPrivateTranslationStatus,
    cancelPrivateTranslation,
  }
}
