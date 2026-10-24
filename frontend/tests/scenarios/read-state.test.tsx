import { afterAll, afterEach, beforeAll, expect, it } from 'vitest'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { setupServer } from 'msw/node'
import { AuthContext } from '@/context/AuthContext'
import { CapabilityProvider } from '@/context/CapabilitiesContext'
import ReadStateButton from '@/components/news-detail/ReadStateButton'
import { createScenarioBackend } from '@/mocks/backend'
import type { ScenarioBackend } from '@/mocks/backend'
import { scenarioHandlers } from '@/mocks/handlers'
import { MOCK_VIEWER } from '@/mocks/fixtures'

const server = setupServer()
const clients: QueryClient[] = []
let backend: ScenarioBackend | undefined
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); backend?.reset(); server.resetHandlers() })
afterAll(() => server.close())
function mount(scenario: string) {
  backend = createScenarioBackend(scenario, { origin: location.origin })
  server.resetHandlers(...scenarioHandlers(backend, location.origin))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } })
  clients.push(client)
  const user = { id: MOCK_VIEWER.id, username: MOCK_VIEWER.username, isSuperuser: false }
  render(<QueryClientProvider client={client}><CapabilityProvider><AuthContext.Provider value={{ user, loading: false,
    login: async () => user, register: async () => user, logout: async () => {}, refresh: async () => {} }}>
    <ReadStateButton newsId={910001} />
  </AuthContext.Provider></CapabilityProvider></QueryClientProvider>)
  return userEvent.setup()
}
it('saves through real component -> API -> MSW -> stateful backend', async () => {
  const user = mount('normal')
  await user.click(await screen.findByRole('button', { name: '标为已读' }))
  expect(await screen.findByRole('button', { name: '已读' })).toHaveAttribute('aria-pressed', 'true')
  expect(backend!.inspect().requests.some(row => row.method === 'PATCH' && row.status === 200)).toBe(true)
})
it('failed save does not claim optimistic success', async () => {
  const user = mount('read-save-error')
  await user.click(await screen.findByRole('button', { name: '标为已读' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('未能保存，请重试。')
  await waitFor(() => expect(screen.getByRole('button', { name: '标为已读' })).toBeEnabled())
  expect(screen.getByRole('button', { name: '标为已读' })).toHaveAttribute('aria-pressed', 'false')
})
it('409 re-reads the remote version and a second explicit action succeeds', async () => {
  const user = mount('read-conflict')
  await user.click(await screen.findByRole('button', { name: '标为已读' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('未能保存')
  const latest = await screen.findByRole('button', { name: '已读' })
  await user.click(latest)
  await waitFor(() => expect(screen.getByRole('button', { name: '标为已读' })).toHaveAttribute('aria-pressed', 'false'))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  expect(backend!.inspect().requests.filter(row => row.method === 'PATCH').map(row => row.status)).toEqual([409, 200])
})
it('read-only capability hides the personal write control', async () => {
  mount('read-only')
  await waitFor(() => expect(backend!.inspect().requests.some(row => row.path === '/api/capabilities/' && row.status === 200)).toBe(true))
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})
