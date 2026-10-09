import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ fetchCapabilities: vi.fn() }))
vi.mock('@/services/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/api')>()),
  fetchCapabilities: mocks.fetchCapabilities,
}))

import { CapabilityProvider, FAIL_CLOSED_CAPABILITIES, useCapabilities } from '@/context/CapabilitiesContext'
import * as api from '@/services/api'
import { readOnlyCapabilities } from '../helpers/capabilities'

function CapabilitiesProbe() {
  const { capabilities, loading, failed } = useCapabilities()
  return (
    <output data-testid="capabilities">
      {JSON.stringify({ accounts: capabilities.features.accounts, news: capabilities.features.news, loading, failed })}
    </output>
  )
}

function renderProvider() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CapabilityProvider><CapabilitiesProbe /></CapabilityProvider>
    </QueryClientProvider>,
  )
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
})
