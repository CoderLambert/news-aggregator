import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLanguage } from '@/context/useLanguage'
import {
  createResearchStream,
  deleteResearchSession,
  openResearchSessionStream,
  researchChatStream,
} from '@/services/researchApi'
import {
  researchKeys,
  researchResultsOptions,
  researchSessionOptions,
  researchSessionsOptions,
} from '@/services/researchQueries'
import type { ResearchViewerId } from '@/services/researchQueries'
import { isRecord } from '@/types/news'
import type {
  JsonRecord,
  ResearchEvent,
  ResearchMessage,
  ResearchPhase,
  ResearchSearchResult,
  ResearchSessionDetail,
  ResearchToolCall,
} from '@/types/research'
import { parseResearchEvent } from '@/types/research'
import {
  applyResearchEvent,
  createResearchTask,
  markResearchTaskCancelled,
  markResearchTaskInterrupted,
  researchTaskMessages,
  resetResearchTaskForReplay,
} from './researchTask'
import type { ResearchTaskSnapshot } from './researchTask'

const ERROR_MESSAGE = '研究过程中遇到了问题，请稍后再试。'
const CANCEL_NOTICE = '已停止接收流式进度。服务器任务可能仍在运行；需要时可继续接收。'

interface ResearchSelection {
  viewerId: ResearchViewerId | null
  sessionId: string | null
  newSession: boolean
  draftKey: string | null
}

interface ActiveConnection {
  id: string
  taskKey: string
  controller: AbortController
  selectOnCreate: boolean
}

function selectionForViewer(selection: ResearchSelection, viewerId: ResearchViewerId | null): ResearchSelection {
  return selection.viewerId === viewerId
    ? selection
    : { viewerId, sessionId: null, newSession: false, draftKey: null }
}

function taskStorageKey(viewerId: ResearchViewerId, sessionId: string): string {
  return `${String(viewerId)}:session:${sessionId}`
}

function draftStorageKey(viewerId: ResearchViewerId, taskId: string): string {
  return `${String(viewerId)}:draft:${taskId}`
}

function safeParseJson(value: string): JsonRecord {
  try {
    const parsed: unknown = JSON.parse(value)
    return isRecord(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function buildToolSummary(name: string, result: JsonRecord): string {
  if (typeof result.error === 'string') return `❌ ${result.error}`
  if (name === 'search_news') return `找到 ${typeof result.total === 'number' ? result.total : 0} 篇相关文章`
  if (name === 'fetch_article') return '已获取文章'
  if (name === 'search_web') return `联网搜索到 ${Array.isArray(result.results) ? result.results.length : 0} 条结果`
  if (name === 'fetch_webpage') return '已抓取网页'
  if (name === 'analyze_topic') return `分析完成: ${typeof result.total_articles === 'number' ? result.total_articles : 0} 篇文章`
  if (name === 'generate_report') return '报告结构生成'
  return `${name} 完成`
}

function parseToolArguments(value: string): JsonRecord {
  return safeParseJson(value)
}

function emptyToolCall(callId: string, name: string, args: JsonRecord): ResearchToolCall {
  return {
    callId,
    name,
    args,
    summary: '',
    status: 'done',
    articles: [],
    webResults: [],
    articleTitle: '',
    articleId: null,
    articleSource: '',
    articleUrl: '',
    contentTruncated: false,
    originalLength: 0,
    contentLength: 0,
  }
}

function hydrateStoredToolResult(call: ResearchToolCall, rawContent: string): ResearchToolCall {
  const data = safeParseJson(rawContent)
  const event = parseResearchEvent({
    type: 'tool_result',
    call_id: call.callId,
    summary: buildToolSummary(call.name, data),
    ...data,
  })
  if (!event || event.type !== 'tool_result') return call
  return {
    ...call,
    summary: event.summary,
    articles: event.articles,
    webResults: event.results,
    articleTitle: event.title,
    articleId: event.id,
    articleSource: event.source,
    articleUrl: event.url,
    contentTruncated: event.content_truncated,
    originalLength: event.original_length,
    contentLength: event.length,
  }
}

function convertMessages(rawMessages: ResearchSessionDetail['messages']): ResearchMessage[] {
  const messages: ResearchMessage[] = []
  rawMessages.forEach((message, index) => {
    if (message.role === 'system') return
    if (message.role === 'user') {
      messages.push({ id: `stored:${index}`, role: 'user', content: message.content })
      return
    }
    if (message.role === 'assistant') {
      const toolCalls = (message.tool_calls ?? []).map((toolCall) => ({
        ...emptyToolCall(
          toolCall.id,
          toolCall.function.name,
          parseToolArguments(toolCall.function.arguments),
        ),
      }))
      messages.push({ id: `stored:${index}`, role: 'assistant', content: message.content, toolCalls })
      return
    }
    if (message.role === 'tool') {
      const assistant = messages.at(-1)
      if (!assistant || assistant.role !== 'assistant' || !message.tool_call_id) return
      const matchingCall = assistant.toolCalls?.find((call) => call.callId === message.tool_call_id)
      if (!matchingCall) return
      assistant.toolCalls = assistant.toolCalls?.map((call) => call.callId === message.tool_call_id
        ? hydrateStoredToolResult(call, message.content)
        : call)
    }
  })
  return messages
}

function isActivePhase(task: ResearchTaskSnapshot): boolean {
  return task.phase === 'thinking' || task.phase === 'tool_calling' || task.phase === 'streaming'
}

function sessionHasSavedTask(session: ResearchSessionDetail, task: ResearchTaskSnapshot): boolean {
  return session.message_count > task.startingMessageCount
}

function querySessionMessages(
  queryClient: ReturnType<typeof useQueryClient>,
  viewerId: ResearchViewerId,
  lang: 'zh' | 'en',
  sessionId: string,
): { messages: ResearchMessage[]; messageCount: number } {
  const cached = queryClient.getQueryData<ResearchSessionDetail>(researchKeys.session(viewerId, lang, sessionId))
  return { messages: cached ? convertMessages(cached.messages) : [], messageCount: cached?.message_count ?? 0 }
}

export function useResearch(viewerId: ResearchViewerId | null) {
  const queryClient = useQueryClient()
  const { lang } = useLanguage()
  const queryViewerId = viewerId ?? 'anonymous'
  const sessionsQuery = useQuery({
    ...researchSessionsOptions(queryViewerId, lang),
    enabled: viewerId !== null,
  })
  const sessions = sessionsQuery.data?.results ?? []
  const [selection, setSelection] = useState<ResearchSelection>({
    viewerId,
    sessionId: null,
    newSession: false,
    draftKey: null,
  })
  const currentSelection = selectionForViewer(selection, viewerId)
  const activeSessionId = currentSelection.sessionId ?? (currentSelection.newSession ? null : sessions[0]?.id ?? null)
  const sessionQuery = useQuery({
    ...researchSessionOptions(queryViewerId, lang, activeSessionId ?? ''),
    enabled: viewerId !== null && Boolean(activeSessionId),
  })
  const resultsQuery = useQuery({
    ...researchResultsOptions(queryViewerId, lang, activeSessionId ?? ''),
    enabled: viewerId !== null && Boolean(activeSessionId),
  })
  const deleteMutation = useMutation({
    mutationFn: deleteResearchSession,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: researchKeys.sessions(queryViewerId, lang) }),
  })

  const [taskSnapshots, setTaskSnapshots] = useState<Map<string, ResearchTaskSnapshot>>(() => new Map())
  const taskSnapshotsRef = useRef(taskSnapshots)
  const connectionRef = useRef<ActiveConnection | null>(null)
  const taskSequenceRef = useRef(0)
  const activeSessionIdRef = useRef<string | null>(activeSessionId)
  const activeDraftKeyRef = useRef<string | null>(currentSelection.draftKey)
  const sendLockRef = useRef(false)

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId
    activeDraftKeyRef.current = currentSelection.draftKey
  }, [activeSessionId, currentSelection.draftKey])

  useEffect(() => () => {
    const connection = connectionRef.current
    connectionRef.current = null
    connection?.controller.abort()
  }, [])

  const activeTaskKey = activeSessionId
    ? taskStorageKey(queryViewerId, activeSessionId)
    : currentSelection.draftKey
  const activeTask = activeTaskKey ? taskSnapshots.get(activeTaskKey) ?? null : null

  const messages = useMemo(() => {
    if (activeTask) return researchTaskMessages(activeTask)
    return sessionQuery.data ? convertMessages(sessionQuery.data.messages) : []
  }, [activeTask, sessionQuery.data])
  const searchResults: ResearchSearchResult[] = resultsQuery.data?.results ?? []
  const phase: ResearchPhase = activeTask?.phase ?? 'idle'
  const activeToolCalls = activeTask?.assistant.toolCalls ?? []

  const publishTasks = useCallback((next: Map<string, ResearchTaskSnapshot>) => {
    taskSnapshotsRef.current = next
    setTaskSnapshots(next)
  }, [])

  const putTask = useCallback((key: string, task: ResearchTaskSnapshot) => {
    const next = new Map(taskSnapshotsRef.current)
    next.set(key, task)
    publishTasks(next)
  }, [publishTasks])

  const removeTask = useCallback((key: string, taskId?: string) => {
    const current = taskSnapshotsRef.current.get(key)
    if (!current || (taskId && current.id !== taskId)) return
    const next = new Map(taskSnapshotsRef.current)
    next.delete(key)
    publishTasks(next)
  }, [publishTasks])

  const setSelectionForSession = useCallback((sessionId: string) => {
    activeSessionIdRef.current = sessionId
    activeDraftKeyRef.current = null
    setSelection({ viewerId, sessionId, newSession: false, draftKey: null })
  }, [viewerId])

  const pauseCurrentConnection = useCallback((notice = CANCEL_NOTICE) => {
    const connection = connectionRef.current
    if (!connection) return
    connectionRef.current = null
    connection.controller.abort()
    sendLockRef.current = false
    const current = taskSnapshotsRef.current.get(connection.taskKey)
    if (!current || current.id !== connection.id || !isActivePhase(current)) return
    putTask(connection.taskKey, markResearchTaskCancelled(current, notice))
  }, [putTask])

  const connectionIsCurrent = useCallback((connection: ActiveConnection): boolean => {
    return connectionRef.current === connection && !connection.controller.signal.aborted
  }, [])

  const currentConnectionTask = useCallback((connection: ActiveConnection): ResearchTaskSnapshot | null => {
    const task = taskSnapshotsRef.current.get(connection.taskKey)
    return task?.id === connection.id ? task : null
  }, [])

  const refreshCompletedTask = useCallback(async (connection: ActiveConnection, task: ResearchTaskSnapshot) => {
    if (viewerId === null || !task.sessionId) return
    const sessionId = task.sessionId
    const sessionKey = researchKeys.session(queryViewerId, lang, sessionId)
    const sessionsKey = researchKeys.sessions(queryViewerId, lang)
    const resultsKey = researchKeys.results(queryViewerId, lang, sessionId)
    try {
      const session = await queryClient.fetchQuery({
        ...researchSessionOptions(queryViewerId, lang, sessionId),
        staleTime: 0,
      })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: sessionsKey }),
        queryClient.invalidateQueries({ queryKey: resultsKey }),
      ])
      const current = taskSnapshotsRef.current.get(taskStorageKey(queryViewerId, sessionId))
      if (sessionHasSavedTask(session, task) && current?.id === connection.id && current.phase === 'success') {
        removeTask(taskStorageKey(queryViewerId, sessionId), connection.id)
      }
    } catch {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: sessionKey, exact: true }),
        queryClient.invalidateQueries({ queryKey: sessionsKey, exact: true }),
        queryClient.invalidateQueries({ queryKey: resultsKey, exact: true }),
      ])
    }
  }, [lang, queryClient, queryViewerId, removeTask, viewerId])

  const consumeResearchEvents = useCallback(async (connection: ActiveConnection, events: AsyncIterable<ResearchEvent>) => {
    try {
      for await (const event of events) {
        if (!connectionIsCurrent(connection)) return
        const current = currentConnectionTask(connection)
        if (!current) return

        if (event.type === 'session_created') {
          const nextTask = applyResearchEvent(current, event)
          if (nextTask.sessionId) {
            const oldKey = connection.taskKey
            const sessionKey = taskStorageKey(queryViewerId, nextTask.sessionId)
            const nextTasks = new Map(taskSnapshotsRef.current)
            if (oldKey !== sessionKey) nextTasks.delete(oldKey)
            nextTasks.set(sessionKey, nextTask)
            connection.taskKey = sessionKey
            publishTasks(nextTasks)
            if (connection.selectOnCreate && activeDraftKeyRef.current === oldKey) {
              setSelectionForSession(nextTask.sessionId)
              connection.selectOnCreate = false
            }
          }
          continue
        }

        const nextTask = applyResearchEvent(current, event)
        if (nextTask !== current) putTask(connection.taskKey, nextTask)
        if (nextTask !== current && nextTask.phase === 'success') void refreshCompletedTask(connection, nextTask)
      }

      if (!connectionIsCurrent(connection)) return
      const finalTask = currentConnectionTask(connection)
      if (finalTask && isActivePhase(finalTask)) {
        putTask(connection.taskKey, markResearchTaskInterrupted(
          finalTask,
          '连接已结束，但没有收到研究完成事件。可以继续接收已有任务，或在没有会话时重新发起。',
        ))
      }
    } catch (error) {
      if (!connectionIsCurrent(connection)) return
      const task = currentConnectionTask(connection)
      if (!task) return
      const message = error instanceof Error ? error.message : ERROR_MESSAGE
      const isAuthError = /\b(401|403)\b/.test(message)
      const interrupted = markResearchTaskInterrupted(
        task,
        isAuthError ? '请先登录后再使用研究助手 🔐' : ERROR_MESSAGE,
      )
      putTask(connection.taskKey, isAuthError
        ? { ...interrupted, recovery: 'none' }
        : interrupted)
    }
  }, [connectionIsCurrent, currentConnectionTask, publishTasks, putTask, queryViewerId, refreshCompletedTask, setSelectionForSession])

  const runStreamTask = useCallback(async (task: ResearchTaskSnapshot, mode: 'create' | 'chat') => {
    if (connectionRef.current || sendLockRef.current || viewerId === null) return
    const taskKey = task.sessionId
      ? taskStorageKey(queryViewerId, task.sessionId)
      : draftStorageKey(queryViewerId, task.id)
    putTask(taskKey, task)
    if (!task.sessionId) {
      activeDraftKeyRef.current = taskKey
      setSelection({ viewerId, sessionId: null, newSession: true, draftKey: taskKey })
    }
    const connection: ActiveConnection = {
      id: task.id,
      taskKey,
      controller: new AbortController(),
      selectOnCreate: task.sessionId === null,
    }
    connectionRef.current = connection
    sendLockRef.current = true

    try {
      const events = mode === 'create'
        ? createResearchStream(task.query, { localOnly: task.localOnly, signal: connection.controller.signal })
        : researchChatStream(task.sessionId ?? '', task.query, { localOnly: task.localOnly, signal: connection.controller.signal })
      await consumeResearchEvents(connection, events)
    } finally {
      if (connectionRef.current === connection) connectionRef.current = null
      sendLockRef.current = false
    }
  }, [consumeResearchEvents, putTask, queryViewerId, viewerId])

  const handleSend = useCallback(async (query: string, { localOnly = false }: { localOnly?: boolean } = {}) => {
    const normalizedQuery = query.trim()
    if (!normalizedQuery || connectionRef.current || sendLockRef.current || viewerId === null) return
    if (activeTask?.recovery === 'resume') return

    const sessionId = activeSessionId
    const currentTask = activeTask
    const priorMessages = sessionId
      ? currentTask?.sessionId === sessionId && currentTask.phase === 'success'
        ? researchTaskMessages(currentTask).filter((message) => !message.id.endsWith(':notice'))
        : querySessionMessages(queryClient, queryViewerId, lang, sessionId).messages
      : []
    const { messageCount } = sessionId
      ? querySessionMessages(queryClient, queryViewerId, lang, sessionId)
      : { messageCount: 0 }
    const taskId = `research-${Date.now()}-${++taskSequenceRef.current}`
    const task = createResearchTask(taskId, normalizedQuery, localOnly, priorMessages, sessionId, messageCount)
    await runStreamTask(task, sessionId ? 'chat' : 'create')
  }, [activeSessionId, activeTask, lang, queryClient, queryViewerId, runStreamTask, viewerId])

  const handleNewSession = useCallback(() => {
    pauseCurrentConnection('已切换到新会话；原服务端任务可能仍在运行，可从历史会话继续接收。')
    activeSessionIdRef.current = null
    activeDraftKeyRef.current = null
    setSelection({ viewerId, sessionId: null, newSession: true, draftKey: null })
  }, [viewerId, pauseCurrentConnection])

  const handleSelectSession = useCallback((sessionId: string) => {
    if (sessionId === activeSessionId) return
    pauseCurrentConnection('已切换到其他会话；原服务端任务可能仍在运行，切回后可继续接收。')
    activeSessionIdRef.current = sessionId
    activeDraftKeyRef.current = null
    setSelection({ viewerId, sessionId, newSession: false, draftKey: null })
  }, [activeSessionId, pauseCurrentConnection, viewerId])

  const handleRetry = useCallback(async () => {
    const task = activeTask
    if (!task || task.phase !== 'error' || task.recovery !== 'retry' || viewerId === null) return
    const next = createResearchTask(
      `research-${Date.now()}-${++taskSequenceRef.current}`,
      task.query,
      task.localOnly,
      task.baseMessages,
      task.sessionId,
      task.startingMessageCount,
    )
    await runStreamTask(next, next.sessionId ? 'chat' : 'create')
  }, [activeTask, runStreamTask, viewerId])

  const handleResume = useCallback(async () => {
    const task = activeTask
    if (!task || task.recovery !== 'resume' || !task.sessionId || connectionRef.current || sendLockRef.current || viewerId === null) return
    const next = resetResearchTaskForReplay(task, `research-${Date.now()}-${++taskSequenceRef.current}`)
    const taskKey = taskStorageKey(queryViewerId, task.sessionId)
    putTask(taskKey, next)
    const connection: ActiveConnection = {
      id: next.id,
      taskKey,
      controller: new AbortController(),
      selectOnCreate: false,
    }
    connectionRef.current = connection
    sendLockRef.current = true
    try {
      const stream = await openResearchSessionStream(task.sessionId, connection.controller.signal)
      if (!connectionIsCurrent(connection)) return
      if (stream.kind === 'session') {
        const sessionKey = researchKeys.session(queryViewerId, lang, task.sessionId)
        queryClient.setQueryData(sessionKey, stream.session)
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: researchKeys.sessions(queryViewerId, lang) }),
          queryClient.invalidateQueries({ queryKey: researchKeys.results(queryViewerId, lang, task.sessionId) }),
        ])
        if (sessionHasSavedTask(stream.session, next)) {
          removeTask(taskKey, next.id)
        } else {
          putTask(taskKey, {
            ...next,
            phase: 'error',
            recovery: 'retry',
            notice: '服务器任务已结束，但没有保存完整回答。可以重新研究此问题。',
          })
        }
      } else {
        await consumeResearchEvents(connection, stream.events)
      }
    } catch (error) {
      if (!connectionIsCurrent(connection)) return
      const current = currentConnectionTask(connection)
      if (current) putTask(taskKey, markResearchTaskInterrupted(
        current,
        error instanceof Error && /\b(401|403)\b/.test(error.message)
          ? '请先登录后再使用研究助手 🔐'
          : ERROR_MESSAGE,
      ))
    } finally {
      if (connectionRef.current === connection) connectionRef.current = null
      sendLockRef.current = false
    }
  }, [activeTask, connectionIsCurrent, currentConnectionTask, consumeResearchEvents, lang, putTask, removeTask, queryClient, queryViewerId, viewerId])

  const handleCancel = useCallback(() => {
    pauseCurrentConnection(CANCEL_NOTICE)
  }, [pauseCurrentConnection])

  const handleDeleteSession = useCallback(async (sessionId: string) => {
    try {
      await deleteMutation.mutateAsync(sessionId)
      const storageKey = taskStorageKey(queryViewerId, sessionId)
      removeTask(storageKey)
      if (activeSessionId === sessionId) handleNewSession()
    } catch (error) {
      console.error('Failed to delete research session:', error)
    }
  }, [activeSessionId, deleteMutation, handleNewSession, queryViewerId, removeTask])

  const refetchSessions = sessionsQuery.refetch
  const loadSessions = useCallback(() => refetchSessions(), [refetchSessions])

  return {
    sessions,
    activeSessionId,
    messages,
    phase,
    activeToolCalls,
    loadingSessions: sessionsQuery.isPending,
    searchResults,
    hasRecoverableTask: activeTask?.recovery === 'resume',
    recoveryAction: activeTask?.recovery ?? 'none',
    handleSend,
    handleNewSession,
    handleSelectSession,
    handleDeleteSession,
    handleCancel,
    handleResume,
    handleRetry,
    loadSessions,
  }
}
