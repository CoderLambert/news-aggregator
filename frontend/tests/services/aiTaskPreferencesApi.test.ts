import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
  interceptorUse: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: mocks.get,
      post: vi.fn(),
      patch: mocks.patch,
      delete: vi.fn(),
      put: vi.fn(),
      interceptors: { request: { use: mocks.interceptorUse } },
    }),
  },
}))

let api: typeof import('@/services/api')

const taskKinds = ['default', 'article_qa', 'full_translation', 'deep_research', 'question_suggestions'] as const
const preferences = taskKinds.map((task_kind) => ({
  task_kind,
  model_config_id: null,
  selection_state: task_kind === 'default' ? 'unset' : 'inherit_default',
  model: null,
}))

beforeAll(async () => {
  api = await import('@/services/api')
})

beforeEach(() => vi.clearAllMocks())

describe('BYOK task preference API boundary', () => {
  it('reads the complete five-purpose preference set without caching', async () => {
    mocks.get.mockResolvedValueOnce({ data: { preferences } })

    const result = await api.fetchAITaskPreferences()
    expect(result).toHaveLength(5)
    expect(result.slice(0, 2)).toMatchObject([
      { task_kind: 'default', selection_state: 'unset' },
      { task_kind: 'article_qa', selection_state: 'inherit_default' },
    ])
    expect(mocks.get).toHaveBeenCalledWith('/ai/preferences/', { signal: undefined })
  })

  it('sends only task choices and rejects incomplete or secret-bearing response data', async () => {
    const input = [
      { task_kind: 'default' as const, model_config_id: 'model-1', api_key: 'synthetic-never-real' },
      ...taskKinds.slice(1).map((task_kind) => ({ task_kind, model_config_id: null })),
    ]
    mocks.patch.mockResolvedValueOnce({ data: { preferences } })

    await expect(api.saveAITaskPreferences(input)).resolves.toHaveLength(5)
    expect(mocks.patch).toHaveBeenCalledWith('/ai/preferences/', {
      preferences: input.map(({ task_kind, model_config_id }) => ({ task_kind, model_config_id })),
    })
    expect(JSON.stringify(mocks.patch.mock.calls)).not.toContain('synthetic-never-real')

    mocks.get.mockResolvedValueOnce({ data: { preferences: preferences.slice(1) } })
    await expect(api.fetchAITaskPreferences()).rejects.toThrow(TypeError)

    mocks.get.mockResolvedValueOnce({ data: { preferences: [{
      ...preferences[0], api_key: 'synthetic-never-real',
    }, ...preferences.slice(1)] } })
    await expect(api.fetchAITaskPreferences()).rejects.toThrow(TypeError)
  })
})
