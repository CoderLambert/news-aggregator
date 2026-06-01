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
    apiModule = await import('./api')
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

  it('retestProviderComparison posts to the retest action endpoint', async () => {
    axios.__mock.clients[2].post.mockResolvedValueOnce({ data: { id: 7, status: 'queued' } })

    const result = await apiModule.retestProviderComparison(7)

    expect(axios.__mock.clients[2].post).toHaveBeenCalledWith('/provider-comparisons/7/retest/')
    expect(axios.__mock.clients[2].config.timeout).toBe(180_000)
    expect(result).toEqual({ id: 7, status: 'queued' })
  })
})
