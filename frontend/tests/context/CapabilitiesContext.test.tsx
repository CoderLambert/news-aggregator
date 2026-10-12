import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ fetchCapabilities: vi.fn() }))
vi.mock('@/services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/api')>()),
  fetchCapabilities: mocks.fetchCapabilities,
}))

import { CAPABILITIES_QUERY_KEY, CapabilityProvider, FAIL_CLOSED_CAPABILITIES, useCapabilities } from '@/context/CapabilitiesContext'
import * as api from '@/services/api'
import { fullCapabilities, readOnlyCapabilities } from '../helpers/capabilities'

function CapabilitiesProbe() {
  const { capabilities, loading, failed } = useCapabilities()
  return (
    <output data-testid="capabilities">
      {JSON.stringify({ capabilities, loading, failed })}
    </output>
  )
}

function renderProvider(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const view = render(
    <QueryClientProvider client={client}>
      <CapabilityProvider><CapabilitiesProbe /></CapabilityProvider>
    </QueryClientProvider>,
  )
  return { client, ...view }
}

function readState() {
  return JSON.parse(screen.getByTestId('capabilities').textContent ?? '{}') as {
    capabilities: ReturnType<typeof fullCapabilities>
    loading: boolean
    failed: boolean
  }
}

describe('CapabilityProvider fail-closed behavior', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => vi.clearAllMocks())

  it('loads a valid capability snapshot once', async () => {
    mocks.fetchCapabilities.mockResolvedValue(readOnlyCapabilities())
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('capabilities')).toHaveTextContent('"loading":false'))
    expect(screen.getByTestId('capabilities')).toHaveTextContent('"accounts":{"enabled":false,"reason":"public_read_only"}')
    expect(api.fetchCapabilities).toHaveBeenCalledOnce()
  })

  it('keeps public news and keyword search usable after request failure', async () => {
    mocks.fetchCapabilities.mockRejectedValue(new Error('offline'))
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('capabilities')).toHaveTextContent('"failed":true'))
    expect(FAIL_CLOSED_CAPABILITIES.features.news).toEqual({ enabled: true, reason: null })
    expect(FAIL_CLOSED_CAPABILITIES.features.keyword_search).toEqual({ enabled: true, reason: null })
    expect(FAIL_CLOSED_CAPABILITIES.features.semantic_search).toEqual({ enabled: false, reason: 'capabilities_unavailable' })
    expect(api.fetchCapabilities).toHaveBeenCalledOnce()
  })

  it('uses the safe fallback when the provider is missing', () => {
    render(<CapabilitiesProbe />)
    expect(screen.getByTestId('capabilities')).toHaveTextContent('"accounts":{"enabled":false,"reason":"capabilities_unavailable"}')
    expect(screen.getByTestId('capabilities')).toHaveTextContent('"loading":false')
  })

  it.each([
    ['a rejected refetch', () => { throw new Error('offline') }],
    ['an invalid schema refetch', () => api.parseCapabilities({ ...fullCapabilities(), features: {} })],
  ])('fails closed after %s while stale full capabilities remain cached, then recovers', async (_label, rejectRefetch) => {
    const staleFull = fullCapabilities()
    mocks.fetchCapabilities.mockResolvedValueOnce(staleFull)
    const { client } = renderProvider()

    await waitFor(() => expect(readState().capabilities.features.accounts.enabled).toBe(true))
    expect(client.getQueryData(CAPABILITIES_QUERY_KEY)).toEqual(staleFull)

    mocks.fetchCapabilities.mockImplementationOnce(rejectRefetch)
    await client.refetchQueries({ queryKey: CAPABILITIES_QUERY_KEY, exact: true })

    await waitFor(() => expect(readState().failed).toBe(true))
    expect(client.getQueryState(CAPABILITIES_QUERY_KEY)?.status).toBe('error')
    expect(client.getQueryData(CAPABILITIES_QUERY_KEY)).toEqual(staleFull)

    const failedState = readState()
    expect(failedState.loading).toBe(false)
    expect(failedState.capabilities.features.news).toEqual({ enabled: true, reason: null })
    expect(failedState.capabilities.features.keyword_search).toEqual({ enabled: true, reason: null })
    for (const [name, feature] of Object.entries(failedState.capabilities.features)) {
      if (name === 'news' || name === 'keyword_search') continue
      expect(feature).toEqual({ enabled: false, reason: 'capabilities_unavailable' })
    }
    expect(api.fetchCapabilities).toHaveBeenCalledTimes(2)

    const recoveredFull = fullCapabilities()
    mocks.fetchCapabilities.mockResolvedValueOnce(recoveredFull)
    await client.refetchQueries({ queryKey: CAPABILITIES_QUERY_KEY, exact: true })

    await waitFor(() => expect(readState().failed).toBe(false))
    expect(readState().capabilities).toEqual(recoveredFull)
    expect(client.getQueryData(CAPABILITIES_QUERY_KEY)).toEqual(recoveredFull)
    expect(api.fetchCapabilities).toHaveBeenCalledTimes(3)
  })
})
