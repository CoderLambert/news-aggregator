import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DiscoverDialog from '@/features/rss/DiscoverDialog'
import { workspaceRequest } from '@/services/workspaceApi'

vi.mock('@/services/workspaceApi', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/workspaceApi')>(), workspaceRequest: vi.fn(),
}))
const request = vi.mocked(workspaceRequest)
const response = {
  results: [], next_cursor: null, categories: [{ id: 'engineering', name: '编程与技术' }],
  sections: [{ key: 'tech', label: '技术', count: 40, groups: [
    { key: 'ai-llm', label: 'AI / 大模型', count: 20 },
    { key: 'frontend', label: '前端开发', count: 20 },
  ] }],
}
beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  request.mockResolvedValue(response)
})
afterEach(cleanup)

function setup(viewer = 12) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const view = (id: number) => <QueryClientProvider client={client}>
    <DiscoverDialog viewer={id} roots={[]} groups={[]} onClose={vi.fn()} onDone={vi.fn()} />
  </QueryClientProvider>
  const result = render(view(viewer))
  return { ...result, changeViewer: (id: number) => result.rerender(view(id)) }
}

it('combines section, group, language and keyword via the existing read-only endpoint', async () => {
  setup()
  fireEvent.click(await screen.findByRole('button', { name: '技术 40' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/rss/directory/?q=&section=tech', expect.anything()))
  fireEvent.change(screen.getByLabelText('默认 RSS 二级分组'), { target: { value: 'frontend' } })
  fireEvent.change(screen.getByLabelText('订阅源语言'), { target: { value: 'en' } })
  fireEvent.change(screen.getByLabelText('搜索订阅源、网站或 RSS 地址'), { target: { value: 'React' } })
  fireEvent.click(screen.getByRole('button', { name: '查找订阅' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith(
    '/rss/directory/?q=React&section=tech&group=frontend&language=en', expect.anything()))
  expect(request.mock.calls.every(([path]) => path.startsWith('/rss/directory/'))).toBe(true)
  expect(screen.getByRole('button', { name: '确认订阅' })).toBeDisabled()
})

it('resets filters on account switch without writing another account groups', async () => {
  const { changeViewer } = setup()
  fireEvent.click(await screen.findByRole('button', { name: '技术 40' }))
  changeViewer(13)
  expect(await screen.findByRole('button', { name: '全部栏目' })).toHaveAttribute('aria-pressed', 'true')
  expect(request.mock.calls.some(([path]) => path.startsWith('/me/'))).toBe(false)
})

it('keeps older directory responses functional without fabricated taxonomy', async () => {
  request.mockResolvedValue({ results: [], next_cursor: null })
  setup()
  expect(await screen.findByText('没有可添加的匹配渠道，已订阅渠道已隐藏。')).toBeInTheDocument()
  expect(screen.queryByRole('group', { name: '默认 RSS 一级栏目' })).not.toBeInTheDocument()
})
