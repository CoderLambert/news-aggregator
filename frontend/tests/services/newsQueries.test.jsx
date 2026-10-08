import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchNews } from '@/services/api'
import { newsKeys, newsListOptions } from '@/services/newsQueries'

vi.mock('@/services/api', () => ({
  fetchNews: vi.fn(),
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
