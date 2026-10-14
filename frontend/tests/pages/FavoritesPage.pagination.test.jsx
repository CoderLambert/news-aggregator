import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { AuthContext } from '@/context/AuthContext'
import FavoritesPage from '@/pages/FavoritesPage'
import { fetchBlockedNews, fetchUserFavorites, unblockNews } from '@/services/api'

vi.mock('@/services/api', () => ({ fetchBlockedNews: vi.fn(), fetchUserFavorites: vi.fn(), unblockNews: vi.fn() }))

const saved = Array.from({ length: 41 }, (_, i) => ({
  id: i + 1,
  type: 'bookmark',
  created_at: '2026-10-07T06:00:00Z',
  news: { id: i + 1, title: `Saved story ${i + 1}`, title_zh: '', content: '', content_zh: '',
    url: `https://example.com/story-${i + 1}`, source_name: 'Publisher', category_name: 'News', publish_time: '2026-10-06T09:00:00Z' },
}))

let blocked
function Probe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname + location.search}</output>
}
function mount(initial = '/favorites') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>
    <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false }}>
      <MemoryRouter initialEntries={[initial]}><FavoritesPage /><Probe /></MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  blocked = saved.slice(0, 21).map(item => ({ id: item.id, news: item.news, created_at: item.created_at }))
  fetchUserFavorites.mockImplementation(async ({ page = 1, type } = {}) => {
    const rows = saved.filter(item => !type || item.type === type)
    return { count: rows.length, next: page * 20 < rows.length ? 'next' : null,
      previous: page > 1 ? 'previous' : null, results: rows.slice((page - 1) * 20, page * 20) }
  })
  fetchBlockedNews.mockImplementation(async ({ page = 1 } = {}) => ({
    count: blocked.length,
    next: page * 20 < blocked.length ? 'next' : null,
    previous: page > 1 ? 'previous' : null,
    results: blocked.slice((page - 1) * 20, page * 20),
  }))
  unblockNews.mockImplementation(async newsId => {
    blocked = blocked.filter(row => row.news.id !== newsId)
    return { removed: true }
  })
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation(fn => { fn(0); return 1 })
})

describe('private history pagination', () => {
  it('allows navigation to all 41 bookmarks and preserves filter in the URL', async () => {
    mount('/favorites?filter=bookmark')
    expect(await screen.findByRole('heading', { name: 'Saved story 1' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '第 2 页' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('page=2'))
    expect(await screen.findByRole('heading', { name: 'Saved story 21' })).toBeInTheDocument()
    expect(fetchUserFavorites).toHaveBeenCalledWith({ type: 'bookmark', page: 2 }, expect.any(AbortSignal))
    fireEvent.click(screen.getByRole('button', { name: '第 3 页' }))
    expect(await screen.findByRole('heading', { name: 'Saved story 41' })).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('filter=bookmark&page=3')
  })

  it('restores blocked entries beyond page one and goes back after removing last item', async () => {
    mount('/favorites?view=blocked&page=2')
    expect(await screen.findByRole('heading', { name: 'Saved story 21' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '恢复' }))
    await waitFor(() => expect(unblockNews).toHaveBeenCalledWith(21))
    await waitFor(() => expect(screen.getByTestId('location')).not.toHaveTextContent('page=2'))
    expect(await screen.findByRole('heading', { name: 'Saved story 1' })).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('view=blocked')
  })

  it('switching tabs and filters resets pagination without mixing results', async () => {
    mount('/favorites?page=3')
    expect(await screen.findByRole('heading', { name: 'Saved story 41' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '已屏蔽' }))
    await waitFor(() => expect(screen.getByTestId('location')).not.toHaveTextContent('page=3'))
    expect(await screen.findByRole('heading', { name: 'Saved story 1' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '收藏与点赞' }))
    expect(await screen.findByRole('button', { name: '点赞' })).toBeInTheDocument()
  })
})
