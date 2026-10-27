import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import WorkspaceShell from '@/components/workspace/WorkspaceShell'

vi.mock('@/context/AuthContext', () => ({ useAuth: () => ({ user: { id: 1 }, loading: false }) }))
vi.mock('@/context/CapabilitiesContext', () => ({ useCapability: () => ({ enabled: true }) }))
vi.mock('@/services/channelQueries', () => ({
  useChannelConfig: () => ({ enabled: true, error: false, retry: vi.fn(),
    roots: { data: [{ id: 4, name: '技术', version: 1, child_count: 1, created_at: '2026-01-01', updated_at: '2026-01-01' }] },
    groups: { data: [
      { id: 8, root_id: 4, name: '前端', source_ids: [2], version: 1, created_at: '2026-01-01', updated_at: '2026-01-01' },
      { id: 9, root_id: null, name: '🌐 科技媒体与开源生态深度阅读', source_ids: [3], version: 1 },
      { id: 10, root_id: null, name: 'OPML 导入 / 用户手工原名', source_ids: [], version: 1 },
    ] },
  }),
}))

afterEach(cleanup)

it('uses roots only as disclosure controls and exposes child reading links with full paths', () => {
  render(<MemoryRouter><WorkspaceShell><main>Content</main></WorkspaceShell></MemoryRouter>)
  const root = screen.getByRole('button', { name: '折叠 技术' })
  expect(root).toHaveAttribute('aria-expanded', 'true')
  const direct = screen.getByRole('link', { name: /🌐 科技媒体与开源生态深度阅读/ })
  expect(direct).toHaveAttribute('href', '/?scope=group&group_id=9')
  expect(direct).not.toHaveTextContent('OPML 导入 / 🌐')
  expect(screen.getByRole('link', { name: /OPML 导入 \/ 用户手工原名/ })).toBeInTheDocument()
  const child = screen.getByRole('link', { name: /技术 \/ 前端/ })
  expect(child).toHaveAttribute('href', '/?scope=group&group_id=8')
  expect(screen.queryByRole('link', { name: '技术' })).toBeNull()
  fireEvent.click(root)
  expect(screen.queryByRole('link', { name: /技术 \/ 前端/ })).toBeNull()
  expect(screen.getByRole('button', { name: '展开 技术' })).toHaveAttribute('aria-expanded', 'false')
})
