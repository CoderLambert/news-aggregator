import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext } from '@/context/AuthContext'
import FavoritesPage from './FavoritesPage'
import { fetchBlockedNews, fetchUserFavorites, unblockNews } from '@/services/api'
import { privateNewsKeys } from '@/services/userNewsQueries'

vi.mock('@/services/api', () => ({ fetchBlockedNews: vi.fn(), fetchUserFavorites: vi.fn(), unblockNews: vi.fn() }))

let blocked = true

beforeEach(() => {
  vi.clearAllMocks()
  blocked = true
  fetchUserFavorites.mockResolvedValue({ results: [] })
  fetchBlockedNews.mockImplementation(async () => ({ results: blocked ? [{
    id: 5,
    news: { id: 21, title: 'Blocked article', publish_time: '2026-10-06T09:00:00Z' },
    created_at: '2026-10-06T09:00:00Z',
  }] : [] }))
  unblockNews.mockImplementation(async () => { blocked = false; return { removed: true } })
})

describe('FavoritesPage unblock', () => {
  it('removes the restored article from the server-data cache after confirmation', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          <MemoryRouter><FavoritesPage /></MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )

    fireEvent.click(await screen.findByRole('tab', { name: '屏蔽' }))
    expect(await screen.findByRole('heading', { name: 'Blocked article' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '恢复' }))

    await waitFor(() => {
      expect(unblockNews).toHaveBeenCalledWith(21)
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['news', 'list', { viewerId: 12 }] })
    })
    expect(screen.queryByRole('heading', { name: 'Blocked article' })).not.toBeInTheDocument()
  })

  it('shows load and retry feedback instead of the empty state after a failed read', async () => {
    fetchUserFavorites.mockRejectedValueOnce(new Error('network unavailable'))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          <MemoryRouter><FavoritesPage /></MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('收藏内容加载失败。')
    expect(screen.queryByText('还没有收藏内容')).not.toBeInTheDocument()
  })

  it('does not display cached favorite data for a different signed-in viewer', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } } })
    client.setQueryData(privateNewsKeys.favorites(12, 'all'), {
      count: 1,
      next: null,
      previous: null,
      results: [{
        id: 121,
        news: {
          id: 81, title: 'Viewer A private favorite', title_zh: '', content: '', content_zh: '',
          url: 'https://example.com/a', cover_image: '', source_name: 'Example', category_name: 'News',
          publish_time: '2026-10-06T09:00:00Z',
        },
        type: 'like',
        created_at: '2026-10-06T09:00:00Z',
      }],
    })
    fetchUserFavorites.mockResolvedValue({ results: [{
      id: 131,
      news: {
        id: 82, title: 'Viewer B favorite', title_zh: '', content: '', content_zh: '',
        url: 'https://example.com/b', cover_image: '', source_name: 'Example', category_name: 'News',
        publish_time: '2026-10-06T09:00:00Z',
      },
      type: 'bookmark',
      created_at: '2026-10-06T09:00:00Z',
    }] })

    render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={{ user: { id: 13, username: 'reader-b' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          <MemoryRouter><FavoritesPage /></MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )

    expect(screen.queryByRole('link', { name: /Viewer A private favorite/ })).not.toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /Viewer B favorite/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Viewer A private favorite/ })).not.toBeInTheDocument()
  })
})
