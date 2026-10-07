import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthContext } from '@/context/AuthContext'

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

import ResearchPanel from './ResearchPanel'

function waitForAbort(signal) {
  return new Promise((resolve) => signal.addEventListener('abort', resolve, { once: true }))
}

async function* pausedResearch(signal) {
  yield { type: 'session_created', session_id: 'panel-session' }
  yield { type: 'thinking' }
  await waitForAbort(signal)
  throw new DOMException('The operation was aborted', 'AbortError')
}

function completedSession() {
  return {
    id: 'panel-session',
    title: '已完成研究',
    messages: [
      { role: 'user', content: '分析 AI 芯片竞争格局' },
      { role: 'assistant', content: '这是保存后的完整结果。' },
    ],
    message_count: 2,
    created_at: '2026-10-07T00:00:00Z',
    updated_at: '2026-10-07T00:00:00Z',
  }
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={{
        user: { id: 7, username: 'tester' },
        loading: false,
        login: vi.fn(),
        register: vi.fn(),
        logout: vi.fn(),
        refresh: vi.fn(),
      }}>
        <ResearchPanel />
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listResearchSessions.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
  api.getResearchSession.mockImplementation(async () => completedSession())
  api.getResearchResults.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
  api.deleteResearchSession.mockResolvedValue(undefined)
})

describe('ResearchPanel', () => {
  it('shows streaming cancellation and reconnect controls, then displays the persisted result', async () => {
    let requestSignal
    api.createResearchStream.mockImplementation((_query, { signal }) => {
      requestSignal = signal
      return pausedResearch(signal)
    })
    api.openResearchSessionStream.mockResolvedValue({
      kind: 'events',
      events: (async function* replay() {
        yield { type: 'text_delta', text: '这是保存后的完整结果。' }
        yield { type: 'complete' }
      })(),
    })

    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '打开新闻研究助手' }))
    expect(await screen.findByRole('dialog', { name: '新闻研究助手' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '分析 AI 芯片竞争格局' }))

    const cancelButton = await screen.findByRole('button', { name: '取消当前研究' })
    expect(requestSignal.aborted).toBe(false)
    fireEvent.click(cancelButton)

    const resumeButton = await screen.findByRole('button', { name: '继续接收' })
    expect(requestSignal.aborted).toBe(true)
    fireEvent.click(resumeButton)

    expect(await screen.findByText('这是保存后的完整结果。')).toBeInTheDocument()
    await waitFor(() => expect(api.openResearchSessionStream).toHaveBeenCalledTimes(1))
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: '继续接收' })).not.toBeInTheDocument()
  })
})
