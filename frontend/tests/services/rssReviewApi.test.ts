import { expect, it, vi } from 'vitest'
import { fetchAdditions } from '@/services/rssReviewApi'
import { workspaceRequest } from '@/services/workspaceApi'
vi.mock('@/services/workspaceApi', () => ({ workspaceRequest: vi.fn() }))
it('rejects malformed addition versions rather than enabling actions', async () => {
  vi.mocked(workspaceRequest).mockResolvedValue({ results: [{ operation_id: 'op', state: 'unknown', version: 0, actions: ['retry'] }], count: 1, page: 1, page_size: 25 })
  await expect(fetchAdditions('status=all')).rejects.toThrow()
})
