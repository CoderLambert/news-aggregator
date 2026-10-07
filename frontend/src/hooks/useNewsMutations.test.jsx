import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { AuthContext } from '@/context/AuthContext'
import { blockNews, toggleFavorite, unblockNews } from '@/services/api'
import { useBlockNews, useToggleFavorite, useUnblockNews } from '@/hooks/useNewsMutations'
import { privateNewsKeys } from '@/services/userNewsQueries'

vi.mock('@/services/api', () => ({ blockNews: vi.fn(), toggleFavorite: vi.fn(), unblockNews: vi.fn() }))

function renderMutation(useMutationHook) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const wrapper = ({ children }) => (
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={{ user: { id: 12, username: 'reader' }, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), refresh: vi.fn() }}>
        {children}
      </AuthContext.Provider>
    </QueryClientProvider>
  )
  const hook = renderHook(() => useMutationHook(), { wrapper })
  return { ...hook, client, invalidate }
}

beforeEach(() => vi.clearAllMocks())

describe('favorite mutations', () => {
  it('updates confirmed status counts and invalidates viewer favorite lists', async () => {
    toggleFavorite.mockResolvedValue({ created: true })
    const { result, client, invalidate } = renderMutation(useToggleFavorite)
    const statusKey = privateNewsKeys.favoriteStatus(12, 21)
    client.setQueryData(statusKey, { is_liked: false, is_bookmarked: false, like_count: 2, bookmark_count: 1 })

    await act(async () => { await result.current.mutateAsync({ newsId: 21, viewerId: 12, type: 'like' }) })

    expect(toggleFavorite).toHaveBeenCalledWith(21, 'like')
    expect(client.getQueryData(statusKey)).toEqual({ is_liked: true, is_bookmarked: false, like_count: 3, bookmark_count: 1 })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: privateNewsKeys.favoriteLists(12) })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: statusKey, exact: true })
  })

  it('does not change favorite caches when the server rejects a toggle', async () => {
    toggleFavorite.mockRejectedValue(new Error('forbidden'))
    const { result, client, invalidate } = renderMutation(useToggleFavorite)
    const statusKey = privateNewsKeys.favoriteStatus(12, 21)
    client.setQueryData(statusKey, { is_liked: false, is_bookmarked: false, like_count: 2, bookmark_count: 1 })

    await act(async () => {
      await expect(result.current.mutateAsync({ newsId: 21, viewerId: 12, type: 'like' })).rejects.toThrow('forbidden')
    })
    expect(client.getQueryData(statusKey).is_liked).toBe(false)
    expect(invalidate).not.toHaveBeenCalled()
  })

  it('adds the server-serialized favorite to matching cached lists after creation', async () => {
    const favorite = {
      id: 55,
      news: {
        id: 21, title: 'New article', title_zh: '', content: 'summary', content_zh: '',
        url: 'https://example.com/article', cover_image: null, source_name: 'Example',
        category_name: 'Technology', publish_time: '2026-10-06T09:00:00Z',
      },
      type: 'bookmark',
      created_at: '2026-10-07T06:00:00Z',
      created: true,
    }
    toggleFavorite.mockResolvedValue(favorite)
    const { result, client } = renderMutation(useToggleFavorite)
    const allKey = privateNewsKeys.favorites(12, 'all')
    const bookmarksKey = privateNewsKeys.favorites(12, 'bookmark')
    client.setQueryData(allKey, { count: 0, next: null, previous: null, results: [] })
    client.setQueryData(bookmarksKey, { count: 0, next: null, previous: null, results: [] })

    await act(async () => { await result.current.mutateAsync({ newsId: 21, viewerId: 12, type: 'bookmark' }) })

    expect(client.getQueryData(allKey)).toMatchObject({ count: 1, results: [{ id: 55, type: 'bookmark', news: { id: 21 } }] })
    expect(client.getQueryData(bookmarksKey)).toMatchObject({ count: 1, results: [{ id: 55, type: 'bookmark', news: { id: 21 } }] })
  })
})

describe('useBlockNews', () => {
  it('updates block status and invalidates only the initiating viewer caches after success', async () => {
    blockNews.mockResolvedValue({ created: false })
    const { result, client, invalidate } = renderMutation(useBlockNews)
    const statusKey = privateNewsKeys.blockStatus(12, 21)

    await act(async () => { await result.current.mutateAsync({ newsId: 21, viewerId: 12 }) })

    expect(blockNews).toHaveBeenCalledWith(21)
    expect(client.getQueryData(statusKey)).toEqual({ is_blocked: true })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['news', 'list', { viewerId: 12 }] })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: privateNewsKeys.blocked(12) })
  })

  it('leaves caches untouched when the server rejects a block', async () => {
    blockNews.mockRejectedValue(new Error('forbidden'))
    const { result, invalidate } = renderMutation(useBlockNews)

    await act(async () => {
      await expect(result.current.mutateAsync({ newsId: 21, viewerId: 12 })).rejects.toThrow('forbidden')
    })
    expect(invalidate).not.toHaveBeenCalled()
  })
})

describe('useUnblockNews', () => {
  it('marks the block removed and invalidates viewer list caches after success', async () => {
    unblockNews.mockResolvedValue({ removed: true })
    const { result, client, invalidate } = renderMutation(useUnblockNews)
    const statusKey = privateNewsKeys.blockStatus(12, 21)
    client.setQueryData(privateNewsKeys.blocked(12), {
      count: 1, next: null, previous: null,
      results: [{ id: 4, news: { id: 21, title: 'Blocked story' }, created_at: '2026-10-06T09:00:00Z' }],
    })

    await act(async () => { await result.current.mutateAsync({ newsId: 21, viewerId: 12 }) })

    expect(unblockNews).toHaveBeenCalledWith(21)
    expect(client.getQueryData(statusKey)).toEqual({ is_blocked: false })
    expect(client.getQueryData(privateNewsKeys.blocked(12)).results).toEqual([])
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['news', 'list', { viewerId: 12 }] })
  })

  it('leaves caches untouched when the server rejects an unblock', async () => {
    unblockNews.mockRejectedValue(new Error('forbidden'))
    const { result, invalidate } = renderMutation(useUnblockNews)

    await act(async () => {
      await expect(result.current.mutateAsync({ newsId: 21, viewerId: 12 })).rejects.toThrow('forbidden')
    })
    expect(invalidate).not.toHaveBeenCalled()
  })
})
