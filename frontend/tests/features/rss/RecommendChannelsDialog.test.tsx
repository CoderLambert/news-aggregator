import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import RecommendChannelsDialog from '@/features/rss/RecommendChannelsDialog'
import { canRecommendChannel } from '@/features/rss/recommendationEligibility'
import { fetchReviewCategories, submitRecommendation } from '@/services/rssReviewApi'
import type { ChannelProfile } from '@/services/workspaceApi'

vi.mock('@/services/rssReviewApi', async original => ({
  ...await original<typeof import('@/services/rssReviewApi')>(), fetchReviewCategories: vi.fn(), submitRecommendation: vi.fn(),
}))
const sources = [1, 2].map(id => ({ id, name: `Source ${id}`, language: 'en', publication: 'personal',
  collection_owner: 'miniflux', subscription_status: 'active' }) as ChannelProfile)
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  vi.clearAllMocks()
  vi.mocked(fetchReviewCategories).mockResolvedValue([{ id: 1, name: '科技' }])
  vi.mocked(submitRecommendation).mockResolvedValue({ state: 'pending' } as Awaited<ReturnType<typeof submitRecommendation>>)
})
it('requires category and explicit consent before recommending, and displays each result', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(<QueryClientProvider client={client}><MemoryRouter><RecommendChannelsDialog viewer={11} sources={sources} onClose={vi.fn()} /></MemoryRouter></QueryClientProvider>)
  await screen.findAllByRole('option', { name: '科技' })
  expect(screen.getByRole('button', { name: '提交推荐' })).toBeDisabled()
  for (const source of sources) fireEvent.change(screen.getByLabelText(`分类 ${source.name}`), { target: { value: '1' } })
  expect(submitRecommendation).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: '提交推荐' })).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: '提交推荐' }))
  await screen.findByRole('link', { name: '查看我的推荐' })
  expect(submitRecommendation).toHaveBeenCalledTimes(2)
  expect(submitRecommendation).toHaveBeenNthCalledWith(1, 11, expect.objectContaining({ source_id: 1, confirm_public_scope: true, category_id: 1 }), expect.any(String))
  expect(screen.getAllByText('待审核')).toHaveLength(2)
  await waitFor(() => expect(screen.getByText('已完成 2 / 2 个推荐')).toBeInTheDocument())
  view.unmount(); client.clear()
})
it('does not offer recommendations for public, disconnected or unknown-scope channels', () => {
  expect(canRecommendChannel(sources[0])).toBe(true)
  expect(canRecommendChannel({ ...sources[0], publication: 'public' })).toBe(false)
  expect(canRecommendChannel({ ...sources[0], subscription_status: 'inactive' })).toBe(false)
  expect(canRecommendChannel({ ...sources[0], publication: undefined })).toBe(false)
})
