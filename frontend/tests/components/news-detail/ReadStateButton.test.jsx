import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ReadStateButton from '@/components/news-detail/ReadStateButton'
import { AuthContext } from '@/context/AuthContext'
import { CapabilitiesTestProvider, fullCapabilities } from '../../helpers/capabilities'
import * as api from '@/services/api'

vi.mock('@/services/api', () => ({ fetchReadState: vi.fn(), updateReadState: vi.fn() }))
beforeEach(() => {
  vi.resetAllMocks()
  api.fetchReadState.mockResolvedValue({ is_read: false, version: 0 })
  api.updateReadState.mockResolvedValue({ is_read: true, version: 1 })
})
function setup(user = { id: 1 }, capabilities = fullCapabilities()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return { client, ...render(<QueryClientProvider client={client}>
    <CapabilitiesTestProvider client={client} value={capabilities}>
      <AuthContext.Provider value={{ user }}><ReadStateButton newsId={7} /></AuthContext.Provider>
    </CapabilitiesTestProvider>
  </QueryClientProvider>) }
}
it('loads without marking read and persists only an explicit click with viewer/version', async () => {
  setup()
  const button = await screen.findByRole('button', { name: '标为已读' })
  expect(api.updateReadState).not.toHaveBeenCalled()
  fireEvent.click(button)
  expect(await screen.findByRole('button', { name: '已读' })).toHaveAttribute('aria-pressed', 'true')
  expect(api.updateReadState).toHaveBeenCalledWith(7, true, 0, 1)
})
it('keeps state and refreshes after conflict rather than claiming success', async () => {
  api.updateReadState.mockRejectedValueOnce(new Error('stale'))
  setup()
  fireEvent.click(await screen.findByRole('button', { name: '标为已读' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('未能保存')
  await waitFor(() => expect(api.fetchReadState).toHaveBeenCalledTimes(2))
  expect(screen.getByRole('button', { name: '标为已读' })).toHaveAttribute('aria-pressed', 'false')
})
it.each([null, { id: 2 }])('uses only a viewer-specific cache entry', async (user) => {
  const { client } = setup(user)
  if (!user) {
    expect(api.fetchReadState).not.toHaveBeenCalled()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  } else {
    await screen.findByRole('button', { name: '标为已读' })
    expect(client.getQueryData(['private', 'read-state', { viewerId: 2, newsId: 7 }])).toEqual({ is_read: false, version: 0 })
    expect(client.getQueryData(['private', 'read-state', { viewerId: 1, newsId: 7 }])).toBeUndefined()
  }
})
it('does not request personal state in read-only mode', () => {
  setup({ id: 1 }, { ...fullCapabilities(), site_mode: 'read_only' })
  expect(api.fetchReadState).not.toHaveBeenCalled()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})
