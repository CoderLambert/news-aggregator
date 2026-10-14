import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider, useMutation } from '@tanstack/react-query'
import AddChannelDialog from '@/components/workspace/AddChannelDialog'
import { AuthContext } from '@/context/AuthContext'

vi.mock('@/services/channelQueries', () => ({ useChannelMutation: () => useMutation({ mutationFn: (perform: () => Promise<unknown>) => perform() }) }))
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
afterEach(() => { vi.unstubAllGlobals(); document.cookie = 'csrftoken=; Max-Age=0' })

it('shows safe address validation and preserves the URL for correction', async () => {
  document.cookie = 'csrftoken=test-token'
  const fetcher = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(['只接受不含凭据的公开 HTTP(S) 域名地址。']), { status: 400 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ matches: [], supported: false, message: '此地址尚未登记。', url: 'https://example.org/rss' }), { status: 200 }))
  vi.stubGlobal('fetch', fetcher)
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
    <AuthContext.Provider value={{
      user: null, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn(),
    }}>
      <AddChannelDialog topics={[]} onClose={vi.fn()} onDone={vi.fn()} />
    </AuthContext.Provider>
  </QueryClientProvider>)
  const input = screen.getByRole('textbox', { name: '网站或 RSS 地址' })
  fireEvent.change(input, { target: { value: 'http://localhost/rss' } })
  fireEvent.click(screen.getByRole('button', { name: '匹配频道' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('只接受不含凭据的公开 HTTP(S) 域名地址。')
  expect(input).toHaveValue('http://localhost/rss')
  expect(screen.getByRole('button', { name: '确认订阅' })).toBeDisabled()
  fireEvent.change(input, { target: { value: 'https://example.org/rss' } })
  expect(screen.queryByRole('alert')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '匹配频道' }))
  await waitFor(() => expect(screen.getByText('此地址尚未登记。')).toBeInTheDocument())
  expect(fetcher).toHaveBeenCalledTimes(2)
})
