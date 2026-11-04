import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/context/AuthContext'
import { queryClient } from '@/services/queryClient'
import { usePreferencesStore } from '@/stores/preferences'
import NewsList from '@/pages/NewsList'
import FeedWorkspace from '@/components/workspace/FeedWorkspace'
import { workspaceRequest } from '@/services/workspaceApi'
import { fetchCategories, fetchCsrfToken, fetchMe, fetchNews, fetchSources, loginUser, logoutUser, registerUser,
  fetchChannelSubscriptions, fetchChannelGroups, fetchChannelGroupRoots, fetchNewsPreferences } from '@/services/api'
import { CapabilitiesTestProvider } from '../helpers/capabilities'

vi.mock('@/services/workspaceApi', async (importOriginal) => ({
  ...await importOriginal(), workspaceRequest: vi.fn().mockImplementation(path => Promise.resolve(
    path.includes('reading-stats') ? { week: [], today: 0, total: 0, streak: 0, timezone: 'UTC' } : { stories: [] })),
}))

vi.mock('@/services/api', () => ({
  fetchChannelSubscriptions: vi.fn().mockResolvedValue([]),
  fetchChannelGroups: vi.fn().mockResolvedValue([]),
  fetchChannelGroupRoots: vi.fn().mockResolvedValue([]),
  fetchNewsPreferences: vi.fn().mockResolvedValue({ scope: 'all', group_id: null }),
  saveNewsPreferences: vi.fn().mockImplementation(value => Promise.resolve(value)),
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

function renderAuthenticatedList(path = '/') {
  return render(
    <QueryClientProvider client={queryClient}>
      <CapabilitiesTestProvider client={queryClient}>
        <AuthProvider>
          <MemoryRouter initialEntries={[path]}>
            <AuthControls />
            <FeedWorkspace><NewsList /></FeedWorkspace>
          </MemoryRouter>
        </AuthProvider>
      </CapabilitiesTestProvider>
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
  fetchChannelSubscriptions.mockResolvedValue([])
  fetchChannelGroups.mockResolvedValue([])
  fetchChannelGroupRoots.mockResolvedValue([])
  fetchNewsPreferences.mockResolvedValue({ scope: 'all', group_id: null })
  fetchNews.mockImplementation(() => fetchNews.mock.calls.length === 1
    ? Promise.resolve(page('Private story for account one'))
    : nextListResponse.promise)
})

afterEach(() => queryClient.clear())

describe('NewsList authentication transitions', () => {
  it('loads explicit all-news without waiting for personal configuration or preferences', async () => {
    const pending = deferred().promise
    fetchChannelSubscriptions.mockReturnValue(pending)
    fetchChannelGroups.mockReturnValue(pending)
    fetchChannelGroupRoots.mockReturnValue(pending)
    fetchNewsPreferences.mockReturnValue(pending)
    renderAuthenticatedList('/?scope=all')
    expect(await screen.findByRole('heading', { name: 'Private story for account one' })).toBeInTheDocument()
  })

  it('uses the saved all-news scope without waiting for sidebar groups', async () => {
    fetchChannelGroups.mockReturnValue(deferred().promise)
    renderAuthenticatedList()
    expect(await screen.findByRole('heading', { name: 'Private story for account one' })).toBeInTheDocument()
  })

  it('keeps a private group closed until its membership has loaded', async () => {
    fetchChannelGroups.mockReturnValue(deferred().promise)
    renderAuthenticatedList('/?scope=group&group_id=7')
    await waitFor(() => expect(screen.getByTestId('viewer')).toHaveTextContent('1'))
    expect(fetchNews).not.toHaveBeenCalled()
  })

  it('starts filter statistics after the initial news request settles', async () => {
    fetchNews.mockReturnValue(nextListResponse.promise)
    renderAuthenticatedList('/?scope=all')
    await waitFor(() => expect(fetchNews).toHaveBeenCalledOnce())
    expect(fetchCategories).not.toHaveBeenCalled()
    expect(fetchSources).not.toHaveBeenCalled()
    expect(workspaceRequest).not.toHaveBeenCalled()
    await act(async () => { nextListResponse.resolve(page('News before statistics')) })
    await waitFor(() => expect(fetchSources).toHaveBeenCalledOnce())
    expect(fetchCategories).toHaveBeenCalledOnce()
    await waitFor(() => expect(workspaceRequest).toHaveBeenCalledWith('/smart-channels/dashboard/', expect.anything()))
    expect(screen.getByRole('heading', { name: 'News before statistics' })).toBeInTheDocument()
  })

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
