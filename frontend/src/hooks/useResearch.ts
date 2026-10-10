import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLanguage } from '@/context/useLanguage'
import {
  cancelResearchRun,
  createResearchStream,
  deleteResearchSession,
  openResearchSessionStream,
  researchChatStream,
  resumeQueuedResearchRun,
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
const RECOVERY_STORAGE_PREFIX = 'news-aggregator:research-recovery:v1'

function newIdempotencyKey(): string {
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

interface StoredResearchRecovery {
  version: 1
  taskId: string
  sessionId: string
  query: string
  localOnly: boolean
  startingMessageCount: number
  idempotencyKey: string | null
  runId: string | null
  mode: 'create' | 'chat' | null
}

interface ResearchSelection {
  viewerId: ResearchViewerId | null
  sessionId: string | null
  newSession: boolean
  draftKey: string | null
}

interface ActiveConnection {
  id: string
  viewerId: ResearchViewerId
  taskKey: string
  controller: AbortController
  selectOnCreate: boolean
  idempotencyKey: string | null
  runId: string | null
  requestMode: 'create' | 'chat' | null
  cancelRequested: boolean
  cancelCallStarted: boolean
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


const PENDING_CREATE_PREFIX = 'news-aggregator:research-pending-create:v1'

interface PendingResearchCreate {
  version: 1
  taskId: string
  idempotencyKey: string
  query: string
  localOnly: boolean
  createdAt: number
}

function pendingCreateStorageKey(viewerId: ResearchViewerId): string {
  return PENDING_CREATE_PREFIX + ':' + encodeURIComponent(String(viewerId))
}

function savePendingCreate(viewerId: ResearchViewerId, task: ResearchTaskSnapshot, key: string): void {
  if (task.sessionId) return
  const value: PendingResearchCreate = {
    version: 1, taskId: task.id, idempotencyKey: key, query: task.query,
    localOnly: task.localOnly, createdAt: Date.now(),
  }
  try {
    window.sessionStorage.setItem(pendingCreateStorageKey(viewerId), JSON.stringify(value))
  } catch {
    // An unavailable session store cannot provide pre-header recovery.
  }
}

function clearPendingCreate(viewerId: ResearchViewerId, expectedKey?: string): void {
  try {
    if (expectedKey) {
      const current = loadPendingCreate(viewerId)
      if (!current || current.idempotencyKey !== expectedKey) return
    }
    window.sessionStorage.removeItem(pendingCreateStorageKey(viewerId))
  } catch {
    // Browser storage is optional.
  }
}

function loadPendingCreate(viewerId: ResearchViewerId): PendingResearchCreate | null {
  try {
    const raw: unknown = JSON.parse(window.sessionStorage.getItem(pendingCreateStorageKey(viewerId)) ?? 'null')
    if (!isRecord(raw)) return null
    const valid = raw.version === 1 && typeof raw.taskId === 'string'
      && typeof raw.idempotencyKey === 'string' && /^[\x20-\x7e]{1,64}$/.test(raw.idempotencyKey)
      && typeof raw.query === 'string' && raw.query.length > 0 && raw.query.length <= 20_000
      && typeof raw.localOnly === 'boolean' && typeof raw.createdAt === 'number'
      && Number.isFinite(raw.createdAt) && raw.createdAt <= Date.now()
      && Date.now() - raw.createdAt <= 24 * 60 * 60 * 1000
    if (valid) return raw as unknown as PendingResearchCreate
    clearPendingCreate(viewerId)
  } catch {
    // Invalid JSON must never turn into a fresh paid request.
  }
  return null
}

function pendingCreateSnapshot(pending: PendingResearchCreate): ResearchTaskSnapshot {
  return {
    ...createResearchTask(pending.taskId, pending.query, pending.localOnly, [], null),
    phase: 'cancelled',
    recovery: 'resume',
    notice: '无法确认原研究请求是否到达服务器。继续接收将使用相同请求标识，不会创建第二个不同的请求。',
  }
}

function recoveryStorageKey(viewerId: ResearchViewerId, sessionId: string): string {
  return `${RECOVERY_STORAGE_PREFIX}:${encodeURIComponent(String(viewerId))}:${encodeURIComponent(sessionId)}`
}

function saveStoredRecovery(
  viewerId: ResearchViewerId,
  task: ResearchTaskSnapshot,
  idempotencyKey: string | null = null,
  runId: string | null = null,
  mode: 'create' | 'chat' | null = null,
): void {
  if (!task.sessionId || typeof window === 'undefined') return
  const stored: StoredResearchRecovery = {
    version: 1,
    taskId: task.id,
    sessionId: task.sessionId,
    query: task.query,
    localOnly: task.localOnly,
    startingMessageCount: task.startingMessageCount,
    idempotencyKey,
    runId,
    mode,
  }
  try {
    window.sessionStorage.setItem(recoveryStorageKey(viewerId, task.sessionId), JSON.stringify(stored))
  } catch {
    // Recovery remains available for this mounted panel if browser storage is disabled.
  }
}

function clearStoredRecovery(viewerId: ResearchViewerId, sessionId: string): void {
  if (typeof window === 'undefined') return
  try { window.sessionStorage.removeItem(recoveryStorageKey(viewerId, sessionId)) } catch { /* storage is optional */ }
}

function clearViewerRecovery(viewerId: ResearchViewerId): void {
  if (typeof window === 'undefined') return
  clearPendingCreate(viewerId)
  const prefix = `${RECOVERY_STORAGE_PREFIX}:${encodeURIComponent(String(viewerId))}:`
  try {
    const keys: string[] = []
    for (let index = 0; index < window.sessionStorage.length; index += 1) {
      const key = window.sessionStorage.key(index)
      if (key?.startsWith(prefix)) keys.push(key)
    }
    keys.forEach((key) => window.sessionStorage.removeItem(key))
  } catch {
    // Storage is optional; viewer-scoped keys still prevent cross-owner recovery.
  }
}


function loadStoredRecovery(viewerId: ResearchViewerId, sessionId: string): StoredResearchRecovery | null {
  if (typeof window === 'undefined') return null
  try {
    const value: unknown = JSON.parse(window.sessionStorage.getItem(recoveryStorageKey(viewerId, sessionId)) ?? 'null')
    if (!isRecord(value)
      || value.version !== 1
      || typeof value.taskId !== 'string'
      || value.sessionId !== sessionId
      || typeof value.query !== 'string'
      || value.query.length > 20_000
      || typeof value.localOnly !== 'boolean'
      || typeof value.startingMessageCount !== 'number'
      || !Number.isInteger(value.startingMessageCount)
      || value.startingMessageCount < 0
      || (value.idempotencyKey !== undefined && value.idempotencyKey !== null && typeof value.idempotencyKey !== 'string')
      || (value.runId !== undefined && value.runId !== null && typeof value.runId !== 'string')
      || (value.mode !== undefined && value.mode !== null && value.mode !== 'create' && value.mode !== 'chat')) {
      clearStoredRecovery(viewerId, sessionId)
      return null
    }
    return {
      version: 1,
      taskId: value.taskId,
      sessionId,
      query: value.query,
      localOnly: value.localOnly,
      startingMessageCount: value.startingMessageCount,
      idempotencyKey: typeof value.idempotencyKey === 'string' ? value.idempotencyKey : null,
      runId: typeof value.runId === 'string' ? value.runId : null,
      mode: value.mode === 'create' || value.mode === 'chat' ? value.mode : null,
    }
  } catch {
    return null
  }
}

function restoreStoredTask(
  stored: StoredResearchRecovery,
  baseMessages: ResearchMessage[],
): ResearchTaskSnapshot {
  return {
    ...createResearchTask(
      stored.taskId,
      stored.query,
      stored.localOnly,
      baseMessages,
      stored.sessionId,
      stored.startingMessageCount,
    ),
    phase: 'cancelled',
    recovery: 'resume',
    notice: '正在检查已有的服务器任务；不会自动重新发起研究。',
  }
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
  const [selection, setSelection] = useState<ResearchSelection>(() => {
    const pending = viewerId !== null ? loadPendingCreate(viewerId) : null
    return {
      viewerId, sessionId: null, newSession: Boolean(pending),
      draftKey: pending && viewerId !== null ? draftStorageKey(viewerId, pending.taskId) : null,
    }
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

  const [taskSnapshots, setTaskSnapshots] = useState<Map<string, ResearchTaskSnapshot>>(() => {
    const pending = viewerId !== null ? loadPendingCreate(viewerId) : null
    return pending && viewerId !== null
      ? new Map([[draftStorageKey(viewerId, pending.taskId), pendingCreateSnapshot(pending)]])
      : new Map()
  })
  const [connectionBusy, setConnectionBusy] = useState(false)
  const taskSnapshotsRef = useRef(taskSnapshots)
  const connectionRef = useRef<ActiveConnection | null>(null)
  const taskSequenceRef = useRef(0)
  const activeSessionIdRef = useRef<string | null>(activeSessionId)
  const activeDraftKeyRef = useRef<string | null>(currentSelection.draftKey)
  const probeSelectionRef = useRef<{ key: string | null; generation: number }>({ key: null, generation: 0 })
  const currentViewerIdRef = useRef(viewerId)
  const startedProbeGenerationRef = useRef(-1)
  const skipAutoProbeKeyRef = useRef<string | null>(null)
  const sendLockRef = useRef(false)

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId
    activeDraftKeyRef.current = currentSelection.draftKey
  }, [activeSessionId, currentSelection.draftKey])
  useLayoutEffect(() => {
    currentViewerIdRef.current = viewerId
  }, [viewerId])

  useEffect(() => () => {
    const connection = connectionRef.current
    connectionRef.current = null
    connection?.controller.abort()
  }, [])

  const previousViewerIdRef = useRef(viewerId)
  useEffect(() => {
    const previousViewerId = previousViewerIdRef.current
    if (previousViewerId === viewerId) return
    previousViewerIdRef.current = viewerId
    if (previousViewerId !== null) clearViewerRecovery(previousViewerId)
    const connection = connectionRef.current
    connectionRef.current = null
    connection?.controller.abort()
    sendLockRef.current = false
    setConnectionBusy(false)
    const pending = viewerId !== null ? loadPendingCreate(viewerId) : null
    const next = pending && viewerId !== null
      ? new Map([[draftStorageKey(viewerId, pending.taskId), pendingCreateSnapshot(pending)]])
      : new Map<string, ResearchTaskSnapshot>()
    taskSnapshotsRef.current = next
    setTaskSnapshots(next)
    setSelection({
      viewerId, sessionId: null, newSession: Boolean(pending),
      draftKey: pending && viewerId !== null ? draftStorageKey(viewerId, pending.taskId) : null,
    })
  }, [viewerId])

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
    setConnectionBusy(false)
    const current = taskSnapshotsRef.current.get(connection.taskKey)
    if (!current || current.id !== connection.id || !isActivePhase(current)) return
    const cancelled = markResearchTaskCancelled(current, notice)
    const pending = !current.sessionId && loadPendingCreate(connection.viewerId)
    putTask(connection.taskKey, pending && pending.idempotencyKey === connection.idempotencyKey
      ? { ...cancelled, recovery: 'resume' }
      : cancelled)
  }, [putTask])

  const connectionIsCurrent = useCallback((connection: ActiveConnection): boolean => {
    return connectionRef.current === connection
      && !connection.controller.signal.aborted
      && connection.viewerId === currentViewerIdRef.current
  }, [])

  const currentConnectionTask = useCallback((connection: ActiveConnection): ResearchTaskSnapshot | null => {
    const task = taskSnapshotsRef.current.get(connection.taskKey)
    return task?.id === connection.id ? task : null
  }, [])
  const cancelConnectionOnServer = useCallback(async (connection: ActiveConnection) => {
    if (!connection.cancelRequested || connection.cancelCallStarted) return
    if (connection.viewerId !== currentViewerIdRef.current) return
    const task = currentConnectionTask(connection)
    if (!task?.sessionId || !connection.runId) return
    connection.cancelCallStarted = true
    let outcomeStatus = ''
    try {
      const response = await cancelResearchRun(task.sessionId, connection.runId)
      if (isRecord(response) && typeof response.status === 'string') outcomeStatus = response.status
    } catch {
      outcomeStatus = ''
    }
    if (!connectionIsCurrent(connection)) return
    const cancellationConfirmed = outcomeStatus === 'cancelled'
    pauseCurrentConnection(cancellationConfirmed ? '研究任务已取消。' : CANCEL_NOTICE)
    if (cancellationConfirmed) {
      const current = taskSnapshotsRef.current.get(connection.taskKey)
      if (current?.id === connection.id) {
        putTask(connection.taskKey, {
          ...current,
          recovery: 'retry',
          notice: '研究任务已取消。只有明确重新研究才会创建新任务。',
        })
      }
    }
  }, [connectionIsCurrent, currentConnectionTask, pauseCurrentConnection, putTask])

  const attachSessionId = useCallback((connection: ActiveConnection, sessionId: string) => {
    if (!connectionIsCurrent(connection)) return
    const current = currentConnectionTask(connection)
    if (!current) return
    if (current.sessionId === sessionId) {
      saveStoredRecovery(queryViewerId, current, connection.idempotencyKey, connection.runId, connection.requestMode)
      if (connection.idempotencyKey) clearPendingCreate(queryViewerId, connection.idempotencyKey)
      void cancelConnectionOnServer(connection)
      return
    }

    const oldKey = connection.taskKey
    const sessionKey = taskStorageKey(queryViewerId, sessionId)
    const nextTask = { ...current, sessionId }
    const nextTasks = new Map(taskSnapshotsRef.current)
    if (oldKey !== sessionKey) nextTasks.delete(oldKey)
    nextTasks.set(sessionKey, nextTask)
    connection.taskKey = sessionKey
    saveStoredRecovery(queryViewerId, nextTask, connection.idempotencyKey, connection.runId, connection.requestMode)
    if (connection.idempotencyKey) clearPendingCreate(queryViewerId, connection.idempotencyKey)
    publishTasks(nextTasks)
    void cancelConnectionOnServer(connection)
    if (connection.selectOnCreate && activeDraftKeyRef.current === oldKey) {
      skipAutoProbeKeyRef.current = sessionKey
      setSelectionForSession(sessionId)
      connection.selectOnCreate = false
    }
    void queryClient.invalidateQueries({ queryKey: researchKeys.sessions(queryViewerId, lang), exact: true })
  }, [cancelConnectionOnServer, connectionIsCurrent, currentConnectionTask, lang, publishTasks, queryClient, queryViewerId, setSelectionForSession])

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
        clearStoredRecovery(queryViewerId, sessionId)
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
          attachSessionId(connection, event.session_id)
          continue
        }

        const nextTask = applyResearchEvent(current, event)
        if (nextTask !== current) putTask(connection.taskKey, nextTask)
        if (nextTask.phase === 'success') {
          if (nextTask !== current) await refreshCompletedTask(connection, nextTask)
          return
        }
        if (nextTask.phase === 'error') return
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
  }, [attachSessionId, connectionIsCurrent, currentConnectionTask, putTask, refreshCompletedTask])

  const runStreamTask = useCallback((
    task: ResearchTaskSnapshot,
    mode: 'create' | 'chat',
    existingIdempotencyKey?: string,
  ): boolean => {
    if (connectionRef.current || sendLockRef.current || viewerId === null) return false
    const taskKey = task.sessionId
      ? taskStorageKey(queryViewerId, task.sessionId)
      : draftStorageKey(queryViewerId, task.id)
    const idempotencyKey = existingIdempotencyKey ?? newIdempotencyKey()
    if (task.sessionId) saveStoredRecovery(queryViewerId, task, idempotencyKey, null, mode)
    else if (mode === 'create') savePendingCreate(queryViewerId, task, idempotencyKey)
    putTask(taskKey, task)
    if (!task.sessionId) {
      activeDraftKeyRef.current = taskKey
      setSelection({ viewerId, sessionId: null, newSession: true, draftKey: taskKey })
    }
    const connection: ActiveConnection = {
      id: task.id,
      viewerId,
      taskKey,
      controller: new AbortController(),
      selectOnCreate: task.sessionId === null,
      idempotencyKey,
      runId: null,
      requestMode: mode,
      cancelRequested: false,
      cancelCallStarted: false,
    }

    connectionRef.current = connection
    sendLockRef.current = true
    setConnectionBusy(true)

    const setRunId = (runId: string) => {
      if (!connectionIsCurrent(connection)) return
      connection.runId = runId
      const current = currentConnectionTask(connection)
      if (current?.sessionId) saveStoredRecovery(queryViewerId, current, idempotencyKey, runId, mode)
      void cancelConnectionOnServer(connection)
    }

    void (async () => {
      try {
        const events = mode === 'create'
          ? createResearchStream(task.query, {
              localOnly: task.localOnly,
              idempotencyKey,
              signal: connection.controller.signal,
              onSessionId: (sessionId) => attachSessionId(connection, sessionId),
              onRunId: setRunId,
            })
          : researchChatStream(task.sessionId ?? '', task.query, {
              localOnly: task.localOnly,
              idempotencyKey,
              signal: connection.controller.signal,
              onRunId: setRunId,
            })
        await consumeResearchEvents(connection, events)
      } catch {
        if (connectionIsCurrent(connection)) {
          const current = currentConnectionTask(connection)
          if (current) putTask(connection.taskKey, markResearchTaskInterrupted(current, ERROR_MESSAGE))
        }
      } finally {
        if (connectionRef.current === connection) {
          connectionRef.current = null
          sendLockRef.current = false
          setConnectionBusy(false)
        }
      }
    })()
    return true
  }, [attachSessionId, cancelConnectionOnServer, connectionIsCurrent, consumeResearchEvents, currentConnectionTask, putTask, queryViewerId, viewerId])

  const startSessionRecovery = useCallback(async (sessionId: string, requestedTask?: ResearchTaskSnapshot) => {
    if (viewerId === null || connectionRef.current || sendLockRef.current) return
    const taskKey = taskStorageKey(queryViewerId, sessionId)
    const cached = querySessionMessages(queryClient, queryViewerId, lang, sessionId)
    const existing = requestedTask ?? taskSnapshotsRef.current.get(taskKey) ?? null
    if (!requestedTask && existing?.phase === 'error' && existing.recovery === 'retry') return
    const stored = loadStoredRecovery(queryViewerId, sessionId)
    const taskToRecover = existing?.recovery === 'resume' || existing?.recovery === 'retry'
      ? existing
      : stored ? restoreStoredTask(stored, cached.messages) : null
    const hasRecovery = taskToRecover !== null
    const sourceTask = taskToRecover
      ? { ...taskToRecover, baseMessages: taskToRecover.baseMessages.length ? taskToRecover.baseMessages : cached.messages }
      : createResearchTask(`recovery-${Date.now()}-${++taskSequenceRef.current}`, '', false, cached.messages, sessionId, cached.messageCount)
    const nextTask = resetResearchTaskForReplay(sourceTask, `research-${Date.now()}-${++taskSequenceRef.current}`)
    if (hasRecovery) putTask(taskKey, nextTask)

    const connection: ActiveConnection = {
      id: nextTask.id,
      taskKey,
      viewerId,
      controller: new AbortController(),
      selectOnCreate: false,
      idempotencyKey: stored?.idempotencyKey ?? null,
      runId: stored?.runId ?? null,
      requestMode: stored?.mode ?? null,
      cancelRequested: false,
      cancelCallStarted: false,
    }

    connectionRef.current = connection
    sendLockRef.current = true
    setConnectionBusy(true)
    try {
      // Read-only GET first; only a separately authorized owner POST may
      // dispatch an existing queued run that never reached the provider.
      const onRunId = (runId: string) => {
        if (!connectionIsCurrent(connection)) return
        connection.runId = runId
        const current = currentConnectionTask(connection)
        if (current) saveStoredRecovery(queryViewerId, current, connection.idempotencyKey, runId, connection.requestMode)
        else if (!hasRecovery) putTask(taskKey, nextTask)
        void cancelConnectionOnServer(connection)
      }
      let stream = await openResearchSessionStream(
        sessionId, connection.controller.signal, onRunId, false,
      )
      if (!connectionIsCurrent(connection)) return
      if (stream.kind === 'queued') {
        if (!stream.runId) {
          putTask(taskKey, {
            ...nextTask, phase: 'error', recovery: 'resume',
            notice: '服务器暂时无法确认排队任务身份。请稍后继续接收，不会自动重新发起研究。',
          })
          return
        }
        try {
          await resumeQueuedResearchRun(sessionId, stream.runId)
        } catch (error) {
          if (!connectionIsCurrent(connection)) return
          const status = isRecord(error) && isRecord(error.response) ? error.response.status : null
          const unavailable = status === 409 || status === 404
          putTask(taskKey, {
            ...nextTask, phase: 'error', recovery: unavailable ? 'retry' : 'resume',
            notice: unavailable
              ? '旧任务无法安全恢复。只有明确重新研究才会创建新的模型任务。'
              : '暂时无法恢复排队中的研究；可继续尝试接收，不会自动发起新任务。',
          })
          return
        }
        if (!connectionIsCurrent(connection)) return
        stream = await openResearchSessionStream(
          sessionId, connection.controller.signal, onRunId, true,
        )
        if (!connectionIsCurrent(connection)) return
      }
      if (stream.kind === 'queued') {
        putTask(taskKey, {
          ...nextTask, phase: 'cancelled', recovery: 'resume',
          notice: '任务仍在排队，尚未发起模型请求；可稍后继续接收。',
        })
      } else if (stream.kind === 'session') {
        queryClient.setQueryData(researchKeys.session(queryViewerId, lang, sessionId), stream.session)
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: researchKeys.sessions(queryViewerId, lang) }),
          queryClient.invalidateQueries({ queryKey: researchKeys.results(queryViewerId, lang, sessionId) }),
        ])
        if (!hasRecovery) removeTask(taskKey, nextTask.id)
        if (hasRecovery) {
          if (sessionHasSavedTask(stream.session, nextTask)) {
            clearStoredRecovery(queryViewerId, sessionId)
            removeTask(taskKey, nextTask.id)
          } else {
            putTask(taskKey, {
              ...nextTask,
              phase: 'error',
              recovery: 'retry',
              notice: '服务器没有保存完整回答。原请求可能已到达服务器；重新研究会新建任务，可能重复计算或产生费用。',
            })
          }
        }
      } else {
        if (!hasRecovery) putTask(taskKey, nextTask)
        await consumeResearchEvents(connection, stream.events)
      }
    } catch (error) {
      if (!connectionIsCurrent(connection)) return
      const current = currentConnectionTask(connection)
      if (!current || !hasRecovery) return
      const interrupted = markResearchTaskInterrupted(
        current,
        error instanceof Error && /\b(401|403)\b/.test(error.message)
          ? '请先登录后再使用研究助手 🔐'
          : ERROR_MESSAGE,
      )
      putTask(taskKey, interrupted)
    } finally {
      if (connectionRef.current === connection) {
        connectionRef.current = null
        sendLockRef.current = false
        setConnectionBusy(false)
      }
    }
  }, [cancelConnectionOnServer, connectionIsCurrent, consumeResearchEvents, currentConnectionTask, lang, putTask, queryClient, queryViewerId, removeTask, runStreamTask, viewerId])

  const handleSend = useCallback(async (query: string, { localOnly = false }: { localOnly?: boolean } = {}) => {
    const normalizedQuery = query.trim()
    if (!normalizedQuery || connectionRef.current || sendLockRef.current || viewerId === null) return false
    // Without response headers, a prior create may already have reached Django.
    // Never create a different request key while its fate is unknown.
    if (loadPendingCreate(viewerId) || activeTask?.recovery === 'resume') return false

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
    return runStreamTask(task, sessionId ? 'chat' : 'create')
  }, [activeSessionId, activeTask, lang, queryClient, queryViewerId, runStreamTask, viewerId])

  const handleNewSession = useCallback(() => {
    pauseCurrentConnection('已切换到新会话；原服务端任务可能仍在运行，可从历史会话继续接收。')
    activeSessionIdRef.current = null
    activeDraftKeyRef.current = null
    setSelection({ viewerId, sessionId: null, newSession: true, draftKey: null })
  }, [viewerId, pauseCurrentConnection])

  const handleSelectSession = useCallback((sessionId: string) => {
    if (sessionId === activeSessionId) return
    skipAutoProbeKeyRef.current = null
    pauseCurrentConnection('已切换到其他会话；原服务端任务可能仍在运行，切回后可继续接收。')
    activeSessionIdRef.current = sessionId
    activeDraftKeyRef.current = null
    setSelection({ viewerId, sessionId, newSession: false, draftKey: null })
  }, [activeSessionId, pauseCurrentConnection, viewerId])

  const handleRetry = useCallback(async () => {
    const task = activeTask
    if (!task || (task.phase !== 'error' && task.phase !== 'cancelled') || task.recovery !== 'retry' || viewerId === null) return
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
    if (!task || task.recovery !== 'resume' || viewerId === null) return
    if (!task.sessionId) {
      const pending = loadPendingCreate(viewerId)
      if (!pending || pending.taskId !== task.id) return
      // Reattach with EXACTLY the original idempotency key. No fresh paid key.
      const retry = createResearchTask(task.id, pending.query, pending.localOnly, [], null)
      runStreamTask(retry, 'create', pending.idempotencyKey)
      return
    }
    await startSessionRecovery(task.sessionId, task)
  }, [activeTask, startSessionRecovery, viewerId])

  const handleCancel = useCallback(async () => {
    const connection = connectionRef.current
    if (!connection) return
    connection.cancelRequested = true
    await cancelConnectionOnServer(connection)
  }, [cancelConnectionOnServer])
  const handleDisconnect = useCallback(() => {
    pauseCurrentConnection('已关闭研究面板；原服务端任务可能仍在运行，重新打开后可继续接收。')
  }, [pauseCurrentConnection])


  const handleDeleteSession = useCallback(async (sessionId: string) => {
    try {
      await deleteMutation.mutateAsync(sessionId)
      clearStoredRecovery(queryViewerId, sessionId)
      const storageKey = taskStorageKey(queryViewerId, sessionId)
      removeTask(storageKey)
      if (activeSessionId === sessionId) handleNewSession()
    } catch (error) {
      console.error('Failed to delete research session:', error)
    }
  }, [activeSessionId, deleteMutation, handleNewSession, queryViewerId, removeTask])

  useEffect(() => {
    const selectionKey = viewerId !== null && activeSessionId
      ? taskStorageKey(viewerId, activeSessionId)
      : null
    if (probeSelectionRef.current.key !== selectionKey) {
      probeSelectionRef.current = {
        key: selectionKey,
        generation: probeSelectionRef.current.generation + 1,
      }
    }
    if (!selectionKey || !sessionQuery.data || sessionQuery.data.id !== activeSessionId) return
    if (startedProbeGenerationRef.current === probeSelectionRef.current.generation) return
    startedProbeGenerationRef.current = probeSelectionRef.current.generation
    if (skipAutoProbeKeyRef.current === selectionKey) return
    const selectedTask = taskSnapshotsRef.current.get(selectionKey)
    // A task created by this mounted hook is already connected through its
    // original POST/chat stream. Probe history only after it is interrupted,
    // when the user selects another session, or on a fresh mount.
    if (selectedTask && selectedTask.recovery === 'none') return
    void startSessionRecovery(activeSessionId)
  }, [activeSessionId, sessionQuery.data, startSessionRecovery, taskSnapshots, viewerId])

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
    isBusy: connectionBusy,
    recoveryAction: activeTask?.recovery ?? 'none',
    handleSend,
    handleNewSession,
    handleSelectSession,
    handleDeleteSession,
    handleCancel,
    handleDisconnect,
    handleResume,
    handleRetry,
    loadSessions,
  }
}
