import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import ReviewRecommendationsDialog from '@/features/rss/ReviewRecommendationsDialog'
import { decideRecommendation, type Recommendation } from '@/services/rssReviewApi'

vi.mock('@/services/rssReviewApi', async original => ({
  ...await original<typeof import('@/services/rssReviewApi')>(), decideRecommendation: vi.fn(),
}))
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  vi.clearAllMocks(); vi.mocked(decideRecommendation).mockResolvedValue({})
})
it('requires confirmation and a rejection reason, sending the captured version per item', async () => {
  const client = new QueryClient()
  const rows = [{ candidate_id: 'a', version: 3, name: 'A', category_name: '科技', language: 'en', feed_url: 'https://example.com/rss', scope_description: '范围' }] as Recommendation[]
  const view = render(<QueryClientProvider client={client}><ReviewRecommendationsDialog viewer={17} rows={rows} onClose={vi.fn()} /></QueryClientProvider>)
  expect(screen.getByRole('button', { name: '确认批量审核' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('审核决定'), { target: { value: 'reject' } })
  fireEvent.click(screen.getByRole('checkbox'))
  expect(screen.getByRole('button', { name: '确认批量审核' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('审核说明（驳回时必填）'), { target: { value: '来源待核验' } })
  fireEvent.click(screen.getByRole('button', { name: '确认批量审核' }))
  await screen.findByText('已完成 1 / 1 项审核')
  expect(decideRecommendation).toHaveBeenCalledWith(17, 'a', { action: 'reject', expected_version: 3, reason: '来源待核验' }, expect.any(String))
  view.unmount(); client.clear()
})
