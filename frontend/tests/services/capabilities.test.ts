import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
  interceptorUse: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: mocks.get,
      post: mocks.post,
      delete: mocks.delete,
      interceptors: { request: { use: mocks.interceptorUse } },
    }),
  },
}))

let api: typeof import('@/services/api')
let validCapabilities: Record<string, unknown>

beforeAll(async () => {
  api = await import('@/services/api')
  const features = Object.fromEntries(api.CAPABILITY_FEATURE_NAMES.map((name) => [name, { enabled: true, reason: null }]))
  validCapabilities = { site_mode: 'full', chatgpt_auth_mode: 'local_oss', features }
})

beforeEach(() => vi.clearAllMocks())

describe('capabilities service', () => {
  it('fetches the same-origin capability snapshot and validates its complete schema', async () => {
    mocks.get.mockResolvedValueOnce({ data: validCapabilities })

    await expect(api.fetchCapabilities()).resolves.toEqual(api.parseCapabilities(validCapabilities))
    expect(mocks.get).toHaveBeenCalledWith('/capabilities/')
  })

  it.each([
    ['unknown site mode', (value: Record<string, unknown>) => ({ ...value, site_mode: 'preview' })],
    ['unknown auth mode', (value: Record<string, unknown>) => ({ ...value, chatgpt_auth_mode: 'oauth' })],
    ['missing feature', (value: Record<string, unknown>) => {
      const features = { ...(value.features as object) }
      delete (features as Record<string, unknown>).tts
      return { ...value, features }
    }],
    ['non-boolean feature', (value: Record<string, unknown>) => ({
      ...value,
      features: { ...(value.features as object), accounts: { enabled: 'false', reason: 'public_read_only' } },
    })],
    ['enabled feature with reason', (value: Record<string, unknown>) => ({
      ...value,
      features: { ...(value.features as object), accounts: { enabled: true, reason: 'public_read_only' } },
    })],
    ['unknown disabled reason', (value: Record<string, unknown>) => ({
      ...value,
      features: { ...(value.features as object), accounts: { enabled: false, reason: 'secret_config' } },
    })],
  ])('rejects %s', (_label, corrupt) => {
    expect(() => api.parseCapabilities(corrupt(validCapabilities))).toThrow(TypeError)
  })

  it('keeps the narrow BYOK first-run capability distinct from hosted research', () => {
    const features = {
      ...(validCapabilities.features as Record<string, unknown>),
      research: { enabled: false, reason: 'hosted_integration_unapproved' },
      research_byok_create: { enabled: true, reason: null },
    }
    const parsed = api.parseCapabilities({ ...validCapabilities, features })

    expect(parsed.features.research).toEqual({
      enabled: false,
      reason: 'hosted_integration_unapproved',
    })
    expect(parsed.features.research_byok_create).toEqual({ enabled: true, reason: null })
  })

  it('accepts only the exact current-origin handoff target', async () => {
    const handoffUrl = new URL('/api/chatgpt-subscription/handoff/', window.location.origin).href
    mocks.post.mockResolvedValueOnce({
      data: {
        attempt_id: 'attempt-1',
        handoff_token: 'opaque-test-token',
        handoff_url: handoffUrl,
      },
    })

    await expect(api.startChatGPTSubscriptionConnect()).resolves.toMatchObject({
      attempt_id: 'attempt-1',
      handoff_url: handoffUrl,
    })
    expect(mocks.post).toHaveBeenCalledWith('/chatgpt-subscription/connect/', {})
  })

  it.each([
    'http://127.0.0.1.evil:9527/api/chatgpt-subscription/handoff/',
    'http://user@127.0.0.1:9527/api/chatgpt-subscription/handoff/',
    'https://127.0.0.1:9527/api/chatgpt-subscription/handoff/',
    'http://127.0.0.1:9528/api/chatgpt-subscription/handoff/',
    `${window.location.origin}/api/chatgpt-subscription/handoff/?token=secret`,
    `${window.location.origin}/api/chatgpt-subscription/handoff/#fragment`,
    `${window.location.origin}/api/chatgpt-subscription/other/`,
  ])('rejects unsafe handoff target %s', async (handoff_url) => {
    mocks.post.mockResolvedValueOnce({
      data: { attempt_id: 'attempt-1', handoff_token: 'opaque-test-token', handoff_url },
    })
    await expect(api.startChatGPTSubscriptionConnect()).rejects.toThrow(/handoff URL/)
  })
})

it('accepts retired collection without disabling account and reader features', async () => {
  const snapshot = {
    ...validCapabilities,
    features: {
      ...(validCapabilities.features as object),
      provider_comparisons: { enabled: false, reason: 'legacy_ingestion_retired' },
    },
  }
  mocks.get.mockResolvedValueOnce({ data: snapshot })
  const capabilities = await api.fetchCapabilities()
  expect(capabilities.features.provider_comparisons).toEqual({
    enabled: false, reason: 'legacy_ingestion_retired',
  })
  expect(capabilities.features.accounts.enabled).toBe(true)
  expect(capabilities.features.favorites.enabled).toBe(true)
})
