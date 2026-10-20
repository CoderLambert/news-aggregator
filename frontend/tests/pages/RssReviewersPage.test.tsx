import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import RssReviewersPage from '@/pages/admin/RssReviewersPage'
vi.mock('@/context/AuthContext', () => ({ useAuth: () => ({ user: { id: 17, isSuperuser: true } }) }))
vi.mock('@/services/workspaceApi', () => ({ workspaceRequest: vi.fn().mockResolvedValue({ results: [] }), workspaceError: () => '请求失败' }))
afterEach(cleanup)
it('requires an exact account lookup before granting reviewer access', async () => {
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><RssReviewersPage /></MemoryRouter></QueryClientProvider>)
  expect(screen.getByLabelText('准确用户名')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '确认授予审核权限' })).not.toBeInTheDocument()
  expect(await screen.findByText('暂无审核员授权。')).toBeInTheDocument()
})
