import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ChatGPTSubscriptionSettings from '@/pages/ChatGPTSubscriptionSettings'

const api = vi.hoisted(() => ({
  fetchChatGPTSubscriptionStatus: vi.fn(),
  fetchChatGPTSubscriptionModels: vi.fn(),
  startChatGPTSubscriptionConnect: vi.fn(),
  activateChatGPTSubscriptionConnection: vi.fn(),
  selectChatGPTSubscriptionModel: vi.fn(),
  disconnectChatGPTSubscription: vi.fn(),
}))

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { id: 7, username: 'reader' } }),
}))

vi.mock('@/services/api', () => api)

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const view = render(
    <QueryClientProvider client={client}>
      <ChatGPTSubscriptionSettings />
    </QueryClientProvider>,
  )
  return { ...view, client }
}

beforeEach(() => {
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
  api.startChatGPTSubscriptionConnect.mockResolvedValue('https://auth.example/authorize')
  api.activateChatGPTSubscriptionConnection.mockResolvedValue({})
  api.selectChatGPTSubscriptionModel.mockResolvedValue({ selected_model: 'listed-model-slug' })
  api.disconnectChatGPTSubscription.mockResolvedValue({ disconnected: true, revocation_confirmed: true })
})

afterEach(() => vi.restoreAllMocks())

describe('ChatGPT subscription settings', () => {
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

  it('opens official authorization in a separate window without storing credentials in the browser', async () => {
    const popup = { closed: false, location: { href: '' }, close: vi.fn() }
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
    renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: '连接新账号' }))
    await waitFor(() => expect(api.startChatGPTSubscriptionConnect).toHaveBeenCalledWith(undefined))
    await waitFor(() => expect(popup.location.href).toBe('https://auth.example/authorize'))
  })
})
