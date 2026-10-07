import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const api = vi.hoisted(() => ({
  listResearchSessions: vi.fn(),
  getResearchSession: vi.fn(),
  getResearchResults: vi.fn(),
  deleteResearchSession: vi.fn(),
  createResearchStream: vi.fn(),
  researchChatStream: vi.fn(),
  openResearchSessionStream: vi.fn(),
}))

vi.mock('@/services/researchApi', () => api)

import { useResearch } from './useResearch'

function emptyPage(results = []) {
  return { count: results.length, next: null, previous: null, results }
}

function session(id, messages = [], messageCount = messages.length) {
  return {
    id,
    title: `Session ${id}`,
    messages,
    message_count: messageCount,
    created_at: '2026-10-07T00:00:00Z',
    updated_at: '2026-10-07T00:00:00Z',
  }
}

function renderResearchHook() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } },
  })
  const wrapper = ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const hook = renderHook(() => useResearch(1), { wrapper })
  return { ...hook, client }
}

function waitForAbort(signal) {
  return new Promise((resolve) => signal.addEventListener('abort', resolve, { once: true }))
}

async function* hangingStream(signal) {
  yield { type: 'session_created', session_id: 'session-active' }
  yield { type: 'thinking' }
  await waitForAbort(signal)
  throw new DOMException('The operation was aborted', 'AbortError')
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listResearchSessions.mockResolvedValue(emptyPage())
  api.getResearchSession.mockImplementation(async (id) => session(id))
  api.getResearchResults.mockResolvedValue(emptyPage())
  api.deleteResearchSession.mockResolvedValue(undefined)
})

describe('useResearch stream lifecycle', () => {
  it('prevents duplicate sends, cancels the browser stream, and leaves the task resumable', async () => {
    let requestSignal
    api.createResearchStream.mockImplementation((_query, { signal }) => {
      requestSignal = signal
      return hangingStream(signal)
    })
    const { result } = renderResearchHook()

    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    act(() => { void result.current.handleSend('  研究 React  ') })
    await waitFor(() => expect(result.current.activeSessionId).toBe('session-active'))
    await waitFor(() => expect(result.current.phase).toBe('thinking'))

    act(() => { void result.current.handleSend('不要重复启动') })
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
    expect(api.createResearchStream).toHaveBeenCalledWith('研究 React', expect.objectContaining({ localOnly: false, signal: expect.any(AbortSignal) }))

    act(() => result.current.handleCancel())
    await waitFor(() => expect(result.current.phase).toBe('cancelled'))
    expect(requestSignal.aborted).toBe(true)
    expect(result.current.recoveryAction).toBe('resume')
    expect(result.current.messages.at(-1).content).toMatch(/服务器任务可能仍在运行/)
  })

  it('replays an interrupted task once, applies duplicate events idempotently, and reloads its saved result', async () => {
    let requestSignal
    api.createResearchStream.mockImplementation((_query, { signal }) => {
      requestSignal = signal
      return hangingStream(signal)
    })

    let persisted = session('session-active')
    api.getResearchSession.mockImplementation(async () => persisted)
    api.openResearchSessionStream.mockResolvedValue({
      kind: 'events',
      events: (async function* replay() {
        yield { type: 'tool_result', call_id: 'search-1', summary: '找到 1 篇相关文章', articles: [{ id: 42, title: '研究文章' }] }
        yield { type: 'tool_call', call_id: 'search-1', name: 'search_news', args: { query: 'React' } }
        yield { type: 'tool_call', call_id: 'search-1', name: 'search_news', args: { query: 'React' } }
        yield { type: 'text_delta', text: '研究完成。' }
        yield { type: 'complete' }
        yield { type: 'text_delta', text: '迟到事件' }
      })(),
    })

    const { result, client } = renderResearchHook()
    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    act(() => { void result.current.handleSend('研究 React') })
    await waitFor(() => expect(result.current.phase).toBe('thinking'))
    act(() => result.current.handleCancel())
    await waitFor(() => expect(result.current.phase).toBe('cancelled'))

    persisted = session('session-active', [
      { role: 'user', content: '研究 React' },
      { role: 'assistant', content: '研究完成。' },
    ], 2)
    await act(async () => { await result.current.handleResume() })
    await waitFor(() => expect(result.current.messages.map((message) => message.content)).toContain('研究完成。'))

    expect(api.openResearchSessionStream).toHaveBeenCalledTimes(1)
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
    expect(requestSignal.aborted).toBe(true)
    expect(result.current.messages.filter((message) => message.content === '研究完成。')).toHaveLength(1)
    expect(result.current.messages.some((message) => message.content === '迟到事件')).toBe(false)
    expect(result.current.phase).toBe('idle')
    expect(client.getQueryData(['private', 'research', 'session', { viewerId: 1, lang: 'zh', sessionId: 'session-active' }]).messages).toHaveLength(2)
  })

  it('treats stream EOF without complete as interrupted instead of success', async () => {
    api.createResearchStream.mockImplementation(async function* () {
      yield { type: 'session_created', session_id: 'session-incomplete' }
      yield { type: 'text_delta', text: '部分回答' }
    })
    const { result } = renderResearchHook()

    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    await act(async () => { await result.current.handleSend('研究尚未完成') })

    expect(result.current.phase).toBe('error')
    expect(result.current.phase).not.toBe('success')
    expect(result.current.recoveryAction).toBe('resume')
    expect(result.current.messages.some((message) => message.content.includes('没有收到研究完成事件'))).toBe(true)
  })

  it('keeps late session reads scoped to their query key after switching sessions', async () => {
    let resolveLatest
    const latestDetail = new Promise((resolve) => { resolveLatest = resolve })
    api.listResearchSessions.mockResolvedValue(emptyPage([
      { id: 'latest', title: '最新研究' },
      { id: 'older', title: '旧研究' },
    ]))
    api.getResearchSession.mockImplementation((id) => id === 'latest'
      ? latestDetail
      : Promise.resolve(session('older', [{ role: 'user', content: '旧会话内容' }], 1)))
    const { result } = renderResearchHook()

    await waitFor(() => expect(api.getResearchSession).toHaveBeenCalledWith('latest', expect.any(AbortSignal)))
    act(() => result.current.handleSelectSession('older'))
    await waitFor(() => expect(result.current.messages[0]?.content).toBe('旧会话内容'))
    resolveLatest(session('latest', [{ role: 'user', content: '晚到的内容' }], 1))
    await waitFor(() => expect(result.current.activeSessionId).toBe('older'))

    expect(result.current.messages[0]?.content).toBe('旧会话内容')
  })

  it('only starts a retry after an explicit user action following an error event', async () => {
    api.createResearchStream.mockImplementation(async function* () {
      yield { type: 'session_created', session_id: 'session-error' }
      yield { type: 'error', message: '提供商暂不可用' }
    })
    api.researchChatStream.mockImplementation(async function* () {
      yield { type: 'text_delta', text: '恢复成功' }
      yield { type: 'complete' }
    })
    const { result } = renderResearchHook()

    await waitFor(() => expect(result.current.loadingSessions).toBe(false))
    await act(async () => { await result.current.handleSend('研究失败后重试') })
    expect(result.current.phase).toBe('error')
    expect(result.current.recoveryAction).toBe('retry')
    expect(api.researchChatStream).not.toHaveBeenCalled()

    await act(async () => { await result.current.handleRetry() })
    expect(api.researchChatStream).toHaveBeenCalledTimes(1)
  })
})
