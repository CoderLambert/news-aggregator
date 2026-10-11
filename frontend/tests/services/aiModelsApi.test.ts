import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  interceptorUse: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: mocks.get,
      post: mocks.post,
      patch: mocks.patch,
      delete: mocks.delete,
      put: vi.fn(),
      interceptors: { request: { use: mocks.interceptorUse } },
    }),
  },
}))

let api: typeof import('@/services/api')

const model = {
  id: 'model-1', connection_id: 'connection-1', model_id: 'vendor/custom-model',
  display_name: 'vendor/custom-model', source: 'manual', catalog_model_id: '', catalog_version: '',
  catalog_source_url: '', provider_claims: {}, context_window_tokens: null, max_output_tokens: null,
  has_trusted_context_limit: false, config_revision: 1, verification_status: 'not_tested',
  capabilities: { text: 'unknown', tools: 'unknown', structured_output: 'unknown', thinking: 'unknown', stream: 'unknown' },
  last_tested_at: null, updated_at: '2026-10-12T00:00:00Z',
}

beforeAll(async () => {
  api = await import('@/services/api')
})

beforeEach(() => vi.clearAllMocks())

describe('BYOK model API boundary', () => {
  it('parses the versioned catalog and rejects internal route metadata', async () => {
    mocks.get.mockResolvedValueOnce({
      data: {
        catalog_version: '2026-10-12.1',
        catalog_available: true,
        models: [{
          catalog_model_id: 'deepseek-flash', provider_id: 'deepseek', model_id: 'deepseek-flash',
          display_name: 'DeepSeek V4.1 Flash', context_window_tokens: 1_048_576,
          max_output_tokens: 393_216, catalog_version: '2026-10-12.1',
          source_url: 'https://api-docs.deepseek.com/api/list-models/', provider_claims: { tools: true },
        }],
      },
    })

    await expect(api.fetchAIModelCatalog()).resolves.toMatchObject({
      catalog_version: '2026-10-12.1', models: [{ model_id: 'deepseek-flash' }], catalog_available: true,
    })
    expect(mocks.get).toHaveBeenCalledWith('/ai/models/catalog/', { signal: undefined })

    mocks.get.mockResolvedValueOnce({ data: { models: [{ ...model, proxy_model_alias: 'internal-only' }] } })
    await expect(api.fetchAIModels()).rejects.toThrow(TypeError)
  })

  it('sends only the selected connection and model identifier to the owner-scoped API', async () => {
    const input = { connection_id: 'connection-1', model_id: 'vendor/custom-model', display_name: 'Manual model' }
    mocks.post.mockResolvedValueOnce({ data: { ...model, display_name: 'Manual model' } })

    await expect(api.createAIModel(input)).resolves.toMatchObject({
      connection_id: 'connection-1', model_id: 'vendor/custom-model', verification_status: 'not_tested',
    })
    expect(mocks.post).toHaveBeenCalledWith('/ai/models/', input)
    expect(JSON.stringify(mocks.post.mock.calls)).not.toContain('api_key')
  })

  it('posts only a capability kind and rejects provider payloads in the response', async () => {
    mocks.post.mockResolvedValueOnce({ data: {
      attempt_id: 'attempt-1', probe_kind: 'text', status: 'succeeded',
      verification_status: 'verified', capability: 'supported', stale: false,
      safe_error_code: '', latency_ms: 120, input_tokens: 8, output_tokens: 2,
      billing_notice: 'provider_may_bill',
    } })

    await expect(api.testAIModel('model-1', 'text')).resolves.toMatchObject({
      attempt_id: 'attempt-1', status: 'succeeded', capability: 'supported',
      billing_notice: 'provider_may_bill',
    })
    expect(mocks.post).toHaveBeenCalledWith('/ai/models/model-1/test/', { probe_kind: 'text' })
    expect(JSON.stringify(mocks.post.mock.calls)).not.toContain('api_key')

    mocks.post.mockResolvedValueOnce({ data: {
      attempt_id: 'attempt-2', probe_kind: 'text', status: 'succeeded',
      verification_status: 'verified', capability: 'supported', stale: false,
      safe_error_code: '', latency_ms: 80, input_tokens: null, output_tokens: null,
      billing_notice: 'provider_may_bill', raw_response: { api_key: 'synthetic-secret' },
    } })
    await expect(api.testAIModel('model-1', 'text')).rejects.toThrow(TypeError)
  })
})
