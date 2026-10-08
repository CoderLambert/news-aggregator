import { describe, expect, it } from 'vitest'
import { applyResearchEvent, createResearchTask, researchTaskMessages } from '@/hooks/researchTask'
import { parseResearchEvent } from '@/types/research'

function createTask() {
  return createResearchTask('task-1', '研究 React', false, [], null)
}

describe('research task event reducer', () => {
  it('validates the SSE boundary and ignores unknown or malformed event payloads', () => {
    expect(parseResearchEvent({ type: 'tool_call', call_id: 7, name: 'search_news' })).toBeNull()
    expect(parseResearchEvent({ type: 'future_event', value: true })).toBeNull()
    expect(parseResearchEvent({ type: 'text_delta', text: '回答' })).toEqual({ type: 'text_delta', text: '回答' })
  })

  it('folds duplicated and out-of-order tool events into one completed timeline item', () => {
    const result = parseResearchEvent({
      type: 'tool_result',
      call_id: 'call-1',
      summary: '找到 2 篇相关文章',
      articles: [{ id: 1, title: '第一篇' }],
    })
    const call = parseResearchEvent({
      type: 'tool_call',
      call_id: 'call-1',
      name: 'search_news',
      args: { query: 'React' },
    })
    expect(result?.type).toBe('tool_result')
    expect(call?.type).toBe('tool_call')
    if (result?.type !== 'tool_result' || call?.type !== 'tool_call') return

    let task = applyResearchEvent(createTask(), result)
    task = applyResearchEvent(task, call)
    task = applyResearchEvent(task, call)
    task = applyResearchEvent(task, result)

    expect(task.assistant.toolCalls).toHaveLength(1)
    expect(task.assistant.toolCalls[0]).toMatchObject({
      callId: 'call-1',
      status: 'done',
      summary: '找到 2 篇相关文章',
      articles: [{ id: 1, title: '第一篇' }],
    })
  })

  it('marks success only on complete and ignores late events after the terminal event', () => {
    const sessionCreated = parseResearchEvent({ type: 'session_created', session_id: 'session-1' })
    const text = parseResearchEvent({ type: 'text_delta', text: '完整回答' })
    const complete = parseResearchEvent({ type: 'complete' })
    expect(sessionCreated?.type).toBe('session_created')
    expect(text?.type).toBe('text_delta')
    expect(complete?.type).toBe('complete')
    if (!sessionCreated || !text || !complete) return

    let task = applyResearchEvent(createTask(), sessionCreated)
    task = applyResearchEvent(task, text)
    expect(task.phase).toBe('streaming')
    task = applyResearchEvent(task, complete)
    expect(task.phase).toBe('success')
    task = applyResearchEvent(task, text)
    task = applyResearchEvent(task, complete)

    expect(task.phase).toBe('success')
    expect(researchTaskMessages(task).filter((message) => message.role === 'assistant')).toHaveLength(1)
    expect(researchTaskMessages(task).at(-1)?.content).toBe('完整回答')
  })
})
