import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/pages/NewsList', () => ({ default: () => <div>News List Page</div> }))
vi.mock('@/pages/NewsDetail', () => ({ default: () => <div>News Detail Page</div> }))
vi.mock('@/pages/FavoritesPage', () => ({ default: () => <div>Favorites Page</div> }))
vi.mock('@/components/mascot/MascotPreview', () => ({ default: () => <div>Mascot Preview</div> }))
vi.mock('@/pages/ProviderComparisons', () => ({ default: () => <div>Provider Comparisons Route Page</div> }))
vi.mock('@/components/Header', () => ({ default: () => <div>Header</div> }))
vi.mock('@/context/AuthContext', () => ({
  AuthProvider: ({ children }) => <>{children}</>,
  useAuth: () => ({ user: null, loading: false, logout: vi.fn() }),
}))
vi.mock('@/context/SpeechPlayerProvider', () => ({
  SpeechPlayerProvider: ({ children }) => <>{children}</>,
}))
vi.mock('@/context/SpeechPlayerContext', () => ({
  useSpeechPlayer: () => ({ status: 'idle' }),
  useSpeechPlayerState: () => ({ status: 'idle', progress: 0, currentTime: 0, duration: 0, rate: 1, voice: 'yunyang', scope: 'full', title: '', newsId: null, displayMode: 'zh' }),
  useSpeechPlayerActivity: () => false,
  useSpeechPlayerActions: () => ({ speak: vi.fn(), pause: vi.fn(), resume: vi.fn(), stop: vi.fn(), seek: vi.fn(), setRate: vi.fn(), setVoice: vi.fn(), setScope: vi.fn() }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    BrowserRouter: ({ children }) => (
      <MemoryRouter initialEntries={["/provider-comparisons"]}>{children}</MemoryRouter>
    ),
  }
})

import App from '@/App'

describe('App routes', () => {
  it('renders provider comparisons on /provider-comparisons', async () => {
    render(<App />)

    expect(await screen.findByText('Provider Comparisons Route Page')).toBeInTheDocument()
  })
})
