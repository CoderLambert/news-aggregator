import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FavoriteButtons from '@/components/news-detail/FavoriteButtons'
import * as api from '@/services/api'
import { AuthContext } from '@/context/AuthContext'

vi.mock('@/services/api', () => ({
  toggleFavorite: vi.fn(),
  checkFavoriteStatus: vi.fn(),
  blockNews: vi.fn(),
  unblockNews: vi.fn(),
  checkBlockedStatus: vi.fn(),
}))

let isBlocked
let favoriteStatus

function renderWithAuth(ui, user = null, client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={{ user, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
          {ui}
        </AuthContext.Provider>
      </QueryClientProvider>,
    ),
  }
}

describe('FavoriteButtons', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    isBlocked = false
    favoriteStatus = { is_liked: false, is_bookmarked: false, like_count: 5, bookmark_count: 3 }
    api.checkFavoriteStatus.mockImplementation(async () => favoriteStatus)
    api.checkBlockedStatus.mockImplementation(async () => ({ is_blocked: isBlocked }))
    api.toggleFavorite.mockImplementation(async (_id, type) => {
      const key = type === 'like' ? 'is_liked' : 'is_bookmarked'
      const count = type === 'like' ? 'like_count' : 'bookmark_count'
      const created = !favoriteStatus[key]
      favoriteStatus = { ...favoriteStatus, [key]: created, [count]: Math.max(0, favoriteStatus[count] + (created ? 1 : -1)) }
      return created ? { created: true } : { removed: true }
    })
    api.blockNews.mockImplementation(async () => { isBlocked = true; return { created: true } })
    api.unblockNews.mockImplementation(async () => { isBlocked = false; return { removed: true } })
  })

  it('shows loading state until both viewer-scoped status requests finish', () => {
    api.checkFavoriteStatus.mockReturnValueOnce(new Promise(() => {}))
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })
    expect(document.querySelectorAll('.animate-pulse').length).toBe(3)
  })

  it('renders the like, bookmark, and block controls after loading', async () => {
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })
    expect(await screen.findByLabelText('点赞')).toBeInTheDocument()
    expect(screen.getByLabelText('收藏')).toBeInTheDocument()
    expect(screen.getByLabelText('屏蔽此新闻')).toBeInTheDocument()
    expect(api.checkFavoriteStatus).toHaveBeenCalledWith(1, expect.any(AbortSignal))
    expect(api.checkBlockedStatus).toHaveBeenCalledWith(1, expect.any(AbortSignal))
  })

  it('shows confirmed counts from the favorite-status response', async () => {
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })
    await screen.findByLabelText('点赞')
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('toggles a favorite through the mutation and reflects the confirmed result', async () => {
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })
    fireEvent.click(await screen.findByLabelText('点赞'))

    expect(await screen.findByLabelText('取消点赞')).toBeInTheDocument()
    expect(api.toggleFavorite).toHaveBeenCalledWith(1, 'like')
  })

  it('disables a favorite while its request is pending and leaves status unchanged on failure', async () => {
    let rejectRequest
    api.toggleFavorite.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRequest = reject }))
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })
    const likeButton = await screen.findByLabelText('点赞')
    fireEvent.click(likeButton)
    await waitFor(() => expect(screen.getByLabelText('点赞')).toBeDisabled())
    fireEvent.click(likeButton)
    expect(api.toggleFavorite).toHaveBeenCalledTimes(1)

    rejectRequest(new Error('forbidden'))
    expect(await screen.findByRole('alert')).toHaveTextContent('操作失败')
    expect(screen.getByLabelText('点赞')).toBeInTheDocument()
  })

  it('does not allow a mutation while status could not be loaded', async () => {
    api.checkFavoriteStatus.mockRejectedValue(new Error('network'))
    api.checkBlockedStatus.mockRejectedValue(new Error('network'))
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })

    expect(await screen.findByText('互动状态加载失败。')).toBeInTheDocument()
    expect(screen.getByLabelText('点赞')).toBeDisabled()
    expect(api.toggleFavorite).not.toHaveBeenCalled()
  })

  it('shows login prompt to unauthenticated readers without requesting private status', () => {
    renderWithAuth(<FavoriteButtons newsId={1} />)
    expect(screen.getAllByText('登录')).toHaveLength(2)
    expect(api.checkFavoriteStatus).not.toHaveBeenCalled()
  })

  it('invalidates viewer-scoped news and block lists after a confirmed block', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 12, username: 'test' }, client)

    fireEvent.click(await screen.findByLabelText('屏蔽此新闻'))
    expect(await screen.findByLabelText('取消屏蔽')).toBeInTheDocument()
    expect(api.blockNews).toHaveBeenCalledWith(1)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['news', 'list', { viewerId: 12 }] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['private', 'blocked', { viewerId: 12 }] })
  })

  it('invalidates viewer-scoped lists after a confirmed unblock', async () => {
    isBlocked = true
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 12, username: 'test' }, client)

    fireEvent.click(await screen.findByLabelText('取消屏蔽'))
    await waitFor(() => expect(screen.getByLabelText('屏蔽此新闻')).toBeInTheDocument())
    expect(api.unblockNews).toHaveBeenCalledWith(1)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['news', 'list', { viewerId: 12 }] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['private', 'blocked', { viewerId: 12 }] })
  })
})
