import type {
  ResearchActivePhase,
  ResearchEvent,
  ResearchMessage,
  ResearchToolCall,
} from '@/types/research'

type ToolResultEvent = Extract<ResearchEvent, { type: 'tool_result' }>

export type ResearchRecovery = 'none' | 'resume' | 'retry'

export interface ResearchTaskSnapshot {
  id: string
  sessionId: string | null
  query: string
  localOnly: boolean
  startingMessageCount: number
  baseMessages: ResearchMessage[]
  userMessage: ResearchMessage
  assistant: ResearchMessage & { toolCalls: ResearchToolCall[] }
  phase: ResearchActivePhase
  pendingToolResults: Record<string, ToolResultEvent>
  recovery: ResearchRecovery
  notice: string | null
}

function toolCallFromEvent(event: Extract<ResearchEvent, { type: 'tool_call' }>, result?: ToolResultEvent): ResearchToolCall {
  return {
    callId: event.call_id,
    name: event.name,
    args: event.args,
    summary: result?.summary ?? '',
    status: result ? 'done' : 'running',
    articles: result?.articles ?? [],
    webResults: result?.results ?? [],
    articleTitle: result?.title ?? '',
    articleId: result?.id ?? null,
    articleSource: result?.source ?? '',
    articleUrl: result?.url ?? '',
    contentTruncated: result?.content_truncated ?? false,
    originalLength: result?.original_length ?? 0,
    contentLength: result?.length ?? 0,
  }
}

function applyToolResult(call: ResearchToolCall, event: ToolResultEvent): ResearchToolCall {
  return {
    ...call,
    summary: event.summary,
    status: 'done',
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

export function createResearchTask(
  id: string,
  query: string,
  localOnly: boolean,
  baseMessages: ResearchMessage[],
  sessionId: string | null,
  startingMessageCount = 0,
): ResearchTaskSnapshot {
  return {
    id,
    sessionId,
    query,
    localOnly,
    startingMessageCount,
    baseMessages,
    userMessage: { id: `${id}:user`, role: 'user', content: query },
    assistant: { id: `${id}:assistant`, role: 'assistant', content: '', toolCalls: [] },
    phase: 'thinking',
    pendingToolResults: {},
    recovery: 'none',
    notice: null,
  }
}

/**
 * Apply one protocol event. Tool calls/results are keyed by call_id so a
 * replayed or reordered pair cannot create duplicate timeline rows.
 */
export function applyResearchEvent(task: ResearchTaskSnapshot, event: ResearchEvent): ResearchTaskSnapshot {
  if (task.phase === 'success' || task.phase === 'error') return task

  switch (event.type) {
    case 'session_created':
      return task.sessionId === event.session_id ? task : { ...task, sessionId: event.session_id }
    case 'thinking':
      return task.phase === 'streaming' ? task : { ...task, phase: 'thinking' }
    case 'query_decomposed':
      return task
    case 'tool_call': {
      const prior = task.assistant.toolCalls.find((call) => call.callId === event.call_id)
      const pending = task.pendingToolResults[event.call_id]
      const nextCall = prior
        ? { ...toolCallFromEvent(event, pending), ...prior, name: event.name, args: event.args }
        : toolCallFromEvent(event, pending)
      const toolCalls = prior
        ? task.assistant.toolCalls.map((call) => call.callId === event.call_id ? nextCall : call)
        : [...task.assistant.toolCalls, nextCall]
      const pendingToolResults = { ...task.pendingToolResults }
      delete pendingToolResults[event.call_id]
      return {
        ...task,
        phase: task.phase === 'streaming' ? 'streaming' : 'tool_calling',
        assistant: { ...task.assistant, toolCalls },
        pendingToolResults,
      }
    }
    case 'tool_result': {
      const index = task.assistant.toolCalls.findIndex((call) => call.callId === event.call_id)
      if (index === -1) {
        return {
          ...task,
          pendingToolResults: { ...task.pendingToolResults, [event.call_id]: event },
        }
      }
      return {
        ...task,
        assistant: {
          ...task.assistant,
          toolCalls: task.assistant.toolCalls.map((call) => call.callId === event.call_id
            ? applyToolResult(call, event)
            : call),
        },
      }
    }
    case 'text_delta':
      return event.text
        ? { ...task, phase: 'streaming', assistant: { ...task.assistant, content: task.assistant.content + event.text } }
        : task
    case 'complete':
      return { ...task, phase: 'success', recovery: 'none', notice: null, pendingToolResults: {} }
    case 'error':
      return {
        ...task,
        phase: 'error',
        recovery: 'retry',
        notice: event.message || '研究过程中遇到了问题，请稍后再试。',
      }
  }
}

export function markResearchTaskCancelled(task: ResearchTaskSnapshot, notice: string): ResearchTaskSnapshot {
  return { ...task, phase: 'cancelled', recovery: task.sessionId ? 'resume' : 'retry', notice }
}

export function markResearchTaskInterrupted(task: ResearchTaskSnapshot, notice: string): ResearchTaskSnapshot {
  return { ...task, phase: 'error', recovery: task.sessionId ? 'resume' : 'retry', notice }
}

export function resetResearchTaskForReplay(task: ResearchTaskSnapshot, nextId: string): ResearchTaskSnapshot {
  return createResearchTask(nextId, task.query, task.localOnly, task.baseMessages, task.sessionId, task.startingMessageCount)
}

export function researchTaskMessages(task: ResearchTaskSnapshot): ResearchMessage[] {
  const messages: ResearchMessage[] = [
    ...task.baseMessages,
    ...(task.query ? [task.userMessage] : []),
    { ...task.assistant, toolCalls: [...task.assistant.toolCalls] },
  ]
  if (task.notice) {
    messages.push({ id: `${task.id}:notice`, role: 'assistant', content: task.notice, toolCalls: [] })
  }
  return messages
}
