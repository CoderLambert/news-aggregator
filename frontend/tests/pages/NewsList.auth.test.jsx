import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/context/AuthContext'
import { queryClient } from '@/services/queryClient'
import { usePreferencesStore } from '@/stores/preferences'
import NewsList from '@/pages/NewsList'
import { fetchCategories, fetchCsrfToken, fetchMe, fetchNews, fetchSources, loginUser, logoutUser, registerUser } from '@/services/api'

vi.mock('@/services/api', () => ({
  fetchNews: vi.fn(),
  fetchCategories: vi.fn(),
  fetchSources: vi.fn(),
  fetchCsrfToken: vi.fn(),
  fetchMe: vi.fn(),
  loginUser: vi.fn(),
  logoutUser: vi.fn(),
  registerUser: vi.fn(),
}))

function story(title) {
  return {
    id: 21, title, content: 'A short article summary', title_zh: '', content_zh: '', author: null,
    publish_time: '2026-10-06T09:00:00Z', source: 8, source_name: 'Example source', source_type: 'news',
    source_language: 'en', category: 2, category_name: 'Technology', url: 'https://example.com/story',
    cover_image: null, created_at: '2026-10-06T09:00:00Z', related_to: null, translation_status: '',
    translation_error: '', translation_retry_count: 0, full_content_fetch_status: '',
    full_content_fetch_error: '', full_content_fetch_provider: '', full_content_quality_score: null,
    full_content_retry_count: 0, last_full_content_attempt: null,
  }
}

function page(title) {
  return { count: 1, next: null, previous: null, results: [story(title)] }
}

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

function AuthControls() {
  const { user, login, logout } = useAuth()
  return (
    <div>
      <output data-testid="viewer">{user?.id ?? 'anonymous'}</output>
      <button type="button" onClick={() => void login('reader-two', 'secret')}>Switch account</button>
      <button type="button" onClick={() => void logout()}>Log out</button>
    </div>
  )
}

function renderAuthenticatedList() {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/']}>
          <AuthControls />
          <NewsList />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

let nextListResponse

beforeEach(() => {
  queryClient.clear()
  vi.clearAllMocks()
  localStorage.removeItem('news-aggregator-filters')
  usePreferencesStore.setState({ lang: 'zh' })
  nextListResponse = deferred()
  fetchMe.mockResolvedValue({ id: 1, username: 'reader-one' })
  fetchCsrfToken.mockResolvedValue({})
  loginUser.mockResolvedValue({ id: 2, username: 'reader-two' })
  logoutUser.mockResolvedValue({})
  registerUser.mockResolvedValue({ id: 3, username: 'reader-three' })
  fetchCategories.mockResolvedValue([])
  fetchSources.mockResolvedValue([])
  fetchNews.mockImplementation(() => fetchNews.mock.calls.length === 1
    ? Promise.resolve(page('Private story for account one'))
    : nextListResponse.promise)
})

afterEach(() => queryClient.clear())

describe('NewsList authentication transitions', () => {
  it('hides the previous user list while the anonymous list request is pending after logout', async () => {
    renderAuthenticatedList()
    expect(await screen.findByRole('heading', { name: 'Private story for account one' })).toBeInTheDocument()

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Log out' })) })
    await waitFor(() => expect(fetchNews).toHaveBeenCalledTimes(2))
    expect(screen.getByTestId('viewer')).toHaveTextContent('anonymous')
    expect(screen.queryByRole('heading', { name: 'Private story for account one' })).not.toBeInTheDocument()

    await act(async () => { nextListResponse.resolve(page('Anonymous story')) })
    expect(await screen.findByRole('heading', { name: 'Anonymous story' })).toBeInTheDocument()
  })

  it('hides the previous account list while the new account request is pending', async () => {
    renderAuthenticatedList()
    expect(await screen.findByRole('heading', { name: 'Private story for account one' })).toBeInTheDocument()

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Switch account' })) })
    await waitFor(() => expect(fetchNews).toHaveBeenCalledTimes(2))
    expect(screen.getByTestId('viewer')).toHaveTextContent('2')
    expect(screen.queryByRole('heading', { name: 'Private story for account one' })).not.toBeInTheDocument()

    await act(async () => { nextListResponse.resolve(page('Private story for account two')) })
    expect(await screen.findByRole('heading', { name: 'Private story for account two' })).toBeInTheDocument()
  })
})
