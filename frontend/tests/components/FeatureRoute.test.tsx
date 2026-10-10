import { useEffect } from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import FeatureRoute from '@/components/FeatureRoute'
import { AuthContext } from '@/context/AuthContext'
import { CapabilitiesTestProvider } from '../helpers/capabilities'

const privateRead = vi.fn()

function PrivateComparisonsContent() {
  useEffect(() => {
    privateRead()
  }, [])
  return <div>Private comparisons</div>
}

describe('FeatureRoute superuser guard', () => {
  it('does not mount private children or trigger their API reads for an ordinary account', () => {
    privateRead.mockClear()
    render(
      <CapabilitiesTestProvider>
        <AuthContext.Provider value={{
          user: { id: 42, username: 'ordinary-reader', isSuperuser: false },
          loading: false,
          login: vi.fn(),
          register: vi.fn(),
          logout: vi.fn(),
          refresh: vi.fn(),
        }}>
          <MemoryRouter>
            <FeatureRoute feature="provider_comparisons" requireSuperuser>
              <PrivateComparisonsContent />
            </FeatureRoute>
          </MemoryRouter>
        </AuthContext.Provider>
      </CapabilitiesTestProvider>,
    )

    expect(screen.getByRole('status')).toHaveTextContent('此页面仅供管理员使用。')
    expect(screen.queryByText('Private comparisons')).not.toBeInTheDocument()
    expect(privateRead).not.toHaveBeenCalled()
  })
})
