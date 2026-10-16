import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AddChannelDialog from '@/components/workspace/AddChannelDialog'
import { setWorkspaceViewer } from '@/services/workspaceApi'
import { AuthContext } from '@/context/AuthContext'

vi.mock('@/services/channelQueries', () => ({ useChannelConfig: () => ({ groups: { data: [] } }) }))
const originalShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal')
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')
beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute('open', '') } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute('open') } })
})
afterAll(() => {
  if (originalShowModal) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', originalShowModal)
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
  if (originalClose) Object.defineProperty(HTMLDialogElement.prototype, 'close', originalClose)
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'close')
})
afterEach(() => { vi.unstubAllGlobals(); setWorkspaceViewer(null); document.cookie = 'csrftoken=; Max-Age=0' })

it('shows safe address validation and preserves the URL for correction', async () => {
  document.cookie = 'csrftoken=test-token'
  setWorkspaceViewer(12)
  const fetcher = vi.fn().mockImplementation(async (url: string, options: RequestInit) => {
    if (url.includes('/rss/directory/')) return new Response(JSON.stringify({ results: [], next_cursor: null }))
    if (String(options.body).includes('localhost')) return new Response(JSON.stringify({ error: { message: '只接受不含凭据的公开 HTTPS 域名地址。' } }), { status: 400 })
    return new Response(JSON.stringify({ operation_id: 'discovery', state: 'succeeded', candidates: [] }))
  })
  vi.stubGlobal('fetch', fetcher)
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
    <AuthContext.Provider value={{
      user: { id: 12, username: 'reader', isSuperuser: false }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn(),
    }}>
      <AddChannelDialog topics={[]} onClose={vi.fn()} onDone={vi.fn()} />
    </AuthContext.Provider>
  </QueryClientProvider>)
  const input = screen.getByRole('textbox', { name: '搜索订阅源、网站或 RSS 地址' })
  fireEvent.change(input, { target: { value: 'http://localhost/rss' } })
  fireEvent.click(screen.getByRole('button', { name: '查找订阅' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('只接受不含凭据的公开 HTTPS 域名地址。')
  expect(input).toHaveValue('http://localhost/rss')
  expect(screen.getByRole('button', { name: '确认订阅' })).toBeDisabled()
  fireEvent.change(input, { target: { value: 'https://example.org' } })
  expect(screen.queryByRole('alert')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '查找订阅' }))
  await waitFor(() => expect(screen.getByText('未发现网站声明的订阅源。可以粘贴网站公布的 RSS 地址，或明确尝试将此地址作为 Feed 添加。')).toBeInTheDocument())
  expect(fetcher).toHaveBeenCalledTimes(3)
})
