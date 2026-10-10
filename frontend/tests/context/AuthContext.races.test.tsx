import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '@/context/AuthContext'
import * as api from '@/services/api'
import { queryClient } from '@/services/queryClient'
import { CapabilitiesTestProvider, fullCapabilities, readOnlyCapabilities } from '../helpers/capabilities'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function authUser(id: number, username: string) {
  return { id, username, is_superuser: false }
}

function AuthProbe({ client }: { client: QueryClient }) {
  const auth = useAuth()
  const [error, setError] = useState('')
  const run = (operation: Promise<unknown>) => {
    void operation.catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : 'authentication failed')
    })
  }
  return (
    <>
      <output data-testid="auth-state">{JSON.stringify({
        id: auth.user?.id ?? null,
        username: auth.user?.username ?? null,
        loading: auth.loading,
      })}</output>
      {error && <p role="alert">{error}</p>}
      <button type="button" onClick={() => run(auth.refresh())}>refresh</button>
      <button type="button" onClick={() => run(auth.login('reader-a', 'password'))}>login A</button>
      <button type="button" onClick={() => run(auth.login('reader-b', 'password'))}>login B</button>
      <button type="button" onClick={() => run(auth.register('reader-c', 'password', 'c@example.test', 'invite-c'))}>register C</button>
      <button type="button" onClick={() => run(auth.logout())}>logout</button>
      <button type="button" onClick={() => client.setQueryData(['capabilities'], readOnlyCapabilities())}>disable accounts</button>
    </>
  )
}

function renderAuth(options: { strict?: boolean; capabilities?: ReturnType<typeof fullCapabilities> } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const view = render(
    <CapabilitiesTestProvider client={client} value={options.capabilities ?? fullCapabilities()}>
      <AuthProvider><AuthProbe client={client} /></AuthProvider>
    </CapabilitiesTestProvider>,
    { reactStrictMode: options.strict ?? false },
  )
  return { ...view, client }
}

function authState() {
  return JSON.parse(screen.getByTestId('auth-state').textContent ?? '{}') as {
    id: number | null
    username: string | null
    loading: boolean
  }
}

async function waitForHydration() {
  await waitFor(() => expect(authState().loading).toBe(false))
}

beforeEach(() => {
  vi.spyOn(api, 'fetchMe').mockRejectedValue(new Error('anonymous'))
  vi.spyOn(api, 'fetchCsrfToken').mockResolvedValue('csrf-token')
  vi.spyOn(api, 'loginUser').mockImplementation(async (username) => ({ id: username === 'reader-b' ? 2 : 1, username }))
  vi.spyOn(api, 'registerUser').mockResolvedValue({ id: 3, username: 'reader-c' })
  vi.spyOn(api, 'logoutUser').mockResolvedValue({})
})

afterEach(() => {
  vi.restoreAllMocks()
  queryClient.clear()
  localStorage.clear()
  sessionStorage.clear()
})

describe('AuthProvider request ordering and stale-response fencing', () => {
  it('does not let a fetchMe response arriving after logout restore the old user', async () => {
    const refresh = deferred<unknown>()
    vi.mocked(api.fetchMe).mockImplementationOnce(() => refresh.promise)
    renderAuth()
    await waitFor(() => expect(api.fetchMe).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByRole('button', { name: 'logout' }))
    await waitFor(() => expect(api.logoutUser).toHaveBeenCalledTimes(1))
    await act(async () => refresh.resolve(authUser(1, 'late-reader')))

    await waitForHydration()
    expect(authState()).toMatchObject({ id: null, username: null })
  })

  it('serializes overlapping logins and only commits the newest result', async () => {
    const first = deferred<unknown>()
    const second = deferred<unknown>()
    const events: string[] = []
    vi.mocked(api.fetchCsrfToken).mockImplementation(async () => {
      events.push('csrf')
      return `csrf-${events.length}`
    })
    vi.mocked(api.loginUser).mockImplementation((username) => {
      events.push(`login:${username}`)
      return username === 'reader-a' ? first.promise : second.promise
    })
    renderAuth()
    await waitForHydration()

    fireEvent.click(screen.getByRole('button', { name: 'login A' }))
    await waitFor(() => expect(api.loginUser).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole('button', { name: 'login B' }))
    await act(async () => first.resolve(authUser(1, 'reader-a')))

    await waitFor(() => expect(api.loginUser).toHaveBeenCalledTimes(2))
    expect(authState().id).toBeNull()
    expect(events).toEqual(['csrf', 'login:reader-a', 'csrf', 'login:reader-b'])
    await act(async () => second.resolve(authUser(2, 'reader-b')))

    await waitFor(() => expect(authState()).toMatchObject({ id: 2, username: 'reader-b', loading: false }))
  })

  it('keeps logout and login HTTP order equal to invocation order', async () => {
    const pendingLogout = deferred<unknown>()
    const pendingLogin = deferred<unknown>()
    const events: string[] = []
    vi.mocked(api.fetchCsrfToken).mockImplementation(async () => {
      events.push('csrf')
      return 'csrf-token'
    })
    vi.mocked(api.logoutUser).mockImplementation(() => {
      events.push('logout')
      return pendingLogout.promise
    })
    vi.mocked(api.loginUser).mockImplementation(() => {
      events.push('login')
      return pendingLogin.promise
    })
    renderAuth()
    await waitForHydration()

    fireEvent.click(screen.getByRole('button', { name: 'logout' }))
    await waitFor(() => expect(api.logoutUser).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole('button', { name: 'login A' }))
    expect(api.loginUser).not.toHaveBeenCalled()
    expect(events).toEqual(['csrf', 'logout'])

    await act(async () => pendingLogout.resolve({}))
    await waitFor(() => expect(api.loginUser).toHaveBeenCalledTimes(1))
    expect(events).toEqual(['csrf', 'logout', 'login'])
    await act(async () => pendingLogin.resolve(authUser(1, 'reader-a')))

    await waitFor(() => expect(authState()).toMatchObject({ id: 1, username: 'reader-a', loading: false }))
  })

  it('does not start refresh while an auth mutation is pending and refreshes CSRF after a stale login succeeds', async () => {
    const pendingLogin = deferred<unknown>()
    const events: string[] = []
    vi.mocked(api.fetchCsrfToken).mockImplementation(async () => {
      events.push('csrf')
      return `csrf-${events.length}`
    })
    vi.mocked(api.loginUser).mockImplementation(() => {
      events.push('login')
      return pendingLogin.promise
    })
    vi.mocked(api.logoutUser).mockImplementation(async () => { events.push('logout') })
    renderAuth()
    await waitForHydration()
    const initialFetchCount = vi.mocked(api.fetchMe).mock.calls.length

    fireEvent.click(screen.getByRole('button', { name: 'login A' }))
    await waitFor(() => expect(api.loginUser).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole('button', { name: 'logout' }))
    fireEvent.click(screen.getByRole('button', { name: 'refresh' }))
    expect(api.fetchMe).toHaveBeenCalledTimes(initialFetchCount)

    await act(async () => pendingLogin.resolve(authUser(1, 'reader-a')))
    await waitFor(() => expect(api.logoutUser).toHaveBeenCalledTimes(1))
    expect(events).toEqual(['csrf', 'login', 'csrf', 'logout'])
    await waitFor(() => expect(authState()).toMatchObject({ id: null, username: null, loading: false }))
  })

  it('does not issue unsafe authentication calls when CSRF fetch fails and allows a clean retry', async () => {
    vi.mocked(api.fetchCsrfToken)
      .mockRejectedValueOnce(new Error('CSRF unavailable'))
      .mockResolvedValueOnce('fresh-csrf')
    renderAuth()
    await waitForHydration()

    fireEvent.click(screen.getByRole('button', { name: 'login A' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('CSRF unavailable')
    expect(api.loginUser).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'login A' }))
    await waitFor(() => expect(api.loginUser).toHaveBeenCalledTimes(1))
    expect(api.fetchCsrfToken).toHaveBeenCalledTimes(2)
    await waitFor(() => expect(authState()).toMatchObject({ id: 1, username: 'reader-a', loading: false }))
  })

  it('keeps the newest of two refresh responses when they complete in reverse order', async () => {
    const older = deferred<unknown>()
    const newer = deferred<unknown>()
    vi.mocked(api.fetchMe)
      .mockRejectedValueOnce(new Error('anonymous'))
      .mockImplementationOnce(() => older.promise)
      .mockImplementationOnce(() => newer.promise)
    renderAuth()
    await waitForHydration()

    fireEvent.click(screen.getByRole('button', { name: 'refresh' }))
    fireEvent.click(screen.getByRole('button', { name: 'refresh' }))
    await waitFor(() => expect(api.fetchMe).toHaveBeenCalledTimes(3))
    await act(async () => newer.resolve(authUser(2, 'newer-reader')))
    await waitFor(() => expect(authState().username).toBe('newer-reader'))
    await act(async () => older.resolve(authUser(1, 'older-reader')))

    expect(authState()).toMatchObject({ id: 2, username: 'newer-reader', loading: false })
  })

  it('ignores an old identity response after accounts are disabled', async () => {
    const pending = deferred<unknown>()
    vi.mocked(api.fetchMe).mockImplementationOnce(() => pending.promise)
    renderAuth()
    await waitFor(() => expect(api.fetchMe).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByRole('button', { name: 'disable accounts' }))
    await waitFor(() => expect(authState()).toMatchObject({ id: null, loading: false }))
    await act(async () => pending.resolve(authUser(1, 'late-reader')))

    expect(authState()).toMatchObject({ id: null, username: null, loading: false })
    expect(api.fetchMe).toHaveBeenCalledTimes(1)
  })

  it('keeps the mounted lifecycle usable under StrictMode and fences an unmounted refresh', async () => {
    vi.mocked(api.fetchMe).mockResolvedValue(authUser(1, 'reader-a'))
    const mounted = renderAuth({ strict: true })
    await waitFor(() => expect(authState()).toMatchObject({ id: 1, username: 'reader-a', loading: false }))
    mounted.unmount()

    vi.mocked(api.fetchMe).mockClear()
    const pending = deferred<unknown>()
    vi.mocked(api.fetchMe).mockImplementationOnce(() => pending.promise)
    const unmounted = renderAuth()
    await waitFor(() => expect(api.fetchMe).toHaveBeenCalledTimes(1))
    unmounted.unmount()
    await act(async () => pending.resolve(authUser(8, 'unmounted-late-reader')))
  })

  it('invalidates CSRF readiness after successful login and registration', async () => {
    const events: string[] = []
    vi.mocked(api.fetchCsrfToken).mockImplementation(async () => {
      events.push('csrf')
      return 'csrf-token'
    })
    vi.mocked(api.loginUser).mockImplementation(async () => {
      events.push('login')
      return authUser(1, 'reader-a')
    })
    vi.mocked(api.registerUser).mockImplementation(async () => {
      events.push('register')
      return authUser(3, 'reader-c')
    })
    renderAuth()
    await waitForHydration()

    fireEvent.click(screen.getByRole('button', { name: 'login A' }))
    await waitFor(() => expect(authState().username).toBe('reader-a'))
    fireEvent.click(screen.getByRole('button', { name: 'register C' }))
    await waitFor(() => expect(authState().username).toBe('reader-c'))

    expect(api.registerUser).toHaveBeenCalledWith('reader-c', 'password', 'c@example.test', 'invite-c')
    expect(events).toEqual(['csrf', 'login', 'csrf', 'register'])
    const persistedValues = [localStorage, sessionStorage].flatMap((storage) =>
      Array.from({ length: storage.length }, (_, index) => storage.getItem(storage.key(index) ?? '') ?? ''),
    )
    expect(persistedValues.some((value) => value.includes('invite-c'))).toBe(false)
    expect(queryClient.getQueryCache().getAll().some((query) =>
      JSON.stringify([query.queryKey, query.state.data]).includes('invite-c'))).toBe(false)
  })
})
