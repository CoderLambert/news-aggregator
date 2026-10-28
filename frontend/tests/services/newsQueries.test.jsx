import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchNews } from '@/services/api'
import { newsKeys, newsListOptions } from '@/services/newsQueries'

vi.mock('@/services/api', () => ({
  fetchNews: vi.fn(),
  fetchNewsDetail: vi.fn(),
  fetchCategories: vi.fn(),
  fetchSources: vi.fn(),
}))

beforeEach(() => vi.clearAllMocks())

describe('news query definitions', () => {
  it('partitions cached list data by filters, language, and viewer', () => {
    const params = { page: 3, page_size: 20, category: '2,4' }
    const anonymousKey = newsKeys.list(params, 'zh', 'anonymous')
    const readerKey = newsKeys.list(params, 'zh', 12)
    const englishKey = newsKeys.list(params, 'en', 12)
    expect(anonymousKey).not.toEqual(readerKey)
    expect(readerKey).not.toEqual(englishKey)
    expect(newsKeys.list({ ...params, page: 1 }, 'zh', 12)).not.toEqual(readerKey)
  })

  it('passes TanStack Query cancellation to Axios and parses the response at the boundary', async () => {
    fetchNews.mockResolvedValue({ count: 0, results: [] })
    const signal = new AbortController().signal
    const options = newsListOptions({ page: 1, page_size: 20 }, 'zh', 'anonymous')
    const data = await options.queryFn({ signal })
    expect(fetchNews).toHaveBeenCalledWith({ page: 1, page_size: 20 }, signal)
    expect(data).toEqual({ count: 0, results: [], next: null, previous: null })
  })
})


it('coalesces feed-card detail prefetches into the card the pointer settles on', async () => {
  vi.useFakeTimers()
  const { QueryClient } = await import('@tanstack/react-query')
  const { fetchNewsDetail } = await import('@/services/api')
  const { cancelScheduledNewsDetailPrefetch, resetScheduledNewsDetailPrefetch, scheduleNewsDetailPrefetch } = await import('@/services/newsQueries')
  fetchNewsDetail.mockResolvedValue({ id: 1, title: 'Settled', content: 'body', content_zh: '' })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  resetScheduledNewsDetailPrefetch()
  for (const id of [11, 12, 13]) scheduleNewsDetailPrefetch(client, id, 'zh', 4)
  await vi.advanceTimersByTimeAsync(179)
  expect(fetchNewsDetail).not.toHaveBeenCalled()
  cancelScheduledNewsDetailPrefetch(client, 13, 'zh', 4)
  await vi.advanceTimersByTimeAsync(180)
  expect(fetchNewsDetail).not.toHaveBeenCalled()
  scheduleNewsDetailPrefetch(client, 13, 'zh', 4)
  await vi.advanceTimersByTimeAsync(180)
  expect(fetchNewsDetail).toHaveBeenCalledTimes(1)
  expect(fetchNewsDetail).toHaveBeenCalledWith(13, expect.any(AbortSignal))
  cancelScheduledNewsDetailPrefetch(client, 13, 'zh', 4)
  scheduleNewsDetailPrefetch(client, 14, 'zh', 4)
  await vi.advanceTimersByTimeAsync(180)
  expect(fetchNewsDetail).toHaveBeenCalledTimes(2)
  expect(fetchNewsDetail).toHaveBeenLastCalledWith(14, expect.any(AbortSignal))
  resetScheduledNewsDetailPrefetch()
  client.clear()
  vi.useRealTimers()
})

it('keeps source data separate for two viewers and subscription versus history use', async () => {
  const { QueryClient } = await import('@tanstack/react-query')
  const { sourceOptions } = await import('@/services/newsQueries')
  const { fetchSources } = await import('@/services/api')
  const client = new QueryClient()
  fetchSources.mockResolvedValueOnce([{ id: 1, name: 'A private source' }])
    .mockResolvedValueOnce([{ id: 2, name: 'B private source' }])
    .mockResolvedValueOnce([{ id: 3, name: 'Subscribe catalog' }])
  const a = await client.fetchQuery(sourceOptions('zh', 11, 'history'))
  const b = await client.fetchQuery(sourceOptions('zh', 12, 'history'))
  const catalog = await client.fetchQuery(sourceOptions('zh', 11, 'subscribe'))
  expect(a[0].name).toBe('A private source')
  expect(b[0].name).toBe('B private source')
  expect(catalog[0].name).toBe('Subscribe catalog')
  expect(fetchSources.mock.calls.map(call => call[1])).toEqual(['history', 'history', 'subscribe'])
  client.clear()
})
