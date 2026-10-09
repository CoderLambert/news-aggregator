import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { AuthContext } from '@/context/AuthContext'
import FavoritesPage from '@/pages/FavoritesPage'
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
  it('restores the selected section and favorite filter from browser history', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    function HistoryHarness() {
      const location = useLocation()
      const navigate = useNavigate()
      return <><FavoritesPage /><output data-testid="location">{location.pathname}{location.search}</output><button type="button" onClick={() => navigate(-1)}>后退</button></>
    }
    render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          <MemoryRouter initialEntries={['/favorites?view=blocked&filter=bookmark']}><HistoryHarness /></MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('tab', { name: '已屏蔽' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('tab', { name: '收藏与点赞' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/favorites?filter=bookmark')
    fireEvent.click(screen.getByRole('button', { name: '点赞' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/favorites?filter=like')
    fireEvent.click(screen.getByRole('button', { name: '后退' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '收藏' })).toHaveAttribute('aria-pressed', 'true'))
    fireEvent.click(screen.getByRole('button', { name: '后退' }))
    await waitFor(() => expect(screen.getByRole('tab', { name: '已屏蔽' })).toHaveAttribute('aria-selected', 'true'))
  })

  it('implements roving focus and Home/End keyboard navigation for linked tabs and panels', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          <MemoryRouter><FavoritesPage /></MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )

    const favoritesTab = await screen.findByRole('tab', { name: '收藏与点赞' })
    const blockedTab = screen.getByRole('tab', { name: '已屏蔽' })
    expect(favoritesTab).toHaveAttribute('aria-controls', 'favorites-panel')
    expect(blockedTab).toHaveAttribute('aria-controls', 'blocked-panel')
    expect(document.getElementById('favorites-panel')).toHaveAttribute('aria-labelledby', 'favorites-tab')
    expect(document.getElementById('blocked-panel')).toHaveAttribute('aria-labelledby', 'blocked-tab')
    expect(favoritesTab).toHaveAttribute('tabindex', '0')
    expect(blockedTab).toHaveAttribute('tabindex', '-1')
    expect(screen.getByRole('group', { name: '收藏筛选' })).toBeInTheDocument()

    favoritesTab.focus()
    fireEvent.keyDown(favoritesTab, { key: 'ArrowRight' })
    expect(blockedTab).toHaveFocus()
    expect(blockedTab).toHaveAttribute('aria-selected', 'true')
    expect(blockedTab).toHaveAttribute('tabindex', '0')

    fireEvent.keyDown(blockedTab, { key: 'Home' })
    expect(favoritesTab).toHaveFocus()
    expect(favoritesTab).toHaveAttribute('aria-selected', 'true')

    fireEvent.keyDown(favoritesTab, { key: 'End' })
    expect(blockedTab).toHaveFocus()
    fireEvent.keyDown(blockedTab, { key: 'ArrowLeft' })
    expect(favoritesTab).toHaveFocus()
  })

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

    fireEvent.click(await screen.findByRole('tab', { name: '已屏蔽' }))
    expect(await screen.findByRole('heading', { name: 'Blocked article' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '恢复' }))

    await waitFor(() => {
      expect(unblockNews).toHaveBeenCalledWith(21)
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['news', 'list', { viewerId: 12 }] })
    })
    expect(screen.queryByRole('heading', { name: 'Blocked article' })).not.toBeInTheDocument()
  })

  it('serializes restore clicks while the shared unblock mutation is pending', async () => {
    let resolveUnblock
    unblockNews.mockReturnValue(new Promise((resolve) => { resolveUnblock = resolve }))
    fetchBlockedNews.mockResolvedValue({ results: [
      { id: 5, news: { id: 21, title: 'First blocked article', publish_time: '2026-10-06T09:00:00Z' }, created_at: '2026-10-06T09:00:00Z' },
      { id: 6, news: { id: 22, title: 'Second blocked article', publish_time: '2026-10-06T09:00:00Z' }, created_at: '2026-10-06T09:00:00Z' },
    ] })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          <MemoryRouter><FavoritesPage /></MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )

    fireEvent.click(await screen.findByRole('tab', { name: '已屏蔽' }))
    expect(await screen.findByRole('heading', { name: 'First blocked article' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Second blocked article' })).toBeInTheDocument()
    const restoreButtons = screen.getAllByRole('button', { name: '恢复' })
    expect(restoreButtons).toHaveLength(2)

    fireEvent.click(restoreButtons[0])
    await waitFor(() => expect(unblockNews).toHaveBeenCalledWith(21))
    expect(screen.getAllByRole('button', { name: '恢复中…' })).toHaveLength(2)
    expect(restoreButtons[0]).toBeDisabled()
    expect(restoreButtons[1]).toBeDisabled()

    fireEvent.click(restoreButtons[1])
    expect(unblockNews).toHaveBeenCalledTimes(1)

    await act(async () => { resolveUnblock({ removed: true }) })
  })

  it('moves focus to the next restore action after a blocked item is removed', async () => {
    let blockedEntries = [
      { id: 5, news: { id: 21, title: 'First blocked article', publish_time: '2026-10-06T09:00:00Z' }, created_at: '2026-10-06T09:00:00Z' },
      { id: 6, news: { id: 22, title: 'Second blocked article', publish_time: '2026-10-06T09:00:00Z' }, created_at: '2026-10-06T09:00:00Z' },
    ]
    fetchBlockedNews.mockImplementation(async () => ({ results: blockedEntries }))
    unblockNews.mockImplementation(async (newsId) => { blockedEntries = blockedEntries.filter((entry) => entry.news.id !== newsId); return { removed: true } })
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => { callback(0); return 1 })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          <MemoryRouter initialEntries={['/favorites?view=blocked']}><FavoritesPage /></MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    )

    const restoreButtons = await screen.findAllByRole('button', { name: '恢复' })
    fireEvent.click(restoreButtons[0])
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'First blocked article' })).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: '恢复' })).toHaveFocus()
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
