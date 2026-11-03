import { act, renderHook } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useSerialReviewActions } from '@/features/rss/useSerialReviewActions'

it('stops after a failure and retries only unfinished items with the same key', async () => {
  const { result } = renderHook(() => useSerialReviewActions())
  const perform = vi.fn().mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('offline'))
  await act(async () => { await result.current.run(['a', 'b', 'c'], perform) })
  expect(result.current.done).toEqual(['a'])
  expect(perform).toHaveBeenCalledTimes(2)
  const failedKey = perform.mock.calls[1][1]
  perform.mockResolvedValue({})
  await act(async () => { await result.current.run(['a', 'b', 'c'], perform) })
  expect(perform.mock.calls[2]).toEqual(['b', failedKey])
  expect(result.current.done).toEqual(['a', 'b', 'c'])
})

it('does not launch concurrent requests or continue after unmount', async () => {
  const { result, unmount } = renderHook(() => useSerialReviewActions())
  let resolve!: () => void
  const perform = vi.fn(() => new Promise<void>(done => { resolve = done }))
  let pending!: Promise<void>
  act(() => { pending = result.current.run(['a', 'b'], perform) })
  await act(async () => { await result.current.run(['a', 'b'], perform) })
  expect(perform).toHaveBeenCalledTimes(1)
  unmount()
  await act(async () => { resolve(); await pending })
  expect(perform).toHaveBeenCalledTimes(1)
})
