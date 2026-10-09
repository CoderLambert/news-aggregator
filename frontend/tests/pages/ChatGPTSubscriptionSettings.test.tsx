import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import ChatGPTSubscriptionSettings from '@/pages/ChatGPTSubscriptionSettings'

const api = vi.hoisted(() => ({
  fetchChatGPTSubscriptionStatus: vi.fn(),
  fetchChatGPTSubscriptionAttempt: vi.fn(),
  cancelChatGPTSubscriptionAttempt: vi.fn(),
  fetchChatGPTSubscriptionModels: vi.fn(),
  startChatGPTSubscriptionConnect: vi.fn(),
  activateChatGPTSubscriptionConnection: vi.fn(),
  selectChatGPTSubscriptionModel: vi.fn(),
  disconnectChatGPTSubscription: vi.fn(),
}))
const authState = vi.hoisted(() => ({ user: { id: 7, username: 'reader' } }))

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: authState.user }),
}))

vi.mock('@/services/api', () => api)

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter><ChatGPTSubscriptionSettings /></MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...view, client }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function createHandoffPopup() {
  const form = { method: '', action: '', append: vi.fn(), submit: vi.fn() }
  const popup = {
    closed: false,
    document: {
      createElement: vi.fn((tag: string) => tag === 'form' ? form : { type: '', name: '', value: '' }),
      body: { replaceChildren: vi.fn() },
    },
    close: vi.fn(),
  }
  return { popup, form }
}

function handoff(attemptId: string) {
  return {
    attempt_id: attemptId,
    handoff_token: `one-use-${attemptId}`,
    handoff_url: 'http://127.0.0.1:9527/api/chatgpt-subscription/handoff/',
  }
}

async function switchSignedInUser(view: ReturnType<typeof renderSettings>, id: number) {
  await act(async () => {
    authState.user = { id, username: `reader-${id}` }
    view.rerender(
      <QueryClientProvider client={view.client}>
        <MemoryRouter><ChatGPTSubscriptionSettings /></MemoryRouter>
      </QueryClientProvider>,
    )
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  authState.user = { id: 7, username: 'reader' }
  api.fetchChatGPTSubscriptionStatus.mockResolvedValue({
    active_connection_id: 'connection-a',
    connections: [{
      id: 'connection-a',
      account_name: 'Reader account',
      account_email: 'reader@example.com',
      selected_model: '',
      active: true,
      connected: true,
      needs_reauth: false,
      updated_at: '2026-10-08T00:00:00Z',
    }],
  })
  api.fetchChatGPTSubscriptionModels.mockResolvedValue({
    selected_model: '',
    models: [{ slug: 'listed-model-slug', display_name: 'Visible Model' }],
  })
  api.startChatGPTSubscriptionConnect.mockResolvedValue({
    attempt_id: 'attempt-1',
    handoff_token: 'one-use-ticket',
    handoff_url: 'http://127.0.0.1:9527/api/chatgpt-subscription/handoff/',
  })
  api.fetchChatGPTSubscriptionAttempt.mockResolvedValue({
    id: 'attempt-1', status: 'authorizing', message: '', connection_id: null,
  })
  api.cancelChatGPTSubscriptionAttempt.mockResolvedValue({
    id: 'attempt-1', status: 'cancelled', message: '授权请求已取消。', connection_id: null,
  })
  api.activateChatGPTSubscriptionConnection.mockResolvedValue({})
  api.selectChatGPTSubscriptionModel.mockResolvedValue({ selected_model: 'listed-model-slug' })
  api.disconnectChatGPTSubscription.mockResolvedValue({ disconnected: true, revocation_confirmed: true })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('ChatGPT subscription settings', () => {
  it('shows connection, account and model, and configuration readiness as one guided flow', async () => {
    renderSettings()
    const flow = await screen.findByRole('list', { name: 'ChatGPT 订阅设置进度' })
    expect(flow.textContent).toContain('1. 连接')
    expect(flow.textContent).toContain('2. 账号与模型')
    expect(flow.textContent).toContain('3. 配置状态')
    await waitFor(() => expect(flow.textContent).toContain('账号已连接'))
    expect(flow.textContent).toContain('请选择可见模型')
  })

  it('loads the account visible model and saves the chosen slug', async () => {
    renderSettings()
    expect(await screen.findByText('Reader account')).toBeTruthy()
    const select = await screen.findByLabelText('可见模型')
    await waitFor(() => expect(screen.getByRole('option', { name: 'Visible Model' })).toBeTruthy())
    fireEvent.change(select, { target: { value: 'listed-model-slug' } })
    await waitFor(() => expect(api.selectChatGPTSubscriptionModel).toHaveBeenCalledWith('connection-a', 'listed-model-slug'))
  })

  it('stores connection state under the authenticated local viewer key', async () => {
    const { client } = renderSettings()
    expect(await screen.findByText('Reader account')).toBeTruthy()
    await waitFor(() => expect(client.getQueryData(['chatgptSubscription', 'status', 7])).toBeTruthy())
    expect(client.getQueryData(['chatgptSubscription', 'status', 'anonymous'])).toBeUndefined()
  })

  it('POSTs the one-use handoff ticket and does not treat unrelated connection updates as success', async () => {
    const inputs: Array<{ name: string; value: string }> = []
    const form = {
      method: '',
      action: '',
      append: vi.fn((input: { name: string; value: string }) => inputs.push(input)),
      submit: vi.fn(),
    }
    const popup = {
      closed: false,
      document: {
        createElement: vi.fn((tag: string) => tag === 'form' ? form : { type: '', name: '', value: '' }),
        body: { replaceChildren: vi.fn() },
      },
      close: vi.fn(),
    }
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    const { client } = renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))

    await waitFor(() => expect(form.submit).toHaveBeenCalledOnce())
    expect(form.method).toBe('POST')
    expect(form.action).toBe('http://127.0.0.1:9527/api/chatgpt-subscription/handoff/')
    expect(inputs).toEqual([
      expect.objectContaining({ name: 'attempt_id', value: 'attempt-1' }),
      expect.objectContaining({ name: 'handoff_token', value: 'one-use-ticket' }),
    ])
    expect(api.startChatGPTSubscriptionConnect).toHaveBeenCalledWith(undefined)

    await waitFor(() => expect(client.getQueryData(['chatgptSubscription', 'attempt', 7, 'attempt-1'])).toMatchObject({
      status: 'authorizing',
    }))
    act(() => client.setQueryData(['chatgptSubscription', 'status', 7], {
      active_connection_id: 'connection-a',
      connections: [{
        id: 'connection-a', account_name: 'Reader account', account_email: 'reader@example.com',
        selected_model: '', active: true, connected: true, needs_reauth: false,
        updated_at: '2026-10-08T00:01:00Z',
      }],
    }))
    expect(screen.queryByText('ChatGPT 订阅账号已连接。')).toBeNull()
    expect(screen.getByRole('button', { name: '等待 OpenAI 授权…' })).toBeTruthy()

    act(() => client.setQueryData(['chatgptSubscription', 'attempt', 7, 'attempt-1'], {
      id: 'attempt-1', status: 'completed', message: '已完成', connection_id: 'connection-b',
    }))
    expect(await screen.findByText('ChatGPT 订阅账号已连接。')).toBeTruthy()
  })

  it('ignores a late successful handoff after switching A to B and back to A', async () => {
    const oldRequest = deferred<ReturnType<typeof handoff>>()
    const oldPopup = createHandoffPopup()
    const currentPopup = createHandoffPopup()
    vi.spyOn(window, 'open')
      .mockReturnValueOnce(oldPopup.popup as unknown as Window)
      .mockReturnValueOnce(currentPopup.popup as unknown as Window)
    api.startChatGPTSubscriptionConnect
      .mockImplementationOnce(() => oldRequest.promise)
      .mockResolvedValueOnce(handoff('attempt-current'))
    api.fetchChatGPTSubscriptionAttempt.mockImplementation((id: string) => Promise.resolve({
      id, status: 'authorizing', message: '', connection_id: null,
    }))

    const view = renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(api.startChatGPTSubscriptionConnect).toHaveBeenCalledTimes(1))

    await switchSignedInUser(view, 8)
    expect(oldPopup.popup.close).toHaveBeenCalledOnce()
    await switchSignedInUser(view, 7)
    fireEvent.click(screen.getByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(currentPopup.form.submit).toHaveBeenCalledOnce())

    await act(async () => {
      oldRequest.resolve(handoff('attempt-stale'))
      await oldRequest.promise
    })

    expect(oldPopup.form.submit).not.toHaveBeenCalled()
    expect(oldPopup.popup.close).toHaveBeenCalledOnce()
    expect(currentPopup.popup.close).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '等待 OpenAI 授权…' })).toBeTruthy()
    expect(api.fetchChatGPTSubscriptionAttempt.mock.calls.some(([id]) => id === 'attempt-current')).toBe(true)
    expect(api.fetchChatGPTSubscriptionAttempt.mock.calls.some(([id]) => id === 'attempt-stale')).toBe(false)
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()
  })

  it('ignores a late failed handoff after switching A to B and back to A', async () => {
    const oldRequest = deferred<ReturnType<typeof handoff>>()
    const oldPopup = createHandoffPopup()
    const currentPopup = createHandoffPopup()
    vi.spyOn(window, 'open')
      .mockReturnValueOnce(oldPopup.popup as unknown as Window)
      .mockReturnValueOnce(currentPopup.popup as unknown as Window)
    api.startChatGPTSubscriptionConnect
      .mockImplementationOnce(() => oldRequest.promise)
      .mockResolvedValueOnce(handoff('attempt-current'))
    api.fetchChatGPTSubscriptionAttempt.mockImplementation((id: string) => Promise.resolve({
      id, status: 'authorizing', message: '', connection_id: null,
    }))

    const view = renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(api.startChatGPTSubscriptionConnect).toHaveBeenCalledTimes(1))

    await switchSignedInUser(view, 8)
    expect(oldPopup.popup.close).toHaveBeenCalledOnce()
    await switchSignedInUser(view, 7)
    fireEvent.click(screen.getByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(currentPopup.form.submit).toHaveBeenCalledOnce())

    await act(async () => {
      oldRequest.reject(new Error('STALE_HANDOFF_FAILURE'))
      await oldRequest.promise.catch(() => undefined)
    })

    expect(oldPopup.form.submit).not.toHaveBeenCalled()
    expect(oldPopup.popup.close).toHaveBeenCalledOnce()
    expect(currentPopup.popup.close).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '等待 OpenAI 授权…' })).toBeTruthy()
    expect(screen.queryByText(/STALE_HANDOFF_FAILURE/)).toBeNull()
    expect(api.fetchChatGPTSubscriptionAttempt.mock.calls.some(([id]) => id === 'attempt-current')).toBe(true)
    expect(api.fetchChatGPTSubscriptionAttempt.mock.calls.some(([id]) => id === 'attempt-1')).toBe(false)
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()
  })

  it('ignores a successful handoff that arrives after unmount', async () => {
    const pendingRequest = deferred<ReturnType<typeof handoff>>()
    const pendingPopup = createHandoffPopup()
    vi.spyOn(window, 'open').mockReturnValueOnce(pendingPopup.popup as unknown as Window)
    api.startChatGPTSubscriptionConnect.mockImplementationOnce(() => pendingRequest.promise)

    const view = renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(api.startChatGPTSubscriptionConnect).toHaveBeenCalledOnce())
    view.unmount()
    expect(pendingPopup.popup.close).toHaveBeenCalledOnce()

    await act(async () => {
      pendingRequest.resolve(handoff('attempt-after-unmount'))
      await pendingRequest.promise
    })

    expect(pendingPopup.form.submit).not.toHaveBeenCalled()
    expect(pendingPopup.popup.close).toHaveBeenCalledOnce()
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()
  })

  it('keeps a successful handoff current after popup-close polling clears its display reference', async () => {
    const pendingRequest = deferred<ReturnType<typeof handoff>>()
    const pendingPopup = createHandoffPopup()
    vi.spyOn(window, 'open').mockReturnValueOnce(pendingPopup.popup as unknown as Window)
    api.startChatGPTSubscriptionConnect.mockImplementationOnce(() => pendingRequest.promise)
    api.fetchChatGPTSubscriptionAttempt.mockImplementation((id: string) => Promise.resolve({
      id, status: 'authorizing', message: '', connection_id: null,
    }))

    renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(api.startChatGPTSubscriptionConnect).toHaveBeenCalledOnce())

    pendingPopup.popup.closed = true
    expect(await screen.findByText(/仍以服务器状态为准/)).toBeTruthy()
    await act(async () => {
      pendingRequest.resolve(handoff('attempt-after-popup-close'))
      await pendingRequest.promise
    })

    await waitFor(() => expect(api.fetchChatGPTSubscriptionAttempt.mock.calls.some(
      ([id]) => id === 'attempt-after-popup-close',
    )).toBe(true))
    expect(screen.getByRole('button', { name: '取消授权' })).toBeTruthy()
    expect(pendingPopup.form.submit).not.toHaveBeenCalled()
    expect(pendingPopup.popup.close).not.toHaveBeenCalled()
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()
  })

  it('handles a failed handoff after popup-close polling clears its display reference', async () => {
    const pendingRequest = deferred<ReturnType<typeof handoff>>()
    const pendingPopup = createHandoffPopup()
    vi.spyOn(window, 'open').mockReturnValueOnce(pendingPopup.popup as unknown as Window)
    api.startChatGPTSubscriptionConnect.mockImplementationOnce(() => pendingRequest.promise)

    renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(api.startChatGPTSubscriptionConnect).toHaveBeenCalledOnce())

    pendingPopup.popup.closed = true
    expect(await screen.findByText(/仍以服务器状态为准/)).toBeTruthy()
    await act(async () => {
      pendingRequest.reject(new Error('HANDOFF_FAILED_AFTER_POPUP_CLOSE'))
      await pendingRequest.promise.catch(() => undefined)
    })

    expect(await screen.findByText('HANDOFF_FAILED_AFTER_POPUP_CLOSE')).toBeTruthy()
    expect(screen.getByRole('button', { name: '连接新账号' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '取消授权' })).toBeNull()
    expect(pendingPopup.form.submit).not.toHaveBeenCalled()
    expect(pendingPopup.popup.close).not.toHaveBeenCalled()
    expect(api.fetchChatGPTSubscriptionAttempt).not.toHaveBeenCalled()
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()
  })

  it('keeps the server attempt alive when the popup reports closed and accepts a later success', async () => {
    const form = { method: '', action: '', append: vi.fn(), submit: vi.fn() }
    const popup = {
      closed: false,
      document: {
        createElement: vi.fn((tag: string) => tag === 'form' ? form : { type: '', name: '', value: '' }),
        body: { replaceChildren: vi.fn() },
      },
      close: vi.fn(),
    }
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    const { client } = renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(form.submit).toHaveBeenCalledOnce())

    popup.closed = true
    expect(await screen.findByText(/仍以服务器状态为准/)).toBeTruthy()
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()

    act(() => client.setQueryData(['chatgptSubscription', 'attempt', 7, 'attempt-1'], {
      id: 'attempt-1', status: 'completed', message: '已完成', connection_id: 'connection-b',
    }))
    expect(await screen.findByText('ChatGPT 订阅账号已连接。')).toBeTruthy()
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()
  })

  it('waits for server expiry after a genuinely closed popup without cancelling it locally', async () => {
    const form = { method: '', action: '', append: vi.fn(), submit: vi.fn() }
    const popup = {
      closed: false,
      document: {
        createElement: vi.fn((tag: string) => tag === 'form' ? form : { type: '', name: '', value: '' }),
        body: { replaceChildren: vi.fn() },
      },
      close: vi.fn(),
    }
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    const { client } = renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(form.submit).toHaveBeenCalledOnce())

    popup.closed = true
    expect(await screen.findByText(/仍以服务器状态为准/)).toBeTruthy()
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()
    act(() => client.setQueryData(['chatgptSubscription', 'attempt', 7, 'attempt-1'], {
      id: 'attempt-1', status: 'failed', message: '登录请求已过期，请重新连接。', connection_id: null,
    }))
    expect(await screen.findByText('登录请求已过期，请重新连接。')).toBeTruthy()
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()
  })

  it('cancels only after the user presses the explicit cancel button', async () => {
    const form = { method: '', action: '', append: vi.fn(), submit: vi.fn() }
    const popup = {
      closed: false,
      document: {
        createElement: vi.fn((tag: string) => tag === 'form' ? form : { type: '', name: '', value: '' }),
        body: { replaceChildren: vi.fn() },
      },
      close: vi.fn(),
    }
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(form.submit).toHaveBeenCalledOnce())
    fireEvent.click(await screen.findByRole('button', { name: '取消授权' }))

    await waitFor(() => expect(api.cancelChatGPTSubscriptionAttempt).toHaveBeenCalledOnce())
    expect(api.cancelChatGPTSubscriptionAttempt.mock.calls[0]?.[0]).toBe('attempt-1')
    expect(await screen.findByText('授权请求已取消。')).toBeTruthy()
  })

  it('pauses failed status polling and lets the user retry it', async () => {
    const form = { method: '', action: '', append: vi.fn(), submit: vi.fn() }
    const popup = {
      closed: false,
      document: {
        createElement: vi.fn((tag: string) => tag === 'form' ? form : { type: '', name: '', value: '' }),
        body: { replaceChildren: vi.fn() },
      },
      close: vi.fn(),
    }
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    const { client } = renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(form.submit).toHaveBeenCalledOnce())
    const queryKey = ['chatgptSubscription', 'attempt', 7, 'attempt-1']
    await waitFor(() => expect(client.getQueryData(queryKey)).toMatchObject({ status: 'authorizing' }))

    api.fetchChatGPTSubscriptionAttempt.mockRejectedValueOnce(new Error('network offline'))
    await act(async () => {
      await client.getQueryCache().find({ queryKey })?.fetch().catch(() => undefined)
    })
    expect(api.fetchChatGPTSubscriptionAttempt).toHaveBeenCalledTimes(2)
    expect(client.getQueryState(queryKey)?.status).toBe('error')
    expect((await screen.findByRole('alert')).textContent).toContain('network offline')
    expect(await screen.findByRole('button', { name: '重试状态检查' })).toBeTruthy()
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()

    const callsAfterFailure = api.fetchChatGPTSubscriptionAttempt.mock.calls.length
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 2_100)) })
    expect(api.fetchChatGPTSubscriptionAttempt).toHaveBeenCalledTimes(callsAfterFailure)

    fireEvent.click(screen.getByRole('button', { name: '重试状态检查' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(api.fetchChatGPTSubscriptionAttempt).toHaveBeenCalledTimes(callsAfterFailure + 1)
  })

  it('stops the local attempt when the signed-in user changes without sending cancellation', async () => {
    const form = { method: '', action: '', append: vi.fn(), submit: vi.fn() }
    const popup = {
      closed: false,
      document: {
        createElement: vi.fn((tag: string) => tag === 'form' ? form : { type: '', name: '', value: '' }),
        body: { replaceChildren: vi.fn() },
      },
      close: vi.fn(),
    }
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    const view = renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(form.submit).toHaveBeenCalledOnce())

    act(() => {
      authState.user = { id: 8, username: 'another-reader' }
      view.rerender(
        <QueryClientProvider client={view.client}>
          <MemoryRouter><ChatGPTSubscriptionSettings /></MemoryRouter>
        </QueryClientProvider>,
      )
    })
    expect(popup.close).toHaveBeenCalled()
    expect(await screen.findByText('本地登录账号已切换，此授权请求已停止。')).toBeTruthy()
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()
  })

  it('closes the popup on unmount without cancelling the server attempt', async () => {
    const form = { method: '', action: '', append: vi.fn(), submit: vi.fn() }
    const popup = {
      closed: false,
      document: {
        createElement: vi.fn((tag: string) => tag === 'form' ? form : { type: '', name: '', value: '' }),
        body: { replaceChildren: vi.fn() },
      },
      close: vi.fn(),
    }
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    const view = renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(form.submit).toHaveBeenCalledOnce())
    view.unmount()
    expect(popup.close).toHaveBeenCalled()
    expect(api.cancelChatGPTSubscriptionAttempt).not.toHaveBeenCalled()
  })
})
