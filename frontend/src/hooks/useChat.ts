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

interface KeyedValue<T> {
  ownerKey: string
  value: T
}

interface PendingTurn {
  ownerKey: string
  id: string
  user: ChatMessage
  assistant: ChatMessage
  status: 'streaming' | 'failed'
  webSearch: boolean
}

interface ActiveRequest {
  ownerKey: string
  turnId: string
  controller: AbortController
}

const ASSISTANT_ERROR = '抱歉，我遇到了一些问题，请稍后再试。'
const STOPPED_MESSAGE = '已停止接收本页更新；服务器可能仍在处理这条问题。再次发送会创建新的请求。'
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
  const [clearState, setClearState] = useState<KeyedValue<boolean>>({ ownerKey: '', value: false })
  const [pendingTurnState, setPendingTurnState] = useState<PendingTurn | null>(null)
  const [archivedTurnState, setArchivedTurnState] = useState<KeyedValue<ChatMessage[]>>({ ownerKey: '', value: [] })
  const requestRef = useRef<ActiveRequest | null>(null)
  const clearControllerRef = useRef<{ ownerKey: string; controller: AbortController } | null>(null)
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inputRef = useRef(inputState.ownerKey === ownerKey ? inputState.value : '')
  const currentInput = inputState.ownerKey === ownerKey ? inputState.value : ''
  const currentWebSearch = webSearchState.ownerKey === ownerKey ? webSearchState.value : false
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
  const archivedTurns = archivedTurnState.ownerKey === ownerKey ? archivedTurnState.value : []
  const messages = [
    ...(historyQuery.data?.messages ?? []),
    ...archivedTurns,
    ...(currentPendingTurn ? [currentPendingTurn.user, currentPendingTurn.assistant] : []),
  ]
  const phase = enabled && historyQuery.isFetching
    ? 'loading-history'
    : phaseState.ownerKey === ownerKey ? phaseState.value : 'idle'
  const isLoading = phase === 'loading-history' || phase === 'thinking' || phase === 'streaming'
  const confirmingClear = clearState.ownerKey === ownerKey && clearState.value

  useLayoutEffect(() => {
    ownerRef.current = ownerKey
    inputRef.current = currentInput
  }, [currentInput, ownerKey])

  const updatePhase = useCallback((nextPhase: ChatPhase) => {
    if (ownerRef.current === ownerKey) setPhaseState({ ownerKey, value: nextPhase })
  }, [ownerKey, setPhaseState])

  const setInput = useCallback((value: string) => {
    if (ownerRef.current !== ownerKey) return
    inputRef.current = value
    setInputState({ ownerKey, value })
  }, [ownerKey, setInputState])

  const updatePendingTurn = useCallback((turnId: string, update: (turn: PendingTurn) => PendingTurn) => {
    if (ownerRef.current !== ownerKey) return
    setPendingTurnState((current) => current?.ownerKey === ownerKey && current.id === turnId
      ? update(current)
      : current)
  }, [ownerKey, setPendingTurnState])

  useEffect(() => () => {
    if (requestRef.current?.ownerKey === ownerKey) {
      requestRef.current.controller.abort()
      requestRef.current = null
    }
    if (clearControllerRef.current?.ownerKey === ownerKey) {
      clearControllerRef.current.controller.abort()
      clearControllerRef.current = null
    }
    if (successTimerRef.current) clearTimeout(successTimerRef.current)
  }, [ownerKey])

  const doSend = useCallback((text: string): Promise<boolean> => {
    const trimmed = text.trim()
    if (!trimmed || parsedId === null || !enabled || authLoading || isLoading || requestRef.current) {
      return Promise.resolve(false)
    }
    if (ownerRef.current !== ownerKey) return Promise.resolve(false)

    if (successTimerRef.current) clearTimeout(successTimerRef.current)
    const previousTurn = pendingTurnState?.ownerKey === ownerKey ? pendingTurnState : null
    const isRetry = previousTurn?.status === 'failed' && previousTurn.user.content === trimmed
    if (previousTurn?.status === 'failed' && !isRetry) {
      setArchivedTurnState((current) => ({
        ownerKey,
        value: [...(current.ownerKey === ownerKey ? current.value : []), previousTurn.user, previousTurn.assistant],
      }))
    }

    const turnId = isRetry && previousTurn ? previousTurn.id : `chat-turn-${++nextTurnId}`
    const userMessage: ChatMessage = isRetry && previousTurn
      ? previousTurn.user
      : { id: `${turnId}-user`, role: 'user', content: trimmed }
    const assistantMessage: ChatMessage = isRetry && previousTurn
      ? { ...previousTurn.assistant, content: '', web_sources: undefined }
      : { id: `${turnId}-assistant`, role: 'assistant', content: '' }
    const webSearch = currentWebSearch
    if (webSearch) assistantMessage.web_search = true
    const turn: PendingTurn = { ownerKey, id: turnId, user: userMessage, assistant: assistantMessage, status: 'streaming', webSearch }
    setPendingTurnState(turn)
    setClearState({ ownerKey, value: false })

    const request: ActiveRequest = { ownerKey, turnId, controller: new AbortController() }
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
              updatePendingTurn(turnId, (current) => ({
                ...current,
                assistant: { ...current.assistant, web_sources: sources },
              }))
            },
          )
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
        updatePendingTurn(turnId, (current) => ({
          ...current,
          status: 'failed',
          assistant: { ...current.assistant, content: `${ASSISTANT_ERROR}${message ? ` (${message})` : ''}` },
        }))
        if (!inputRef.current) setInput(trimmed)
        updatePhase('error')
        return false
      } finally {
        if (isCurrent()) requestRef.current = null
      }
    })()
  }, [authLoading, currentWebSearch, enabled, historyKey, isLoading, ownerKey, parsedId, pendingTurnState, queryClient, setArchivedTurnState, setClearState, setPendingTurnState, setInput, updatePendingTurn, updatePhase])

  const handleSend = useCallback(() => doSend(inputRef.current), [doSend])

  const stopWaiting = useCallback(() => {
    const request = requestRef.current
    if (!request || request.ownerKey !== ownerKey) return
    requestRef.current = null
    request.controller.abort()
    updatePendingTurn(request.turnId, (current) => ({
      ...current,
      status: 'failed',
      assistant: {
        ...current.assistant,
        content: current.assistant.content ? `${current.assistant.content}\n\n> ${STOPPED_MESSAGE}` : STOPPED_MESSAGE,
      },
    }))
    updatePhase('error')
  }, [ownerKey, updatePendingTurn, updatePhase])

  const requestClearChat = useCallback(() => {
    if (ownerRef.current === ownerKey) setClearState({ ownerKey, value: true })
  }, [ownerKey, setClearState])

  const cancelClear = useCallback(() => {
    if (ownerRef.current === ownerKey) setClearState({ ownerKey, value: false })
  }, [ownerKey, setClearState])

  const confirmClear = useCallback(async () => {
    if (parsedId === null || authLoading || ownerRef.current !== ownerKey) return false
    setClearState({ ownerKey, value: false })
    const activeRequest = requestRef.current
    if (activeRequest?.ownerKey === ownerKey) {
      requestRef.current = null
      activeRequest.controller.abort()
    }
    const controller = new AbortController()
    clearControllerRef.current = { ownerKey, controller }
    try {
      await queryClient.cancelQueries({ queryKey: historyKey })
      await clearChatHistory(parsedId, controller.signal)
      if (ownerRef.current !== ownerKey || clearControllerRef.current?.controller !== controller) return false
      queryClient.setQueryData<ChatHistory>(historyKey, { messages: [] })
      setPendingTurnState((current) => current?.ownerKey === ownerKey ? null : current)
      setArchivedTurnState({ ownerKey, value: [] })
      updatePhase('idle')
      return true
    } catch {
      return false
    } finally {
      if (clearControllerRef.current?.controller === controller) clearControllerRef.current = null
    }
  }, [authLoading, historyKey, ownerKey, parsedId, queryClient, setArchivedTurnState, setClearState, setPendingTurnState, updatePhase])

  const toggleWebSearch = useCallback(() => {
    if (ownerRef.current === ownerKey) {
      setWebSearchState((current) => ({
        ownerKey,
        value: !(current.ownerKey === ownerKey && current.value),
      }))
    }
  }, [ownerKey, setWebSearchState])

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
    requestClearChat,
    cancelClear,
    confirmClear,
    webSearch: currentWebSearch,
    toggleWebSearch,
  }
}
