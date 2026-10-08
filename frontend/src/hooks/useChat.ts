import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import {
  chatStream,
  clearChatHistory,
  fetchChatHistory,
  parseWebSources,
  type ChatHistory,
  type ChatMessage,
} from '@/services/newsWorkflowApi'
import { newsWorkflowKeys, parseNewsId } from '@/services/newsWorkflowQueries'
import type { ViewerId } from '@/services/newsWorkflowQueries'

export type ChatPhase = 'loading-history' | 'idle' | 'thinking' | 'streaming' | 'success' | 'error'
type ReconciliationState = 'idle' | 'checking' | 'unconfirmed' | 'partial' | 'failed'
type ReconciliationResult = 'answered' | 'question-saved' | 'unconfirmed'

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
  historyBoundary: ChatMessage[] | null
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
  historyBoundary: ChatMessage[] | null
}

interface ClearChatState {
  open: boolean
  clearing: boolean
  error: string | null
}

const ASSISTANT_ERROR = '抱歉，我遇到了一些问题，请稍后再试。'
const STOPPED_MESSAGE = '已停止接收本页更新。正在只读核对服务器记录。'
const CLEAR_ERROR = '清空失败，原有聊天记录仍保留。请检查网络后重试。'
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

/** Consume the backend's inline metadata frame without losing split markers. */
function consumeMetaFrame(
  buffered: string,
  chunk: string,
  final: boolean,
  onText: (text: string) => void,
  onSources: (sources: NonNullable<ReturnType<typeof parseWebSources>>) => void,
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
    remaining = remaining.slice(end + META_MARKER.length)
    if (remaining.startsWith('\r\n\r\n')) remaining = remaining.slice(4)
    else if (remaining.startsWith('\n\n')) remaining = remaining.slice(2)
  }
  return ''
}

function copyHistoryBoundary(messages: ChatMessage[] | undefined): ChatMessage[] | null {
  return messages ? messages.map((message) => ({ ...message })) : null
}

function matchesBoundary(history: ChatMessage[], boundary: ChatMessage[]): boolean {
  if (history.length < boundary.length) return false
  return boundary.every((message, index) => {
    const candidate = history[index]
    return candidate?.role === message.role && candidate.content === message.content
  })
}

function reconcileHistory(
  history: ChatHistory,
  boundary: ChatMessage[] | null,
  question: string,
): ReconciliationResult {
  if (!boundary || !matchesBoundary(history.messages, boundary)) return 'unconfirmed'
  const userMessage = history.messages[boundary.length]
  if (userMessage?.role !== 'user' || userMessage.content !== question) return 'unconfirmed'
  return history.messages[boundary.length + 1]?.role === 'assistant' ? 'answered' : 'question-saved'
}

function snapshotActiveRequest(request: ActiveRequest): PendingTurn {
  return {
    ownerKey: request.ownerKey,
    id: request.turnId,
    user: request.user,
    assistant: request.assistant,
    status: 'uncertain',
    webSearch: request.webSearch,
    historyBoundary: request.historyBoundary,
    reconciliation: 'checking',
    serverQuestionSaved: false,
  }
}

export function useChat(newsId: string | number | null | undefined, enabled: boolean) {
  const queryClient = useQueryClient()
  const { user, loading: authLoading } = useAuth()
  const { lang } = useLanguage()
  const parsedId = parseNewsId(newsId)
  const viewerId: ViewerId = user?.id ?? 'anonymous'
  const ownerKey = `${parsedId ?? String(newsId ?? '')}:${viewerId}:${lang}`
  const ownerRef = useRef(ownerKey)
  const [inputState, setInputState] = useState<KeyedValue<string>>({ ownerKey: '', value: '' })
  const [webSearchState, setWebSearchState] = useState<KeyedValue<boolean>>({ ownerKey: '', value: false })
  const [phaseState, setPhaseState] = useState<KeyedValue<ChatPhase>>({ ownerKey: '', value: 'idle' })
  const [clearState, setClearState] = useState<KeyedValue<ClearChatState>>({
    ownerKey: '', value: { open: false, clearing: false, error: null },
  })
  const [pendingTurnState, setPendingTurnState] = useState<PendingTurn | null>(null)
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
  const historyKey = useMemo(() => parsedId === null
    ? ['newsWorkflow', 'chatHistory', 'disabled'] as const
    : newsWorkflowKeys.chatHistory(parsedId, lang, viewerId), [lang, parsedId, viewerId])
  const historyQuery = useQuery<ChatHistory>({
    queryKey: historyKey,
    queryFn: ({ signal }) => fetchChatHistory(parsedId ?? 0, signal),
    enabled: enabled && !authLoading && parsedId !== null,
    staleTime: 30_000,
    retry: false,
  })
  const currentPendingTurn = pendingTurnState?.ownerKey === ownerKey ? pendingTurnState : null
  const messages = [
    ...(historyQuery.data?.messages ?? []),
    ...(currentPendingTurn
      ? currentPendingTurn.serverQuestionSaved
        ? [currentPendingTurn.assistant]
        : [currentPendingTurn.user, currentPendingTurn.assistant]
      : []),
  ]
  const phase = enabled && historyQuery.isFetching
    ? 'loading-history'
    : phaseState.ownerKey === ownerKey ? phaseState.value : 'idle'
  const isLoading = phase === 'loading-history' || phase === 'thinking' || phase === 'streaming'
  const confirmingClear = ownerClearState.open
  const isClearing = ownerClearState.clearing
  const clearError = ownerClearState.error

  useLayoutEffect(() => {
    ownerRef.current = ownerKey
    inputRef.current = currentInput
  }, [currentInput, ownerKey])

  const updatePhase = useCallback((nextPhase: ChatPhase) => {
    if (ownerRef.current === ownerKey) setPhaseState({ ownerKey, value: nextPhase })
  }, [ownerKey])

  const setInput = useCallback((value: string) => {
    if (ownerRef.current !== ownerKey) return
    inputRef.current = value
    setInputState({ ownerKey, value })
  }, [ownerKey])

  const updatePendingTurn = useCallback((turnId: string, update: (turn: PendingTurn) => PendingTurn) => {
    if (ownerRef.current !== ownerKey) return
    setPendingTurnState((current) => current?.ownerKey === ownerKey && current.id === turnId
      ? update(current)
      : current)
  }, [ownerKey])

  useEffect(() => () => {
    if (requestRef.current?.ownerKey === ownerKey) {
      requestRef.current.controller.abort()
      requestRef.current = null
    }
    if (clearControllerRef.current?.ownerKey === ownerKey) {
      clearControllerRef.current.controller.abort()
      clearControllerRef.current = null
    }
    if (reconciliationControllerRef.current?.ownerKey === ownerKey) {
      reconciliationControllerRef.current.controller.abort()
      reconciliationControllerRef.current = null
    }
    if (successTimerRef.current) clearTimeout(successTimerRef.current)
  }, [ownerKey])

  const reconcileInterruptedTurn = useCallback(async (snapshot: PendingTurn) => {
    if (parsedId === null || ownerRef.current !== ownerKey || snapshot.ownerKey !== ownerKey) return
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
      const result = reconcileHistory(history, snapshot.historyBoundary, snapshot.user.content)
      queryClient.setQueryData<ChatHistory>(historyKey, history)
      if (result === 'answered') {
        setPendingTurnState((current) => current?.ownerKey === ownerKey && current.id === snapshot.id ? null : current)
        if (inputRef.current === snapshot.user.content) setInput('')
        updatePhase('idle')
      } else if (result === 'question-saved') {
        updatePendingTurn(snapshot.id, (current) => ({
          ...current,
          status: 'uncertain',
          reconciliation: 'partial',
          serverQuestionSaved: true,
        }))
        if (inputRef.current === snapshot.user.content) setInput('')
        updatePhase('error')
      } else {
        updatePendingTurn(snapshot.id, (current) => ({
          ...current,
          status: 'uncertain',
          reconciliation: 'unconfirmed',
          serverQuestionSaved: false,
        }))
        updatePhase('error')
      }
    } catch {
      if (!isCurrent() || controller.signal.aborted) return
      updatePendingTurn(snapshot.id, (current) => ({ ...current, status: 'uncertain', reconciliation: 'failed' }))
      updatePhase('error')
    } finally {
      if (reconciliationControllerRef.current === request) reconciliationControllerRef.current = null
    }
  }, [historyKey, ownerKey, parsedId, queryClient, setInput, updatePendingTurn, updatePhase])

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
    const turnId = reuseTurn && previousTurn ? previousTurn.id : `chat-turn-${++nextTurnId}`
    const userMessage: ChatMessage = reuseTurn && previousTurn
      ? previousTurn.user
      : { id: `${turnId}-user`, role: 'user', content: trimmed }
    const assistantMessage: ChatMessage = reuseTurn && previousTurn
      ? { ...previousTurn.assistant, content: '', web_sources: undefined }
      : { id: `${turnId}-assistant`, role: 'assistant', content: '' }
    const webSearch = currentWebSearch
    if (webSearch) assistantMessage.web_search = true
    const turn: PendingTurn = {
      ownerKey,
      id: turnId,
      user: userMessage,
      assistant: assistantMessage,
      status: 'streaming',
      webSearch,
      historyBoundary: copyHistoryBoundary(queryClient.getQueryData<ChatHistory>(historyKey)?.messages),
      reconciliation: 'idle',
      serverQuestionSaved: false,
    }
    setPendingTurnState(turn)

    const request: ActiveRequest = {
      ownerKey,
      turnId,
      controller: new AbortController(),
      user: userMessage,
      assistant: assistantMessage,
      webSearch,
      historyBoundary: turn.historyBoundary,
    }
    requestRef.current = request
    const isCurrent = () => requestRef.current === request && ownerRef.current === ownerKey
    updatePhase('thinking')

    return (async () => {
      let accumulated = ''
      let webSources: ReturnType<typeof parseWebSources>
      let firstChunk = true
      let frameBuffer = ''
      try {
        for await (const chunk of chatStream(parsedId, trimmed, { webSearch, signal: request.controller.signal })) {
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
        )

        const completedAssistant: ChatMessage = { ...assistantMessage, content: accumulated }
        if (webSources) completedAssistant.web_sources = webSources
        queryClient.setQueryData<ChatHistory>(historyKey, (current) => ({
          messages: [...(current?.messages ?? []), userMessage, completedAssistant],
        }))
        setPendingTurnState((current) => current?.ownerKey === ownerKey && current.id === turnId ? null : current)
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
        setPendingTurnState(uncertainTurn)
        if (!inputRef.current) setInput(trimmed)
        updatePhase('error')
        await reconcileInterruptedTurn(uncertainTurn)
        return false
      } finally {
        if (isCurrent()) requestRef.current = null
      }
    })()
  }, [authLoading, clearState, currentWebSearch, enabled, historyKey, isLoading, ownerKey, parsedId, pendingTurnState, queryClient, reconcileInterruptedTurn, setInput, updatePendingTurn, updatePhase])

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
    setPendingTurnState(uncertainTurn)
    if (!inputRef.current) setInput(request.user.content)
    updatePhase('error')
    void reconcileInterruptedTurn(uncertainTurn)
  }, [ownerKey, reconcileInterruptedTurn, setInput, updatePhase])

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
      setPendingTurnState(interruptedTurn)
      updatePhase('error')
    } else if (currentPendingTurn?.status === 'uncertain') {
      interruptedTurn = currentPendingTurn
    }
    if (reconciliationControllerRef.current?.ownerKey === ownerKey) {
      reconciliationControllerRef.current.controller.abort()
      reconciliationControllerRef.current = null
    }

    let cleared = false
    try {
      await queryClient.cancelQueries({ queryKey: historyKey })
      if (clearRequest.controller.signal.aborted || ownerRef.current !== ownerKey || clearControllerRef.current !== clearRequest) {
        return false
      }
      await clearChatHistory(parsedId, clearRequest.controller.signal)
      if (ownerRef.current !== ownerKey || clearControllerRef.current !== clearRequest) return false
      queryClient.setQueryData<ChatHistory>(historyKey, { messages: [] })
      setPendingTurnState((current) => current?.ownerKey === ownerKey ? null : current)
      updatePhase('idle')
      cleared = true
    } catch {
      if (ownerRef.current === ownerKey && clearControllerRef.current === clearRequest) {
        setClearState({ ownerKey, value: { open: true, clearing: false, error: CLEAR_ERROR } })
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
  }, [authLoading, currentPendingTurn, historyKey, ownerKey, parsedId, queryClient, reconcileInterruptedTurn, setClearState, setPendingTurnState, updatePhase])

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
