import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AuthModal from '@/components/AuthModal'
import { AuthProvider, useAuth } from '@/context/AuthContext'
import * as api from '@/services/api'
import { CapabilitiesTestProvider, fullCapabilities, readOnlyCapabilities } from '../helpers/capabilities'

function AuthProbe() {
  const { user, loading, login, register, logout } = useAuth()
  return (
    <div>
      <output data-testid="auth-state">{JSON.stringify({ id: user?.id ?? null, loading })}</output>
      <button type="button" onClick={() => void login('reader-two', 'password').catch(() => undefined)}>登录第二个账号</button>
      <button type="button" onClick={() => void register('reader-three', 'password').catch(() => undefined)}>尝试注册</button>
      <button type="button" onClick={() => void logout()}>退出</button>
    </div>
  )
}

function renderAuth(value = fullCapabilities(), extra?: ReactNode) {
  return render(
    <CapabilitiesTestProvider value={value}>
      <AuthProvider>
        <AuthProbe />
        {extra}
      </AuthProvider>
    </CapabilitiesTestProvider>,
  )
}

describe('AuthProvider capability gates', () => {
  beforeEach(() => {
    vi.spyOn(api, 'fetchMe').mockResolvedValue({ id: 1, username: 'reader-one' })
    vi.spyOn(api, 'fetchCsrfToken').mockResolvedValue('test-csrf-token')
    vi.spyOn(api, 'loginUser').mockResolvedValue({ id: 2, username: 'reader-two' })
    vi.spyOn(api, 'registerUser').mockResolvedValue({ id: 3, username: 'reader-three' })
    vi.spyOn(api, 'logoutUser').mockResolvedValue({})
  })
  afterEach(() => vi.restoreAllMocks())

  it('does not request the session or show account controls when accounts are disabled', async () => {
    renderAuth(readOnlyCapabilities(), <AuthModal onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByTestId('auth-state')).toHaveTextContent('"loading":false'))
    expect(api.fetchMe).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('blocks registration when signup is disabled, including direct context calls', async () => {
    renderAuth(fullCapabilities({ signup: false }), <AuthModal onClose={vi.fn()} />)
    await screen.findByRole('dialog')

    expect(screen.queryByRole('button', { name: '立即注册' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '尝试注册' }))
    await waitFor(() => expect(api.registerUser).not.toHaveBeenCalled())
  })

  it('clears only private resume markers on account changes and preserves reading preferences', async () => {
    renderAuth()
    expect(await screen.findByTestId('auth-state')).toHaveTextContent('"id":1')
    const localMarkers = [
      'translating_1_1_zh',
      'translation_paused_1_1_zh',
      'news-aggregator:research-recovery:v1:1',
      'newshub:full-article-auto:v1:1',
      'newshub:full-article-cancel:v1:1',
      'newshub_tts_pos_1_zh_full',
    ]
    for (const key of localMarkers) localStorage.setItem(key, 'private')
    sessionStorage.setItem('newshub:full-article-auto:v1:1', '1')
    localStorage.setItem('newshub_lang', 'en')
    localStorage.setItem('newshub_display_mode', 'bilingual')

    fireEvent.click(screen.getByRole('button', { name: '登录第二个账号' }))
    await waitFor(() => expect(screen.getByTestId('auth-state')).toHaveTextContent('"id":2'))
    for (const key of localMarkers) expect(localStorage.getItem(key)).toBeNull()
    expect(sessionStorage.getItem('newshub:full-article-auto:v1:1')).toBeNull()
    expect(localStorage.getItem('newshub_lang')).toBe('en')
    expect(localStorage.getItem('newshub_display_mode')).toBe('bilingual')

    localStorage.setItem('translation_paused_1_2_zh', 'private')
    sessionStorage.setItem('newshub_tts_pos_1_zh_full', 'private')
    fireEvent.click(screen.getByRole('button', { name: '退出' }))
    await waitFor(() => expect(screen.getByTestId('auth-state')).toHaveTextContent('"id":null'))
    expect(localStorage.getItem('translation_paused_1_2_zh')).toBeNull()
    expect(sessionStorage.getItem('newshub_tts_pos_1_zh_full')).toBeNull()
    expect(localStorage.getItem('newshub_lang')).toBe('en')
    expect(localStorage.getItem('newshub_display_mode')).toBe('bilingual')
  })
})
