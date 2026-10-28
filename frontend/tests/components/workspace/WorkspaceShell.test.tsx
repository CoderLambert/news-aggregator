import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import WorkspaceShell from '@/components/workspace/WorkspaceShell'

vi.mock('@/context/AuthContext', () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }))
vi.mock('@/context/CapabilitiesContext', () => ({ useCapability: () => ({ enabled: true }) }))
vi.mock('@/components/workspace/WorkspaceModal', () => ({ default: ({ children, title }: { children: React.ReactNode; title: string }) => <div role="dialog" aria-label={title}>{children}</div> }))
vi.mock('@/services/channelQueries', () => ({
  useChannelConfig: () => ({ enabled: true, error: false, retry: vi.fn(),
    roots: { data: [
      { id: 4, name: '技术', version: 1, child_count: 4, created_at: '2026-01-01', updated_at: '2026-01-01' },
      { id: 5, name: '空父文件夹', version: 1, child_count: 1, created_at: '2026-01-01', updated_at: '2026-01-01' },
      { id: 6, name: '没有子组', version: 1, child_count: 0, created_at: '2026-01-01', updated_at: '2026-01-01' },
    ] },
    groups: { data: [
      { id: 8, root_id: 4, name: '前端', source_ids: [2], version: 1, created_at: '2026-01-01', updated_at: '2026-01-01' },
      { id: 9, root_id: null, name: '🌐 科技媒体与开源生态深度阅读', source_ids: [3], version: 1 },
      { id: 10, root_id: null, name: 'OPML 导入 / 用户手工原名', source_ids: [4], version: 1 },
      { id: 11, root_id: 4, name: 'AI / 大模型', source_ids: [5], version: 1 },
      { id: 12, root_id: 4, name: 'DevOps / 云原生', source_ids: [6], version: 1 },
      { id: 13, root_id: 4, name: '空子组', source_ids: [], version: 1 },
      { id: 14, root_id: 5, name: '空父级的子组', source_ids: [], version: 1 },
      { id: 15, root_id: null, name: '空直接组', source_ids: [], version: 1 },
    ] },
  }),
}))

afterEach(cleanup)

it('uses folder disclosures and child names without repeating the parent or splitting slashes', () => {
  render(<MemoryRouter><WorkspaceShell><main>Content</main></WorkspaceShell></MemoryRouter>)
  const root = screen.getByRole('button', { name: '折叠 技术' })
  expect(root).toHaveAttribute('aria-expanded', 'true')
  const direct = screen.getByRole('link', { name: /🌐 科技媒体与开源生态深度阅读/ })
  expect(direct).toHaveAttribute('href', '/?scope=group&group_id=9')
  expect(direct).not.toHaveTextContent('OPML 导入 / 🌐')
  expect(screen.getByRole('link', { name: /OPML 导入 \/ 用户手工原名/ })).toBeInTheDocument()
  const child = screen.getByRole('link', { name: /前端/ })
  expect(child).not.toHaveTextContent('技术 /')
  expect(screen.getByRole('link', { name: /AI \/ 大模型/ })).toHaveAttribute('href', '/?scope=group&group_id=11')
  expect(screen.getByRole('link', { name: /DevOps \/ 云原生/ })).toHaveAttribute('href', '/?scope=group&group_id=12')
  expect(child).toHaveAttribute('href', '/?scope=group&group_id=8')
  expect(screen.queryByRole('link', { name: '技术' })).toBeNull()
  fireEvent.click(root)
  expect(screen.queryByRole('link', { name: /前端/ })).toBeNull()
  const expand = screen.getByRole('button', { name: '展开 技术' })
  expect(expand).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(expand)
  expect(screen.getByRole('link', { name: /前端/ })).toBeInTheDocument()
})

it('hides only zero-channel groups and their empty parents while preserving navigation actions', () => {
  render(<MemoryRouter><WorkspaceShell><main>Content</main></WorkspaceShell></MemoryRouter>)
  for (const name of ['空直接组', '空子组', '空父级的子组', '空父文件夹', '没有子组']) {
    expect(screen.queryByText(name)).not.toBeInTheDocument()
  }
  for (const name of ['全部资讯', '未加入分组', '新建分组']) {
    expect(screen.getByRole('link', { name })).toBeInTheDocument()
  }
  // No article-count information is needed to keep a subscribed folder visible.
  expect(screen.getByRole('link', { name: /前端/ })).toBeInTheDocument()
})

it('uses the same nonempty folder navigation in the mobile drawer', () => {
  render(<MemoryRouter><WorkspaceShell><main>Content</main></WorkspaceShell></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '工作区导航' }))
  const drawer = within(screen.getByRole('dialog', { name: '工作区导航' }))
  expect(drawer.getByRole('link', { name: /AI \/ 大模型/ })).toBeInTheDocument()
  expect(drawer.queryByText('空直接组')).not.toBeInTheDocument()
  expect(drawer.queryByText('空父文件夹')).not.toBeInTheDocument()
  fireEvent.click(drawer.getByRole('link', { name: /前端/ }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
