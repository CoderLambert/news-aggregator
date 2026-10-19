import { beforeEach, expect, it, vi } from 'vitest'
const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), interceptors: { request: { use: vi.fn() } } }))
vi.mock('axios', () => ({ default: {
  interceptors: { request: { use: vi.fn() } }, create: vi.fn(() => client),
} }))
import { fetchSuggestedQuestions } from '@/services/api'
beforeEach(() => { vi.clearAllMocks(); client.get.mockResolvedValue({ data: {} }); client.post.mockResolvedValue({ data: {} }) })
it('loads suggestions with a read-only GET and no POST', async () => {
  await fetchSuggestedQuestions(42, { modelConfigId: 'own-model' })
  expect(client.get).toHaveBeenCalledWith('/news/42/suggested-questions/', {
    params: { model_config_id: 'own-model' }, signal: undefined,
  })
  expect(client.post).not.toHaveBeenCalled()
})
it('requires per-call consent and submits an explicit generation POST', async () => {
  expect(() => fetchSuggestedQuestions(42, { force: true, modelConfigId: 'own-model' })).toThrow()
  expect(client.post).not.toHaveBeenCalled()
  await fetchSuggestedQuestions(42, { force: true, modelConfigId: 'own-model', consent: true })
  expect(client.post).toHaveBeenCalledWith('/news/42/suggested-questions/', {
    model_config_id: 'own-model', consent: true,
  }, { params: { force: 1 }, signal: undefined })
})
