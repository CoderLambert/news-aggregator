import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { AuthContext } from '@/context/AuthContext'
import { blockNews, checkBlockedStatus, toggleFavorite, unblockNews } from '@/services/api'
import { useBlockNews, useToggleFavorite, useUnblockNews } from '@/hooks/useNewsMutations'
import { blockStatusOptions, privateNewsKeys } from '@/services/userNewsQueries'
import { parseFavoriteToggleResult } from '@/types/userNews'

vi.mock('@/services/api', () => ({
  blockNews: vi.fn(),
  checkBlockedStatus: vi.fn(),
  toggleFavorite: vi.fn(),
  unblockNews: vi.fn(),
}))

function deferred() {
  let resolve
  const promise = new Promise((accept) => { resolve = accept })
  return { promise, resolve }
}

async function startAndResolveLateBlockReads({ client, result, mutation, mutationReply, staleValue, expectedValue }) {
  const firstRead = deferred()
  const overlappingRead = deferred()
  const mutationRequest = deferred()
  checkBlockedStatus.mockReturnValueOnce(firstRead.promise).mockReturnValueOnce(overlappingRead.promise)
  mutation.mockReturnValueOnce(mutationRequest.promise)

  const firstReadPromise = client.fetchQuery(blockStatusOptions(12, 21)).catch(() => undefined)
  await waitFor(() => expect(checkBlockedStatus).toHaveBeenCalledTimes(1))
  expect(checkBlockedStatus.mock.calls[0][1]).toBeInstanceOf(AbortSignal)

  let mutationPromise
  await act(async () => {
    mutationPromise = result.current.mutateAsync({ newsId: 21, viewerId: 12 })
    await Promise.resolve()
  })
  await waitFor(() => expect(mutation).toHaveBeenCalledTimes(1))

  const overlappingReadPromise = client.fetchQuery(blockStatusOptions(12, 21)).catch(() => undefined)
  await waitFor(() => expect(checkBlockedStatus).toHaveBeenCalledTimes(2))

  await act(async () => {
    mutationRequest.resolve(mutationReply)
    await mutationPromise
  })
  expect(checkBlockedStatus.mock.calls[0][1].aborted).toBe(true)
  expect(checkBlockedStatus.mock.calls[1][1].aborted).toBe(true)

  firstRead.resolve(staleValue)
  overlappingRead.resolve(staleValue)
  await Promise.all([firstReadPromise, overlappingReadPromise])
  expect(client.getQueryData(privateNewsKeys.blockStatus(12, 21))).toEqual(expectedValue)
}

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
  it.each([
    { created: false },
    { removed: false },
    { created: false, removed: false },
  ])('accepts a successful no-op response %#', (response) => {
    expect(parseFavoriteToggleResult(response)).toEqual({ created: false, removed: false })
  })

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

  it('accepts a concurrent no-op response without changing cached counts or retrying the POST', async () => {
    toggleFavorite.mockResolvedValue({ created: false })
    const { result, client, invalidate } = renderMutation(useToggleFavorite)
    const statusKey = privateNewsKeys.favoriteStatus(12, 21)
    const favorite = {
      id: 55,
      news: { id: 21, title: 'Existing favorite', title_zh: '', content: '', content_zh: '', url: '', cover_image: '', source_name: '', category_name: '', publish_time: '2026-10-06T09:00:00Z', created_at: '' },
      type: 'like',
      created_at: '2026-10-07T06:00:00Z',
    }
    const listKey = privateNewsKeys.favorites(12, 'all')
    const status = { is_liked: true, is_bookmarked: false, like_count: 8, bookmark_count: 1 }
    const page = { count: 1, next: null, previous: null, results: [favorite] }
    client.setQueryData(statusKey, status)
    client.setQueryData(listKey, page)

    await act(async () => { await result.current.mutateAsync({ newsId: 21, viewerId: 12, type: 'like' }) })

    expect(toggleFavorite).toHaveBeenCalledTimes(1)
    expect(result.current.isError).toBe(false)
    expect(client.getQueryData(statusKey)).toEqual(status)
    expect(client.getQueryData(listKey)).toEqual(page)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: privateNewsKeys.favoriteLists(12) })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: statusKey, exact: true })
  })

  it('keeps rejecting contradictory favorite mutation flags', async () => {
    toggleFavorite.mockResolvedValue({ created: true, removed: true })
    const { result, client, invalidate } = renderMutation(useToggleFavorite)
    const statusKey = privateNewsKeys.favoriteStatus(12, 21)
    const status = { is_liked: false, is_bookmarked: false, like_count: 2, bookmark_count: 1 }
    client.setQueryData(statusKey, status)

    await act(async () => {
      await expect(result.current.mutateAsync({ newsId: 21, viewerId: 12, type: 'like' })).rejects.toThrow('Invalid favorite mutation response')
    })

    expect(toggleFavorite).toHaveBeenCalledTimes(1)
    expect(client.getQueryData(statusKey)).toEqual(status)
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
    expect(invalidate).toHaveBeenCalledWith({ queryKey: statusKey, exact: true })
  })

  it('cancels stale and overlapping status GETs before keeping the confirmed blocked state', async () => {
    const { result, client } = renderMutation(useBlockNews)
    await startAndResolveLateBlockReads({
      client,
      result,
      mutation: blockNews,
      mutationReply: { created: true },
      staleValue: { is_blocked: false },
      expectedValue: { is_blocked: true },
    })
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
    expect(invalidate).toHaveBeenCalledWith({ queryKey: statusKey, exact: true })
  })

  it('cancels stale and overlapping status GETs before keeping the confirmed unblocked state', async () => {
    const { result, client } = renderMutation(useUnblockNews)
    client.setQueryData(privateNewsKeys.blockStatus(12, 21), { is_blocked: true })
    await startAndResolveLateBlockReads({
      client,
      result,
      mutation: unblockNews,
      mutationReply: { removed: true },
      staleValue: { is_blocked: true },
      expectedValue: { is_blocked: false },
    })
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
