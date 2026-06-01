import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import FavoriteButtons from './FavoriteButtons'
import * as api from '@/services/api'
import { AuthContext } from '@/context/AuthContext'

vi.mock('@/services/api', () => ({
  toggleFavorite: vi.fn(),
  checkFavoriteStatus: vi.fn(),
  blockNews: vi.fn(),
  checkBlockedStatus: vi.fn(),
}))

function renderWithAuth(ui, user = null) {
  return render(
    <AuthContext.Provider value={{ user, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
      {ui}
    </AuthContext.Provider>
  )
}

describe('FavoriteButtons', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.checkFavoriteStatus.mockResolvedValue({
      is_liked: false, is_bookmarked: false, like_count: 5, bookmark_count: 3,
    })
    api.checkBlockedStatus.mockResolvedValue({ is_blocked: false })
  })

  it('renders loading state initially', () => {
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })
    expect(document.querySelectorAll('.animate-pulse').length).toBeGreaterThanOrEqual(2)
  })

  it('renders like and bookmark buttons after loading', async () => {
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })
    await waitFor(() => {
      expect(screen.getByLabelText('点赞')).toBeInTheDocument()
      expect(screen.getByLabelText('收藏')).toBeInTheDocument()
      expect(screen.getByLabelText('屏蔽此新闻')).toBeInTheDocument()
    })
  })

  it('shows counts correctly', async () => {
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })
    await waitFor(() => {
      expect(screen.getByText('5')).toBeInTheDocument()
      expect(screen.getByText('3')).toBeInTheDocument()
    })
  })

  it('toggles like on click', async () => {
    api.toggleFavorite.mockResolvedValue({ created: true })
    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })

    await waitFor(() => expect(screen.getByLabelText('点赞')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('点赞'))

    await waitFor(() => {
      expect(api.toggleFavorite).toHaveBeenCalledWith(1, 'like')
    })
  })

  it('handles removed response correctly', async () => {
    api.checkFavoriteStatus.mockResolvedValue({
      is_liked: true, is_bookmarked: true, like_count: 5, bookmark_count: 3,
    })
    api.toggleFavorite.mockResolvedValue({ removed: true })

    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })

    await waitFor(() => expect(screen.getByLabelText('取消点赞')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('取消点赞'))

    await waitFor(() => {
      expect(api.toggleFavorite).toHaveBeenCalledWith(1, 'like')
    })
  })

  it('silently fails on API error', async () => {
    api.checkFavoriteStatus.mockRejectedValue(new Error('fail'))
    api.checkBlockedStatus.mockRejectedValue(new Error('fail'))
    api.toggleFavorite.mockRejectedValue(new Error('fail'))

    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })

    await waitFor(() => {
      expect(screen.getByLabelText('点赞')).toBeInTheDocument()
    })

    // Clicking should not throw
    fireEvent.click(screen.getByLabelText('点赞'))
  })

  it('shows login prompt when unauthenticated', async () => {
    renderWithAuth(<FavoriteButtons newsId={1} />, null)
    await waitFor(() => {
      expect(screen.getAllByText('登录')).toHaveLength(2)
    })
  })

  it('blocks news on block button click', async () => {
    api.blockNews.mockResolvedValue({ created: true })

    renderWithAuth(<FavoriteButtons newsId={1} />, { id: 1, username: 'test' })

    await waitFor(() => expect(screen.getByLabelText('屏蔽此新闻')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('屏蔽此新闻'))

    await waitFor(() => {
      expect(api.blockNews).toHaveBeenCalledWith(1)
    })
  })
})
