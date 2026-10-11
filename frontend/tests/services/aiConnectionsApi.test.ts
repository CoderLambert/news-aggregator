import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  interceptorUse: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: mocks.get,
      post: mocks.post,
      put: mocks.put,
      patch: mocks.patch,
      delete: mocks.delete,
      interceptors: { request: { use: mocks.interceptorUse } },
    }),
  },
}))

let api: typeof import('@/services/api')

const connection = {
  id: 'conn-1', provider_id: 'deepseek', provider_name: 'DeepSeek', endpoint_profile: 'deepseek_default',
  region_name: '通用 API', display_name: 'DeepSeek · 个人', key_saved: true, masked_key: '••••••••',
  is_enabled: true, verification_status: 'not_tested', updated_at: '2026-10-11T00:00:00Z',
}

beforeAll(async () => {
  api = await import('@/services/api')
})

beforeEach(() => vi.clearAllMocks())

describe('BYOK connection API boundary', () => {
  it('posts the key only to the authenticated same-origin connection endpoint and parses a masked response', async () => {
    const secret = 'sk-t01-synthetic-service-key-never-real'
    const input = {
      provider_id: 'deepseek', endpoint_profile: 'deepseek_default',
      display_name: '个人 DeepSeek', api_key: secret,
    }
    mocks.post.mockResolvedValueOnce({ data: connection })

    await expect(api.createAIConnection(input)).resolves.toEqual(connection)
    expect(mocks.post).toHaveBeenCalledWith('/ai/connections/', input)
  })

  it('rejects any connection API response that includes raw or encrypted credential material', async () => {
    mocks.get.mockResolvedValueOnce({ data: { connections: [{ ...connection, credential_ciphertext: 'should-never-reach-browser' }] } })

    await expect(api.fetchAIConnections()).rejects.toThrow(TypeError)
  })
})
