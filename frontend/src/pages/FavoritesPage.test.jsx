import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext } from '@/context/AuthContext'
import FavoritesPage from './FavoritesPage'
import { fetchBlockedNews, fetchUserFavorites, unblockNews } from '@/services/api'

vi.mock('@/services/api', () => ({
  fetchBlockedNews: vi.fn(),
  fetchUserFavorites: vi.fn(),
  unblockNews: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
  fetchUserFavorites.mockResolvedValue({ results: [] })
  fetchBlockedNews.mockResolvedValue({ results: [{
    id: 5,
    news: { id: 21, title: 'Blocked article' },
    created_at: '2026-10-06T09:00:00Z',
  }] })
  unblockNews.mockResolvedValue({ removed: true })
})

describe('FavoritesPage unblock', () => {
  it('invalidates news lists after restoring a blocked article', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          <MemoryRouter><FavoritesPage /></MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )

    fireEvent.click(await screen.findByRole('button', { name: '屏蔽' }))
    expect(await screen.findByRole('heading', { name: 'Blocked article' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /恢复/ }))

    await waitFor(() => {
      expect(unblockNews).toHaveBeenCalledWith(21)
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['news', 'list'] })
    })
    expect(screen.queryByRole('heading', { name: 'Blocked article' })).not.toBeInTheDocument()
  })
})
