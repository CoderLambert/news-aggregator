import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext } from '@/context/AuthContext'

const api = vi.hoisted(() => ({
  listResearchSessions: vi.fn(),
  getResearchSession: vi.fn(),
  getResearchResults: vi.fn(),
  deleteResearchSession: vi.fn(),
  createResearchStream: vi.fn(),
  researchChatStream: vi.fn(),
  openResearchSessionStream: vi.fn(),
  cancelResearchRun: vi.fn(),
}))

vi.mock('@/services/researchApi', () => api)
vi.mock('@gsap/react', () => ({ useGSAP: () => {} }))

import ResearchLauncher from '@/components/research/ResearchLauncher'
import { CapabilitiesTestProvider } from '../../helpers/capabilities'

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

const signedInUser = { id: 7, username: 'tester' }

function renderPanel(route = '/', withDetailLauncher = false, user = signedInUser) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={{
        user,
        loading: false,
        login: vi.fn(),
        register: vi.fn(),
        logout: vi.fn(),
        refresh: vi.fn(),
      }}>
        <CapabilitiesTestProvider client={client}>
          <MemoryRouter initialEntries={[route]}>
            {withDetailLauncher && <button type="button" aria-label="打开 AI 助手小闻" className="fixed bottom-6 right-6 size-16" />}
            <ResearchLauncher />
          </MemoryRouter>
        </CapabilitiesTestProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  api.listResearchSessions.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
  api.getResearchSession.mockImplementation(async () => completedSession())
  api.getResearchResults.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
  api.deleteResearchSession.mockResolvedValue(undefined)
  api.cancelResearchRun.mockResolvedValue({ status: 'running' })
})

describe('ResearchPanel', () => {
  it('keeps the closed launcher at the mobile screen edge', () => {
    renderPanel()
    const launcher = screen.getByRole('button', { name: '打开新闻研究助手' })
    expect(launcher).toHaveClass('right-4', 'size-12', 'sm:right-24', 'sm:size-14')
    expect(api.listResearchSessions).not.toHaveBeenCalled()
  })

  it('places beside the Xiaowen launcher on a news detail route', () => {
    renderPanel('/news/21', true)
    const researchLauncher = screen.getByRole('button', { name: '打开新闻研究助手' })
    const detailLauncher = screen.getByRole('button', { name: '打开 AI 助手小闻' })
    expect(researchLauncher).toHaveClass('bottom-6', 'right-24', 'size-12')
    expect(detailLauncher).toHaveClass('bottom-6', 'right-6', 'size-16')
    expect(api.listResearchSessions).not.toHaveBeenCalled()
  })

  it('unmounts research work and restores launcher focus when the panel closes', async () => {
    let requestSignal
    api.createResearchStream.mockImplementation((_query, { signal }) => {
      requestSignal = signal
      return pausedResearch(signal)
    })
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '打开新闻研究助手' }))
    await screen.findByRole('dialog', { name: '新闻研究助手' })
    fireEvent.click(await screen.findByRole('button', { name: '分析 AI 芯片竞争格局' }))
    await screen.findByRole('button', { name: '取消研究任务' })
    await waitFor(() => expect(Object.keys(sessionStorage).some((key) => key.includes('panel-session'))).toBe(true))

    fireEvent.click(screen.getByRole('button', { name: '关闭' }))

    const launcher = await screen.findByRole('button', { name: '打开新闻研究助手' })
    await waitFor(() => expect(launcher).toHaveFocus())
    expect(requestSignal.aborted).toBe(true)
    expect(screen.queryByRole('dialog', { name: '新闻研究助手' })).not.toBeInTheDocument()
    expect(api.cancelResearchRun).not.toHaveBeenCalled()
  })

  it('closes the session menu on Escape before closing the research panel', async () => {
    api.listResearchSessions.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [{ id: 'panel-session', title: '已完成研究' }],
    })
    api.getResearchSession.mockResolvedValue(completedSession())
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '打开新闻研究助手' }))
    await screen.findByRole('dialog', { name: '新闻研究助手' })

    const trigger = await screen.findByRole('button', { name: '历史会话' })
    fireEvent.click(trigger)
    const menu = await screen.findByRole('menu', { name: '历史会话' })
    fireEvent.keyDown(menu, { key: 'Escape' })

    expect(screen.queryByRole('menu', { name: '历史会话' })).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: '新闻研究助手' })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '新闻研究助手' })).not.toBeInTheDocument())
  })

  it('keeps Tab focus inside the research dialog in both directions', async () => {
    const user = userEvent.setup()
    renderPanel()
    await user.click(screen.getByRole('button', { name: '打开新闻研究助手' }))
    const dialog = await screen.findByRole('dialog', { name: '新闻研究助手' })
    await waitFor(() => expect(dialog).toHaveFocus())
    const tabStops = Array.from(dialog.querySelectorAll(
      'a[href], button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])',
    )).filter((element) => element.getAttribute('aria-hidden') !== 'true')
    const first = tabStops[0]
    const last = tabStops[tabStops.length - 1]

    await user.tab()
    expect(first).toHaveFocus()

    last.focus()
    await user.tab()
    expect(first).toHaveFocus()

    first.focus()
    await user.tab({ shift: true })
    expect(last).toHaveFocus()
  })

  it('returns forward and reverse Tab focus from the portalled session menu to the research dialog', async () => {
    const user = userEvent.setup()
    api.listResearchSessions.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [{ id: 'panel-session', title: '已完成研究' }],
    })
    renderPanel()
    await user.click(screen.getByRole('button', { name: '打开新闻研究助手' }))
    const dialog = await screen.findByRole('dialog', { name: '新闻研究助手' })
    const trigger = await screen.findByRole('button', { name: '历史会话' })
    await user.click(trigger)
    const menuItem = await screen.findByRole('menuitem', { name: '已完成研究' })
    await waitFor(() => expect(menuItem).toHaveFocus())

    await user.tab()

    const firstTabStop = dialog.querySelector('button:not(:disabled)')
    expect(firstTabStop).toHaveFocus()
    await waitFor(() => expect(screen.queryByRole('menu', { name: '历史会话' })).not.toBeInTheDocument())

    await user.click(trigger)
    const reopenedMenuItem = await screen.findByRole('menuitem', { name: '已完成研究' })
    await waitFor(() => expect(reopenedMenuItem).toHaveFocus())
    await user.tab({ shift: true })

    const dialogTabStops = Array.from(dialog.querySelectorAll(
      'a[href], button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])',
    )).filter((element) => element.tabIndex >= 0 && !element.closest('[hidden], [inert], [aria-hidden="true"]'))
    expect(dialogTabStops[dialogTabStops.length - 1]).toHaveFocus()
    await waitFor(() => expect(screen.queryByRole('menu', { name: '历史会话' })).not.toBeInTheDocument())
  })

  it('recovers focus when a busy control is removed and keeps outside focus from escaping the active dialog', async () => {
    const user = userEvent.setup()
    api.createResearchStream.mockImplementation((_query, options) => {
      options.onRunId('run-focus')
      return pausedResearch(options.signal)
    })
    api.openResearchSessionStream.mockResolvedValue({
      kind: 'events',
      events: (async function* replay() {
        yield { type: 'complete' }
      })(),
    })

    renderPanel('/', true)
    await user.click(screen.getByRole('button', { name: '打开新闻研究助手' }))
    const dialog = await screen.findByRole('dialog', { name: '新闻研究助手' })
    await user.click(screen.getByRole('button', { name: '分析 AI 芯片竞争格局' }))

    const stopButton = await screen.findByRole('button', { name: '取消研究任务' })
    stopButton.focus()
    expect(stopButton).toHaveFocus()
    await user.click(stopButton)
    const resumeButton = await screen.findByRole('button', { name: '继续接收' })
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))
    expect(document.activeElement).not.toBe(document.body)

    const outsideButton = screen.getByRole('button', { name: '打开 AI 助手小闻' })
    outsideButton.focus()
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))

    document.body.tabIndex = -1
    document.body.focus()
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))
    document.body.removeAttribute('tabindex')

    resumeButton.focus()
    expect(resumeButton).toHaveFocus()
    await user.click(resumeButton)
    await waitFor(() => expect(screen.queryByRole('button', { name: '继续接收' })).not.toBeInTheDocument())
    expect(dialog.contains(document.activeElement)).toBe(true)
  })

  it('skips hidden, inert, and disabled controls when recovering lost focus', async () => {
    const user = userEvent.setup()
    renderPanel()
    await user.click(screen.getByRole('button', { name: '打开新闻研究助手' }))
    await screen.findByRole('button', { name: '最近 LLM Agent 有什么新进展？' })

    const newSessionButton = screen.getByRole('button', { name: '新建研究' })
    const fullscreenButton = screen.getByRole('button', { name: '全屏' })
    const closeButton = screen.getByRole('button', { name: '关闭' })
    newSessionButton.hidden = true
    fullscreenButton.setAttribute('inert', '')
    closeButton.disabled = true
    closeButton.tabIndex = 0

    document.body.tabIndex = -1
    document.body.focus()
    await waitFor(() => expect(screen.getByRole('button', { name: '最近 LLM Agent 有什么新进展？' })).toHaveFocus())
    document.body.removeAttribute('tabindex')
  })

  it('yields focus control to AuthModal and restores focus to Research after Escape', async () => {
    const user = userEvent.setup()
    renderPanel('/', false, null)
    await user.click(screen.getByRole('button', { name: '打开新闻研究助手' }))
    const loginButton = await screen.findByRole('button', { name: '登录 / 注册' })
    const researchDialog = loginButton.closest('[role="dialog"]')
    expect(researchDialog).toHaveAccessibleName('新闻研究助手')

    await user.click(loginButton)
    const authDialog = await screen.findByRole('dialog', { name: '登录小闻' })
    await waitFor(() => expect(screen.getByLabelText('用户名')).toHaveFocus())
    await user.tab()
    expect(authDialog.contains(document.activeElement)).toBe(true)
    expect(researchDialog.contains(document.activeElement)).toBe(false)

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: '登录小闻' })).not.toBeInTheDocument()
    expect(researchDialog).toBeInTheDocument()
    await waitFor(() => expect(loginButton).toHaveFocus())
  })

  it('warns about an uncertain pre-header request and resumes only with the same idempotency key', async () => {
    const user = userEvent.setup()
    api.createResearchStream.mockImplementationOnce((_query, { signal }) => (async function* firstAttempt() {
      yield { type: 'thinking' }
      await waitForAbort(signal)
      throw new DOMException('The operation was aborted', 'AbortError')
    })()).mockImplementationOnce(async function* retryAttempt() {
      yield { type: 'complete' }
    })

    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '打开新闻研究助手' }))
    await screen.findByRole('dialog', { name: '新闻研究助手' })
    fireEvent.click(screen.getByRole('button', { name: '分析 AI 芯片竞争格局' }))
    await screen.findByRole('button', { name: '取消研究任务' })
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))

    expect(await screen.findByRole('status')).toHaveTextContent('原请求可能已到达服务器')
    expect(screen.getByRole('status')).toHaveTextContent('复用原请求标识')
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
    const resumeButton = screen.getByRole('button', { name: '继续接收' })
    resumeButton.focus()
    expect(resumeButton).toHaveFocus()
    await user.click(resumeButton)
    await waitFor(() => expect(api.createResearchStream).toHaveBeenCalledTimes(2))
    const firstKey = api.createResearchStream.mock.calls[0][1].idempotencyKey
    const resumedKey = api.createResearchStream.mock.calls[1][1].idempotencyKey
    expect(firstKey).toMatch(/^[0-9a-f-]{36}$/)
    expect(resumedKey).toBe(firstKey)
    const dialog = screen.getByRole('dialog', { name: '新闻研究助手' })
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))
  })

  it('keeps the risk warning visible when closing before a session id exists', async () => {
    api.createResearchStream.mockImplementation((_query, { signal }) => (async function* pendingHeader() {
      yield { type: 'thinking' }
      await waitForAbort(signal)
      throw new DOMException('The operation was aborted', 'AbortError')
    })())
    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '打开新闻研究助手' }))
    fireEvent.click(await screen.findByRole('button', { name: '分析 AI 芯片竞争格局' }))
    await screen.findByRole('button', { name: '取消研究任务' })

    fireEvent.click(screen.getByRole('button', { name: '关闭' }))

    expect(await screen.findByRole('status')).toHaveTextContent('原请求可能已到达服务器')
    expect(screen.getByRole('dialog', { name: '新闻研究助手' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    expect(await screen.findByRole('button', { name: '打开新闻研究助手' })).toHaveFocus()
  })

  it('shows streaming cancellation and reconnect controls, then displays the persisted result', async () => {
    let requestSignal
    api.createResearchStream.mockImplementation((_query, options) => {
      requestSignal = options.signal
      options.onRunId('run-streaming')
      return pausedResearch(options.signal)
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

    const cancelButton = await screen.findByRole('button', { name: '取消研究任务' })
    expect(requestSignal.aborted).toBe(false)
    fireEvent.click(cancelButton)
    await waitFor(() => expect(api.cancelResearchRun).toHaveBeenCalledWith('panel-session', 'run-streaming'))

    const resumeButton = await screen.findByRole('button', { name: '继续接收' })
    expect(requestSignal.aborted).toBe(true)
    fireEvent.click(resumeButton)

    expect(await screen.findByText('这是保存后的完整结果。')).toBeInTheDocument()
    await waitFor(() => expect(api.openResearchSessionStream).toHaveBeenCalledTimes(1))
    expect(api.createResearchStream).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: '继续接收' })).not.toBeInTheDocument()
  })

  it('keeps typed input while history recovery is pending, then clears only after an accepted send', async () => {
    let resolveProbe
    const history = {
      id: 'history-pending',
      title: '进行中的历史会话',
      messages: [],
      message_count: 0,
      created_at: '2026-10-07T00:00:00Z',
      updated_at: '2026-10-07T00:00:00Z',
    }
    api.listResearchSessions.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [{ id: history.id, title: history.title }],
    })
    api.getResearchSession.mockResolvedValue(history)
    api.openResearchSessionStream.mockImplementationOnce(() => new Promise((resolve) => {
      resolveProbe = resolve
    }))
    api.researchChatStream.mockImplementation(async function* chat() {
      yield { type: 'text_delta', text: '问题已接受' }
      yield { type: 'complete' }
    })

    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: '打开新闻研究助手' }))
    await screen.findByRole('dialog', { name: '新闻研究助手' })
    await waitFor(() => expect(api.openResearchSessionStream).toHaveBeenCalledWith(
      history.id, expect.any(AbortSignal), expect.any(Function), true,
    ))

    const input = screen.getByRole('textbox', { name: '输入研究问题' })
    fireEvent.change(input, { target: { value: '探测期间保留草稿' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false })
    expect(input).toHaveValue('探测期间保留草稿')
    expect(screen.getByRole('button', { name: '取消研究任务' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '最近 LLM Agent 有什么新进展？' })).toBeDisabled()
    expect(api.createResearchStream).not.toHaveBeenCalled()
    expect(api.researchChatStream).not.toHaveBeenCalled()

    await act(async () => {
      resolveProbe({ kind: 'session', session: history })
    })
    const sendButton = await screen.findByRole('button', { name: '发送' })
    await waitFor(() => expect(sendButton).toBeEnabled())
    fireEvent.click(sendButton)

    await waitFor(() => expect(api.researchChatStream).toHaveBeenCalledWith(
      history.id,
      '探测期间保留草稿',
      expect.objectContaining({ signal: expect.any(AbortSignal), localOnly: false }),
    ))
    await waitFor(() => expect(input).toHaveValue(''))
    expect(api.createResearchStream).not.toHaveBeenCalled()
  })
})
