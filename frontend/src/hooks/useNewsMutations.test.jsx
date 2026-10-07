import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { blockNews } from '@/services/api'
import { useBlockNews } from '@/hooks/useNewsMutations'

vi.mock('@/services/api', () => ({ blockNews: vi.fn() }))

function renderMutation() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const wrapper = ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const hook = renderHook(() => useBlockNews(), { wrapper })
  return { ...hook, invalidate }
}

beforeEach(() => vi.clearAllMocks())

describe('useBlockNews', () => {
  it('invalidates list queries after the server accepts a block', async () => {
    blockNews.mockResolvedValue({ created: true })
    const { result, invalidate } = renderMutation()
    await act(async () => { await result.current.mutateAsync(21) })
    expect(blockNews).toHaveBeenCalledWith(21)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['news', 'list'] })
  })

  it('leaves query caches untouched when the server rejects a block', async () => {
    blockNews.mockRejectedValue(new Error('forbidden'))
    const { result, invalidate } = renderMutation()
    await act(async () => { await expect(result.current.mutateAsync(21)).rejects.toThrow('forbidden') })
    expect(invalidate).not.toHaveBeenCalled()
  })
})
