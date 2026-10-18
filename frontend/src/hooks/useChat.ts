import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import {
  chatHistoryTurnOverlay,
  copyChatHistoryBoundary,
  reconcileChatHistory,
} from '@/services/chatHistoryReconciliation'
import {
  chatStream,
  cancelChatTurn,
  clearChatHistory,
  fetchChatHistory,
  parseWebSources,
  type ChatHistory,
  type ChatMessage,
} from '@/services/newsWorkflowApi'
import { chatHistoryOptions, parseNewsId } from '@/services/newsWorkflowQueries'
import type { ViewerId } from '@/services/newsWorkflowQueries'

export type ChatPhase = 'loading-history' | 'idle' | 'thinking' | 'streaming' | 'success' | 'error'
type ReconciliationState = 'idle' | 'checking' | 'unconfirmed' | 'partial' | 'failed'

interface KeyedValue<T> {
  ownerKey: string
  value: T
}

interface PendingTurn {
  ownerKey: string
  id: string
  user: ChatMessage
  assistant: ChatMessage
  status: 'streaming' | 'uncertain'
  webSearch: boolean
  modelConfigId: string | null
  serverTurnId: string | null
  historyBoundary: ChatMessage[] | null
  historyBoundaryData: ChatHistory | undefined
  reconciliation: ReconciliationState
  serverQuestionSaved: boolean
}

interface ActiveRequest {
  ownerKey: string
  turnId: string
  controller: AbortController
  user: ChatMessage
  assistant: ChatMessage
  webSearch: boolean
  modelConfigId: string | null
  serverTurnId: string | null
  historyBoundary: ChatMessage[] | null
  historyBoundaryData: ChatHistory | undefined
}

interface ClearChatState {
  open: boolean
  clearing: boolean
  error: string | null
}

const ASSISTANT_ERROR = '抱歉，我遇到了一些问题，请稍后再试。'
const STOPPED_MESSAGE = '已停止接收本页更新。正在只读核对服务器记录。'
const CLEAR_ERROR = '清空失败，原有聊天记录仍保留。请检查网络后重试。'
const CLEAR_CANCEL_UNKNOWN_ERROR = '无法确认服务端是否已停止本轮，因此未清空聊天记录；请求可能仍在处理或已产生费用。请先核对本轮状态。'
const SUCCESS_DURATION_MS = 1500
const META_MARKER = '__META__'
let nextTurnId = 0

function readMetaSources(value: string): ReturnType<typeof parseWebSources> {
  try {
    const parsed: unknown = JSON.parse(value)
    if (typeof parsed === 'object' && parsed !== null && 'sources' in parsed) {
      return parseWebSources(parsed.sources)
    }
  } catch {
    return undefined
  }
  return undefined
}

function readMetaTurnStatus(value: string): 'complete' | 'failed' | undefined {
  try {
    const parsed: unknown = JSON.parse(value)
    if (typeof parsed === 'object' && parsed !== null && 'type' in parsed && 'status' in parsed &&
      parsed.type === 'chat_turn' && (parsed.status === 'complete' || parsed.status === 'failed')) {
      return parsed.status
    }
  } catch { return undefined }
  return undefined
}

function readMetaModel(value: string): ChatMessage['model_source'] {
  try {
    const parsed: unknown = JSON.parse(value)
    if (typeof parsed !== 'object' || parsed === null || !('type' in parsed) ||
        parsed.type !== 'chat_model' || !('model_source' in parsed)) return undefined
    const source = parsed.model_source
    if (typeof source === 'object' && source !== null && 'provider' in source && 'model' in source &&
        typeof source.provider === 'string' && typeof source.model === 'string' &&
        source.provider.length <= 32 && source.model.length <= 64) {
      return { provider: source.provider, model: source.model }
    }
  } catch { /* malformed model metadata never authorizes a completed turn */ }
  return undefined
}

function readMetaContext(value: string): ChatMessage['context_scope'] {
  try {
    const parsed: unknown = JSON.parse(value)
    if (typeof parsed === 'object' && parsed !== null && 'context_scope' in parsed) {
      const scope = parsed.context_scope
      if (scope === 'full' || scope === 'summary' || scope === 'excerpt') return scope
    }
  } catch { return undefined }
  return undefined
}

/** Consume the backend's inline metadata frame without losing split markers. */
function consumeMetaFrame(
  buffered: string,
  chunk: string,
  final: boolean,
  onText: (text: string) => void,
  onSources: (sources: NonNullable<ReturnType<typeof parseWebSources>>) => void,
  onScope?: (scope: NonNullable<ChatMessage['context_scope']>) => void,
  onTurnStatus?: (status: 'complete' | 'failed') => void,
  onModelSource?: (source: NonNullable<ChatMessage['model_source']>) => void,
): string {
  let remaining = buffered + chunk
  while (remaining) {
    const start = remaining.indexOf(META_MARKER)
    if (start < 0) {
      if (final) {
        onText(remaining)
        return ''
      }
      const safeLength = Math.max(0, remaining.length - META_MARKER.length + 1)
      if (safeLength > 0) onText(remaining.slice(0, safeLength))
      return remaining.slice(safeLength)
    }

    if (start > 0) {
      const prefix = remaining.slice(0, start)
      onText(prefix.endsWith('\u200b') ? prefix.slice(0, -1) : prefix)
      remaining = remaining.slice(start)
    }
    const end = remaining.indexOf(META_MARKER, META_MARKER.length)
    if (end < 0) {
      if (final) onText(remaining)
      return final ? '' : remaining
    }
    const sources = readMetaSources(remaining.slice(META_MARKER.length, end))
    if (sources) onSources(sources)
    const scope = readMetaContext(remaining.slice(META_MARKER.length, end))
    if (scope) onScope?.(scope)
    const turnStatus = readMetaTurnStatus(remaining.slice(META_MARKER.length, end))
    if (turnStatus) onTurnStatus?.(turnStatus)
    const model = readMetaModel(remaining.slice(META_MARKER.length, end))
    if (model) onModelSource?.(model)
    remaining = remaining.slice(end + META_MARKER.length)
    if (remaining.startsWith('\r\n\r\n')) remaining = remaining.slice(4)
    else if (remaining.startsWith('\n\n')) remaining = remaining.slice(2)
  }
  return ''
}

function snapshotActiveRequest(request: ActiveRequest): PendingTurn {
  return {
    ownerKey: request.ownerKey,
    id: request.turnId,
    user: request.user,
    assistant: request.assistant,
    status: 'uncertain',
    webSearch: request.webSearch,
    modelConfigId: request.modelConfigId,
    serverTurnId: request.serverTurnId,
    historyBoundary: request.historyBoundary,
    historyBoundaryData: request.historyBoundaryData,
    reconciliation: 'checking',
    serverQuestionSaved: false,
  }
}

export function useChat(newsId: string | number | null | undefined, enabled: boolean,
  modelConfigId: string | null = null, billingConsent = false) {
  const queryClient = useQueryClient()
  const { user, loading: authLoading } = useAuth()
  const { lang } = useLanguage()
  const parsedId = parseNewsId(newsId)
  const viewerId: ViewerId = user?.id ?? 'anonymous'
  const ownerKey = `${parsedId ?? String(newsId ?? '')}:${viewerId}:${lang}`
  const ownerRef = useRef(ownerKey)
  const ownerEpochRef = useRef(0)
  const automaticReconciliationRef = useRef('')
  const [inputState, setInputState] = useState<KeyedValue<string>>({ ownerKey: '', value: '' })
  const [webSearchState, setWebSearchState] = useState<KeyedValue<boolean>>({ ownerKey: '', value: false })
  const [phaseState, setPhaseState] = useState<KeyedValue<ChatPhase>>({ ownerKey: '', value: 'idle' })
  const [clearState, setClearState] = useState<KeyedValue<ClearChatState>>({
    ownerKey: '', value: { open: false, clearing: false, error: null },
  })
  const [pendingTurnState, setPendingTurnState] = useState<PendingTurn | null>(null)
  const pendingTurnRef = useRef<PendingTurn | null>(null)
  const lastReconciledHistoryRef = useRef<{ ownerKey: string; turnId: string; history: ChatHistory } | null>(null)
  const requestRef = useRef<ActiveRequest | null>(null)
  const clearControllerRef = useRef<{ ownerKey: string; controller: AbortController } | null>(null)
  const reconciliationControllerRef = useRef<{ ownerKey: string; turnId: string; controller: AbortController } | null>(null)
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inputRef = useRef(inputState.ownerKey === ownerKey ? inputState.value : '')
  const currentInput = inputState.ownerKey === ownerKey ? inputState.value : ''
  const currentWebSearch = webSearchState.ownerKey === ownerKey ? webSearchState.value : false
  const ownerClearState = clearState.ownerKey === ownerKey
    ? clearState.value
    : { open: false, clearing: false, error: null }
  const historyOptions = useMemo(() => {
    const options = chatHistoryOptions(parsedId ?? 0, lang, viewerId)
    return parsedId === null
      ? { ...options, queryKey: ['newsWorkflow', 'chatHistory', 'disabled'] as unknown as typeof options.queryKey }
      : options
  }, [lang, parsedId, viewerId])
  const historyKey = historyOptions.queryKey
  const historyQuery = useQuery({
    ...historyOptions,
    enabled: enabled && !authLoading && parsedId !== null,
  })
  const currentPendingTurn = pendingTurnState?.ownerKey === ownerKey ? pendingTurnState : null
  const historyMessages = historyQuery.data?.messages
  const messages = useMemo(() => [
    ...(historyMessages ?? []),
    ...(currentPendingTurn ? chatHistoryTurnOverlay(currentPendingTurn) : []),
  ], [historyMessages, currentPendingTurn])
  const phase = enabled && historyQuery.isFetching
    ? 'loading-history'
    : phaseState.ownerKey === ownerKey ? phaseState.value : 'idle'
  const isLoading = phase === 'loading-history' || phase === 'thinking' || phase === 'streaming'
  const confirmingClear = ownerClearState.open
  const isClearing = ownerClearState.clearing
  const clearError = ownerClearState.error

  useLayoutEffect(() => {
    if (ownerRef.current !== ownerKey) ownerEpochRef.current += 1
    ownerRef.current = ownerKey
    inputRef.current = currentInput
    pendingTurnRef.current = pendingTurnState
  }, [currentInput, ownerKey, pendingTurnState])

  const updatePhase = useCallback((nextPhase: ChatPhase) => {
    if (ownerRef.current === ownerKey) setPhaseState({ ownerKey, value: nextPhase })
  }, [ownerKey])

  const setInput = useCallback((value: string) => {
    if (ownerRef.current !== ownerKey) return
    inputRef.current = value
    setInputState({ ownerKey, value })
  }, [ownerKey])

  const setPendingTurn = useCallback((next: PendingTurn | null | ((current: PendingTurn | null) => PendingTurn | null)) => {
    const updated = typeof next === 'function' ? next(pendingTurnRef.current) : next
    pendingTurnRef.current = updated
    setPendingTurnState(updated)
  }, [])

  const updatePendingTurn = useCallback((turnId: string, update: (turn: PendingTurn) => PendingTurn) => {
    if (ownerRef.current !== ownerKey) return
    const current = pendingTurnRef.current
    if (current?.ownerKey === ownerKey && current.id === turnId) setPendingTurn(update(current))
  }, [ownerKey, setPendingTurn])

  useEffect(() => () => {
    if (requestRef.current?.ownerKey === ownerKey) {
      const request = requestRef.current
      requestRef.current = null
      request.controller.abort()
      // Unmounting only stops browser receive. Best-effort server cancellation
      // fences a paid turn when this tab disappears; failure remains unknown.
      if (request.serverTurnId && parsedId !== null && ownerRef.current === ownerKey) {
        void cancelChatTurn(parsedId, request.serverTurnId).catch(() => {})
      }
      const interrupted = snapshotActiveRequest(request)
      interrupted.reconciliation = 'unconfirmed'
      const pending = pendingTurnRef.current
      if (pending?.ownerKey === ownerKey && pending.id === request.turnId) {
        pendingTurnRef.current = interrupted
        setPendingTurnState((current) => current?.ownerKey === ownerKey && current.id === request.turnId
          ? interrupted
          : current)
      }
      setPhaseState((current) => current.ownerKey === ownerKey ? { ownerKey, value: 'error' } : current)
    }
    if (clearControllerRef.current?.ownerKey === ownerKey) {
      clearControllerRef.current.controller.abort()
      clearControllerRef.current = null
    }
    if (reconciliationControllerRef.current?.ownerKey === ownerKey) {
      const reconciliation = reconciliationControllerRef.current
      reconciliation.controller.abort()
      reconciliationControllerRef.current = null
      const pending = pendingTurnRef.current
      if (
        ownerRef.current !== ownerKey && pending?.ownerKey === ownerKey && pending.id === reconciliation.turnId &&
        pending.status === 'uncertain' && pending.reconciliation === 'checking'
      ) {
        setPendingTurnState((current) => current?.ownerKey === ownerKey && current.id === reconciliation.turnId && current.reconciliation === 'checking'
          ? { ...current, reconciliation: 'unconfirmed' }
          : current)
      }
    }
    if (successTimerRef.current) clearTimeout(successTimerRef.current)
  }, [ownerKey, parsedId])

  // Apply both explicit rechecks and later Query snapshots against the original turn boundary.
  const applyHistoryReconciliation = useCallback((snapshot: PendingTurn, history: ChatHistory) => {
    if (ownerRef.current !== ownerKey || snapshot.ownerKey !== ownerKey) return
    const current = pendingTurnRef.current
    if (current?.ownerKey !== ownerKey || current.id !== snapshot.id || current.status !== 'uncertain') return
    const previous = lastReconciledHistoryRef.current
    const hasSettledSnapshot = current.reconciliation === 'unconfirmed' || current.reconciliation === 'partial'
    if (
      hasSettledSnapshot && previous?.ownerKey === ownerKey && previous.turnId === snapshot.id && previous.history === history
    ) return

    lastReconciledHistoryRef.current = { ownerKey, turnId: snapshot.id, history }
    const result = reconcileChatHistory(history, snapshot.historyBoundary, snapshot.user.content)
    if (result === 'answered') {
      setPendingTurn(null)
      if (inputRef.current === snapshot.user.content) setInput('')
      updatePhase('idle')
    } else if (result === 'question-saved') {
      setPendingTurn({ ...current, status: 'uncertain', reconciliation: 'partial', serverQuestionSaved: true })
      if (inputRef.current === snapshot.user.content) setInput('')
      updatePhase('error')
    } else {
      setPendingTurn({ ...current, status: 'uncertain', reconciliation: 'unconfirmed', serverQuestionSaved: false })
      updatePhase('error')
    }
  }, [ownerKey, setInput, setPendingTurn, updatePhase])

  useEffect(() => {
    const turn = currentPendingTurn
    if (!turn || turn.status !== 'uncertain' || turn.reconciliation === 'checking' || !historyQuery.data) return
    if (turn.historyBoundaryData === historyQuery.data) return
    applyHistoryReconciliation(turn, historyQuery.data)
  }, [applyHistoryReconciliation, currentPendingTurn, historyQuery.data])

  const reconcileInterruptedTurn = useCallback(async (snapshot: PendingTurn) => {
    if (parsedId === null || ownerRef.current !== ownerKey || snapshot.ownerKey !== ownerKey) return
    automaticReconciliationRef.current = `${ownerKey}:${ownerEpochRef.current}:${snapshot.id}`
    const previous = reconciliationControllerRef.current
    if (previous?.ownerKey === ownerKey) previous.controller.abort()
    const controller = new AbortController()
    const request = { ownerKey, turnId: snapshot.id, controller }
    reconciliationControllerRef.current = request
    updatePendingTurn(snapshot.id, (current) => ({ ...current, status: 'uncertain', reconciliation: 'checking' }))

    const isCurrent = () => ownerRef.current === ownerKey && reconciliationControllerRef.current === request
    try {
      const history = await fetchChatHistory(parsedId, controller.signal)
      if (!isCurrent()) return
      const storedHistory = queryClient.setQueryData<ChatHistory>(historyKey, history) ?? history
      applyHistoryReconciliation(snapshot, storedHistory)
    } catch {
      if (!isCurrent() || controller.signal.aborted) return
      updatePendingTurn(snapshot.id, (current) => ({ ...current, status: 'uncertain', reconciliation: 'failed' }))
      updatePhase('error')
    } finally {
      if (reconciliationControllerRef.current === request) reconciliationControllerRef.current = null
    }
  }, [applyHistoryReconciliation, historyKey, ownerKey, parsedId, queryClient, updatePendingTurn, updatePhase])

  useEffect(() => {
    const turn = currentPendingTurn
    if (
      !enabled || authLoading || !turn || turn.status !== 'uncertain' ||
      turn.reconciliation !== 'unconfirmed'
    ) return
    const reconciliationKey = `${ownerKey}:${ownerEpochRef.current}:${turn.id}`
    if (automaticReconciliationRef.current === reconciliationKey) return
    automaticReconciliationRef.current = reconciliationKey
    void reconcileInterruptedTurn(turn)
  }, [authLoading, currentPendingTurn, enabled, ownerKey, reconcileInterruptedTurn])

  const sendMessage = useCallback((text: string, explicitlyResending = false): Promise<boolean> => {
    const trimmed = text.trim()
    const clearInFlight = clearControllerRef.current?.ownerKey === ownerKey
    const clearDialogOpen = clearState.ownerKey === ownerKey && clearState.value.open
    const currentTurn = pendingTurnState?.ownerKey === ownerKey ? pendingTurnState : null
    if (
      !trimmed || parsedId === null || !enabled || authLoading || isLoading || requestRef.current || clearInFlight || clearDialogOpen ||
      ownerRef.current !== ownerKey
    ) return Promise.resolve(false)
    if (currentTurn?.status === 'uncertain' && (
      !explicitlyResending || currentTurn.serverQuestionSaved || currentTurn.reconciliation === 'checking'
    )) return Promise.resolve(false)

    if (successTimerRef.current) clearTimeout(successTimerRef.current)
    const previousTurn = currentTurn
    const reuseTurn = Boolean(explicitlyResending && previousTurn?.status === 'uncertain')
    const selectedForTurn = reuseTurn ? previousTurn?.modelConfigId ?? null : modelConfigId
    // Never switch the model for a paid ambiguous request while replaying it.
    if ((reuseTurn && selectedForTurn !== modelConfigId) || (selectedForTurn && !billingConsent)) {
      return Promise.resolve(false)
    }
    // An explicitly retried billable attempt receives a new one-shot UUID.
    const serverTurnId = selectedForTurn ? crypto.randomUUID() : null
    const turnId = reuseTurn && previousTurn ? previousTurn.id : `chat-turn-${++nextTurnId}`
    const userMessage: ChatMessage = reuseTurn && previousTurn
      ? previousTurn.user
      : { id: `${turnId}-user`, role: 'user', content: trimmed }
    const assistantMessage: ChatMessage = reuseTurn && previousTurn
      ? { ...previousTurn.assistant, content: '', web_sources: undefined }
      : { id: `${turnId}-assistant`, role: 'assistant', content: '' }
    const webSearch = Boolean(currentWebSearch && !selectedForTurn)
    if (webSearch) assistantMessage.web_search = true
    const historyAtSend = queryClient.getQueryData<ChatHistory>(historyKey)
    const turn: PendingTurn = {
      ownerKey,
      id: turnId,
      user: userMessage,
      assistant: assistantMessage,
      status: 'streaming',
      webSearch,
      modelConfigId: selectedForTurn,
      serverTurnId,
      historyBoundary: copyChatHistoryBoundary(historyAtSend?.messages),
      historyBoundaryData: historyAtSend,
      reconciliation: 'idle',
      serverQuestionSaved: false,
    }
    lastReconciledHistoryRef.current = null
    setPendingTurn(turn)

    const request: ActiveRequest = {
      ownerKey,
      turnId,
      controller: new AbortController(),
      user: userMessage,
      assistant: assistantMessage,
      webSearch,
      modelConfigId: selectedForTurn,
      serverTurnId,
      historyBoundary: turn.historyBoundary,
      historyBoundaryData: turn.historyBoundaryData,
    }
    requestRef.current = request
    const isCurrent = () => requestRef.current === request && ownerRef.current === ownerKey
    updatePhase('thinking')

    return (async () => {
      let accumulated = ''
      let webSources: ReturnType<typeof parseWebSources>
      let firstChunk = true
      let frameBuffer = ''
      let terminalStatus: 'complete' | 'failed' | undefined
      const applyScope = (scope: NonNullable<ChatMessage['context_scope']>) => {
        request.assistant = { ...request.assistant, context_scope: scope }
        updatePendingTurn(turnId, (current) => ({ ...current, assistant: { ...current.assistant, context_scope: scope } }))
      }
      try {
        for await (const chunk of chatStream(parsedId, trimmed, {
          webSearch, ...(selectedForTurn ? { modelConfigId: selectedForTurn, billingConsent,
            turnId: serverTurnId ?? undefined } : {}),
          signal: request.controller.signal,
        })) {
          if (!isCurrent()) return false
          if (firstChunk) {
            firstChunk = false
            updatePhase('streaming')
          }
          frameBuffer = consumeMetaFrame(frameBuffer, chunk, false,
            (content) => { accumulated += content },
            (sources) => {
              webSources = sources
              request.assistant = { ...request.assistant, web_sources: sources }
              updatePendingTurn(turnId, (current) => ({
                ...current,
                assistant: { ...current.assistant, web_sources: sources },
              }))
            },
            applyScope,
            (status) => { terminalStatus = status },
            (source) => {
              request.assistant = { ...request.assistant, model_source: source }
              updatePendingTurn(turnId, (current) => ({
                ...current, assistant: { ...current.assistant, model_source: source },
              }))
            },
          )
          request.assistant = { ...request.assistant, content: accumulated }
          updatePendingTurn(turnId, (current) => ({
            ...current,
            assistant: { ...current.assistant, content: accumulated },
          }))
        }
        if (!isCurrent()) return false
        consumeMetaFrame(frameBuffer, '', true,
          (content) => { accumulated += content },
          (sources) => {
            webSources = sources
            request.assistant = { ...request.assistant, web_sources: sources }
            updatePendingTurn(turnId, (current) => ({
              ...current,
              assistant: { ...current.assistant, web_sources: sources },
            }))
          },
          applyScope,
          (status) => { terminalStatus = status },
          (source) => { request.assistant = { ...request.assistant, model_source: source } },
        )

        // A clean TCP EOF without the server's terminal receipt is not success.
        if (terminalStatus !== 'complete') {
          request.assistant = { ...request.assistant, content: accumulated,
            status: terminalStatus === 'failed' ? 'failed' : 'interrupted' }
          const uncertainTurn = snapshotActiveRequest(request)
          setPendingTurn(uncertainTurn)
          updatePhase('error')
          await reconcileInterruptedTurn(uncertainTurn)
          return false
        }

        const completedAssistant: ChatMessage = { ...request.assistant, content: accumulated, status: 'complete' }
        if (webSources) completedAssistant.web_sources = webSources
        queryClient.setQueryData<ChatHistory>(historyKey, (current) => ({
          messages: [...(current?.messages ?? []), userMessage, completedAssistant],
        }))
        setPendingTurn((current) => current?.ownerKey === ownerKey && current.id === turnId ? null : current)
        if (inputRef.current === trimmed) setInput('')
        updatePhase('success')
        successTimerRef.current = setTimeout(() => {
          if (ownerRef.current === ownerKey) updatePhase('idle')
        }, SUCCESS_DURATION_MS)
        return true
      } catch (error: unknown) {
        if (!isCurrent() || request.controller.signal.aborted) return false
        const message = error instanceof Error ? error.message : ASSISTANT_ERROR
        request.assistant = {
          ...request.assistant,
          content: request.assistant.content || `${ASSISTANT_ERROR}${message ? ` (${message})` : ''}`,
        }
        const uncertainTurn = snapshotActiveRequest(request)
        setPendingTurn(uncertainTurn)
        if (!inputRef.current) setInput(trimmed)
        updatePhase('error')
        await reconcileInterruptedTurn(uncertainTurn)
        return false
      } finally {
        if (isCurrent()) requestRef.current = null
      }
    })()
  }, [authLoading, billingConsent, clearState, currentWebSearch, enabled, historyKey, isLoading, modelConfigId, ownerKey, parsedId, pendingTurnState, queryClient, reconcileInterruptedTurn, setInput, setPendingTurn, updatePendingTurn, updatePhase])

  const doSend = useCallback((text: string): Promise<boolean> => sendMessage(text), [sendMessage])
  const handleSend = useCallback(() => doSend(inputRef.current), [doSend])

  const stopWaiting = useCallback(() => {
    const request = requestRef.current
    if (!request || request.ownerKey !== ownerKey) return
    requestRef.current = null
    request.controller.abort()
    const uncertainTurn = snapshotActiveRequest(request)
    uncertainTurn.assistant = {
      ...uncertainTurn.assistant,
      content: uncertainTurn.assistant.content
        ? `${uncertainTurn.assistant.content}\n\n> ${STOPPED_MESSAGE}`
        : STOPPED_MESSAGE,
    }
    setPendingTurn(uncertainTurn)
    if (!inputRef.current) setInput(request.user.content)
    updatePhase('error')
    // A browser AbortSignal alone cannot fence the backend one-shot send.
    // Request a durable server acknowledgement before reconciling history.
    void (async () => {
      if (request.serverTurnId && parsedId !== null) {
        try {
          const outcome = await cancelChatTurn(parsedId, request.serverTurnId)
          if (ownerRef.current === ownerKey) {
            updatePendingTurn(request.turnId, current => ({
              ...current,
              assistant: {
                ...current.assistant,
                content: outcome === 'cancelled'
                  ? '服务端已确认取消本轮；已经发送的请求仍可能产生费用。'
                  : '服务端已完成本轮；正在核对已保存的回答。',
              },
            }))
          }
        } catch { /* Failed/unknown cancellation is never assumed successful. */ }
      }
      await reconcileInterruptedTurn(uncertainTurn)
    })()
  }, [ownerKey, parsedId, reconcileInterruptedTurn, setInput, setPendingTurn, updatePendingTurn, updatePhase])

  const requestClearChat = useCallback(() => {
    if (
      ownerRef.current !== ownerKey || clearControllerRef.current?.ownerKey === ownerKey ||
      (clearState.ownerKey === ownerKey && clearState.value.open)
    ) return
    setClearState({ ownerKey, value: { open: true, clearing: false, error: null } })
  }, [clearState, ownerKey])

  const cancelClear = useCallback(() => {
    if (ownerRef.current !== ownerKey || clearControllerRef.current?.ownerKey === ownerKey) return
    setClearState({ ownerKey, value: { open: false, clearing: false, error: null } })
  }, [ownerKey])

  const confirmClear = useCallback(async () => {
    if (
      parsedId === null || authLoading || ownerRef.current !== ownerKey ||
      clearControllerRef.current?.ownerKey === ownerKey
    ) return false
    const clearRequest = { ownerKey, controller: new AbortController() }
    clearControllerRef.current = clearRequest
    setClearState({ ownerKey, value: { open: true, clearing: true, error: null } })

    let interruptedTurn: PendingTurn | null = null
    const activeRequest = requestRef.current
    if (activeRequest?.ownerKey === ownerKey) {
      requestRef.current = null
      activeRequest.controller.abort()
      interruptedTurn = snapshotActiveRequest(activeRequest)
      setPendingTurn(interruptedTurn)
      updatePhase('error')
    } else if (currentPendingTurn?.status === 'uncertain') {
      interruptedTurn = currentPendingTurn
    }
    if (reconciliationControllerRef.current?.ownerKey === ownerKey) {
      reconciliationControllerRef.current.controller.abort()
      reconciliationControllerRef.current = null
    }

    let cleared = false
    let cancelOutcomeUnknown = false
    try {
      await queryClient.cancelQueries({ queryKey: historyKey })
      if (clearRequest.controller.signal.aborted || ownerRef.current !== ownerKey || clearControllerRef.current !== clearRequest) {
        return false
      }
      // Clear only after a durable receipt for a known personal-model turn.
      // Unknown never means cancelled: leave history and the uncertain turn intact.
      if (interruptedTurn?.serverTurnId) {
        try {
          const outcome = await cancelChatTurn(parsedId, interruptedTurn.serverTurnId)
          if (clearRequest.controller.signal.aborted || ownerRef.current !== ownerKey ||
            clearControllerRef.current !== clearRequest) return false
          interruptedTurn = {
            ...interruptedTurn,
            assistant: {
              ...interruptedTurn.assistant,
              content: outcome === 'cancelled'
                ? '服务端已确认取消本轮；已发送请求仍可能产生费用。'
                : '服务端已完成本轮；正在清空已保存记录。',
            },
          }
          setPendingTurn(interruptedTurn)
        } catch {
          cancelOutcomeUnknown = true
          throw new Error('chat_turn_cancel_unknown')
        }
      }
      if (clearRequest.controller.signal.aborted || ownerRef.current !== ownerKey || clearControllerRef.current !== clearRequest) {
        return false
      }
      await clearChatHistory(parsedId, clearRequest.controller.signal)
      if (ownerRef.current !== ownerKey || clearControllerRef.current !== clearRequest) return false
      queryClient.setQueryData<ChatHistory>(historyKey, { messages: [] })
      setPendingTurn((current) => current?.ownerKey === ownerKey ? null : current)
      updatePhase('idle')
      cleared = true
    } catch {
      if (ownerRef.current === ownerKey && clearControllerRef.current === clearRequest) {
        setClearState({ ownerKey, value: { open: true, clearing: false,
          error: cancelOutcomeUnknown ? CLEAR_CANCEL_UNKNOWN_ERROR : CLEAR_ERROR } })
        if (interruptedTurn) updatePhase('error')
      }
    } finally {
      if (clearControllerRef.current === clearRequest) clearControllerRef.current = null
    }

    if (cleared) {
      setClearState({ ownerKey, value: { open: false, clearing: false, error: null } })
      return true
    }
    if (interruptedTurn && ownerRef.current === ownerKey) void reconcileInterruptedTurn(interruptedTurn)
    return false
  }, [authLoading, currentPendingTurn, historyKey, ownerKey, parsedId, queryClient, reconcileInterruptedTurn, setClearState, setPendingTurn, updatePhase])

  const checkPendingTurn = useCallback(async () => {
    if (
      currentPendingTurn?.status !== 'uncertain' || currentPendingTurn.reconciliation === 'checking' ||
      ownerRef.current !== ownerKey
    ) return
    await reconcileInterruptedTurn(currentPendingTurn)
  }, [currentPendingTurn, ownerKey, reconcileInterruptedTurn])

  const resendUncertainTurn = useCallback((): Promise<boolean> => {
    if (
      currentPendingTurn?.status !== 'uncertain' || currentPendingTurn.serverQuestionSaved ||
      currentPendingTurn.reconciliation === 'checking'
    ) return Promise.resolve(false)
    return sendMessage(currentPendingTurn.user.content, true)
  }, [currentPendingTurn, sendMessage])

  const toggleWebSearch = useCallback(() => {
    if (
      ownerRef.current === ownerKey && clearControllerRef.current?.ownerKey !== ownerKey &&
      !(clearState.ownerKey === ownerKey && clearState.value.open)
    ) {
      setWebSearchState((current) => ({
        ownerKey,
        value: !(current.ownerKey === ownerKey && current.value),
      }))
    }
  }, [clearState, ownerKey])

  return {
    messages,
    input: currentInput,
    setInput,
    isLoading,
    phase,
    historyError: historyQuery.error,
    retryHistory: historyQuery.refetch,
    handleSend,
    doSend,
    stopWaiting,
    confirmingClear,
    isClearing,
    clearError,
    requestClearChat,
    cancelClear,
    confirmClear,
    uncertainTurn: currentPendingTurn?.status === 'uncertain' ? currentPendingTurn : null,
    checkPendingTurn,
    resendUncertainTurn,
    webSearch: currentWebSearch,
    toggleWebSearch,
  }
}
