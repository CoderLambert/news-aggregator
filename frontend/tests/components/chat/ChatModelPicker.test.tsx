import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ChatModelPicker from '@/components/chat/ChatModelPicker'
import * as api from '@/services/aiConnectionsApi'

vi.mock('@/services/aiConnectionsApi', async original => ({
  ...await original<typeof import('@/services/aiConnectionsApi')>(),
  listAIConnections: vi.fn(), listAIModels: vi.fn(), probeAIModel: vi.fn(),
}))
const connection: api.AIConnection = {
  id: '11111111-1111-4111-8111-111111111111', provider_id: 'deepseek', provider_name: 'DeepSeek',
  display_name: 'My BYOK', endpoint_profile: 'deepseek_default', endpoint_profile_version: 1,
  region_name: 'trusted', key_saved: true, masked_key: '••••', is_enabled: true,
  credential_epoch: 1, revision: 1, verification_status: 'not_tested',
  updated_at: '2026-10-18T00:00:00Z',
}
const good: api.AIModel = {
  id: '22222222-2222-4222-8222-222222222222', connection_id: connection.id, model_id: 'deepseek-chat',
  display_name: 'Verified model', catalog_model_id: 'deepseek-chat', config_revision: 1,
  has_trusted_route: true, context_window_tokens: null,
  capabilities: { text: 'supported', tools: 'unknown' },
  updated_at: '2026-10-18T00:00:00Z',
}
const unverified: api.AIModel = {
  ...good, id: '33333333-3333-4333-8333-333333333333', display_name: 'Not verified',
  capabilities: { text: 'unknown', tools: 'unknown' },
}
function Harness({ viewer = 7 }: { viewer?: number }) {
  const [choice, setChoice] = useState<{ viewer: number; id: string | null; consent: boolean } | null>(null)
  const selected = choice?.viewer === viewer ? choice.id : null
  const consent = choice?.viewer === viewer && choice.consent === true
  return <MemoryRouter>
    <ChatModelPicker viewer={viewer} selected={selected} consent={consent} disabled={false}
      onSelect={id => setChoice({ viewer, id, consent: false })}
      onConsent={confirmed => setChoice({ viewer, id: selected, consent: confirmed })} />
  </MemoryRouter>
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.listAIConnections).mockReset().mockResolvedValue([connection])
  vi.mocked(api.listAIModels).mockReset().mockResolvedValue([good, unverified])
})
afterEach(cleanup)
describe('T04 owner-only per-turn model picker', () => {
  it('loads GET metadata only, never picks a billable model or probes automatically', async () => {
    render(<Harness />)
    expect((await screen.findByRole('combobox', { name: '本轮聊天模型' }))).toHaveValue('')
    await screen.findByRole('option', { name: 'My BYOK · Verified model' })
    expect(screen.queryByRole('option', { name: /Not verified/ })).not.toBeInTheDocument()
    expect(api.listAIConnections).toHaveBeenCalledOnce()
    expect(api.listAIModels).toHaveBeenCalledWith(connection, expect.any(AbortSignal))
    expect(api.probeAIModel).not.toHaveBeenCalled()
    expect(screen.queryByRole('checkbox', { name: /产生服务商费用/ })).not.toBeInTheDocument()
  })
  it('requires explicit consent and clears it upon model change', async () => {
    render(<Harness />)
    await screen.findByRole('option', { name: 'My BYOK · Verified model' })
    fireEvent.change(screen.getByRole('combobox', { name: '本轮聊天模型' }), { target: { value: good.id } })
    const consent = screen.getByRole('checkbox', { name: /产生服务商费用/ })
    expect(consent).not.toBeChecked()
    fireEvent.click(consent)
    expect(consent).toBeChecked()
    fireEvent.change(screen.getByRole('combobox', { name: '本轮聊天模型' }), { target: { value: '' } })
    expect(screen.queryByRole('checkbox', { name: /产生服务商费用/ })).not.toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: '本轮聊天模型' }), { target: { value: good.id } })
    expect(screen.getByRole('checkbox', { name: /产生服务商费用/ })).not.toBeChecked()
  })
  it('rejects late response from previous viewer and never reuses that choice', async () => {
    let finish!: (value: api.AIConnection[]) => void
    vi.mocked(api.listAIConnections).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const view = render(<Harness viewer={7} />)
    await waitFor(() => expect(api.listAIConnections).toHaveBeenCalledOnce())
    const originalSignal = vi.mocked(api.listAIConnections).mock.calls[0][0]
    view.rerender(<Harness viewer={8} />)
    await screen.findByRole('option', { name: 'My BYOK · Verified model' })
    expect(originalSignal?.aborted).toBe(true)
    await act(async () => finish([connection]))
    expect(screen.getByRole('combobox', { name: '本轮聊天模型' })).toHaveValue('')
  })
  it('keeps previous viewer models unavailable when GET fails', async () => {
    vi.mocked(api.listAIConnections).mockRejectedValue(new api.ConnectionRequestError(0))
    render(<Harness />)
    await screen.findByRole('alert')
    expect(screen.getByRole('combobox', { name: '本轮聊天模型' })).toBeDisabled()
  })
})
