import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import axios from 'axios'

const mockState = vi.hoisted(() => ({ clients: [] }))

vi.mock('axios', () => {
  const requestUse = vi.fn()
  return {
    default: {
      interceptors: { request: { use: vi.fn() } },
      create: vi.fn((config) => {
        const client = {
          config,
          get: vi.fn(),
          post: vi.fn(),
          interceptors: { request: { use: requestUse } },
        }
        mockState.clients.push(client)
        return client
      }),
      __mock: { clients: mockState.clients, requestUse },
    },
  }
})

describe('provider comparison api', () => {
  let apiModule

  beforeEach(async () => {
    vi.resetModules()
    axios.__mock.clients.length = 0
    apiModule = await import('@/services/api')
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('fetchProviderComparisons calls GET /provider-comparisons/ with params', async () => {
    axios.__mock.clients[0].get.mockResolvedValueOnce({ data: { count: 0, results: [] } })

    const result = await apiModule.fetchProviderComparisons({ page: 2, search: 'scrapy' })

    expect(axios.__mock.clients[0].get).toHaveBeenCalledWith('/provider-comparisons/', {
      params: { page: 2, search: 'scrapy' },
    })
    expect(result).toEqual({ count: 0, results: [] })
  })

  it('passes TanStack cancellation through comparison list reads', async () => {
    const controller = new AbortController()
    axios.__mock.clients[0].get.mockResolvedValueOnce({ data: { count: 0, results: [] } })

    await apiModule.fetchProviderComparisons({}, controller.signal)

    expect(axios.__mock.clients[0].get).toHaveBeenCalledWith('/provider-comparisons/', {
      params: {},
      signal: controller.signal,
    })
  })

  it('createProviderComparison posts news_id or url payload', async () => {
    axios.__mock.clients[2].post.mockResolvedValueOnce({ data: { id: 12 } })

    const result = await apiModule.createProviderComparison({ news_id: '42', url: '' })

    expect(axios.__mock.clients[2].post).toHaveBeenCalledWith('/provider-comparisons/', {
      news_id: '42',
      url: '',
    })
    expect(axios.__mock.clients[2].config.timeout).toBe(180_000)
    expect(result).toEqual({ id: 12 })
  })

  it('passes a caller AbortSignal to a provider comparison create request', async () => {
    const controller = new AbortController()
    axios.__mock.clients[2].post.mockResolvedValueOnce({ data: { run_id: 'run-1' } })

    await apiModule.createProviderComparison({ news_id: '42' }, controller.signal)

    expect(axios.__mock.clients[2].post).toHaveBeenCalledWith('/provider-comparisons/', { news_id: '42' }, { signal: controller.signal })
  })

  it('retestProviderComparison posts to the retest action endpoint', async () => {
    axios.__mock.clients[2].post.mockResolvedValueOnce({ data: { id: 7, status: 'queued' } })

    const result = await apiModule.retestProviderComparison(7)

    expect(axios.__mock.clients[2].post).toHaveBeenCalledWith('/provider-comparisons/7/retest/')
    expect(axios.__mock.clients[2].config.timeout).toBe(180_000)
    expect(result).toEqual({ id: 7, status: 'queued' })
  })

  it('passes a separate AbortSignal to each provider retest request', async () => {
    const jinaController = new AbortController()
    const scrapyController = new AbortController()
    axios.__mock.clients[2].post.mockResolvedValue({ data: { run_id: 'run-1' } })

    await Promise.all([
      apiModule.retestProviderComparison(7, jinaController.signal),
      apiModule.retestProviderComparison(8, scrapyController.signal),
    ])

    expect(axios.__mock.clients[2].post).toHaveBeenNthCalledWith(1, '/provider-comparisons/7/retest/', undefined, { signal: jinaController.signal })
    expect(axios.__mock.clients[2].post).toHaveBeenNthCalledWith(2, '/provider-comparisons/8/retest/', undefined, { signal: scrapyController.signal })
    expect(jinaController.signal).not.toBe(scrapyController.signal)
  })
})
