/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { queryClient } from '@/services/queryClient'
import { newsKeys } from '@/services/newsQueries'
import { fetchCsrfToken, fetchMe, loginUser, logoutUser, registerUser } from '@/services/api'
import { isRecord } from '@/types/news'
import { newsWorkflowKeys } from '@/services/newsWorkflowQueries'
import { useCapabilities } from '@/context/CapabilitiesContext'

const PRIVATE_MARKER_PREFIXES = [
  'translating_',
  'translation_paused_',
  'news-aggregator:research-recovery:v1',
  'newshub:full-article-auto',
  'newshub:full-article-cancel',
  'newshub_tts_pos_',
]

const PRIVATE_QUERY_KEYS = [
  ['providerComparisons'],
  newsKeys.lists(),
  newsKeys.details(),
  newsWorkflowKeys.chatHistories(),
  ['private'],
  ['chatgptSubscription'],
] as const

function clearPrivateMarkers(): void {
  const storages: Storage[] = []
  try { if (globalThis.localStorage) storages.push(globalThis.localStorage) } catch { /* storage can be unavailable */ }
  try { if (globalThis.sessionStorage) storages.push(globalThis.sessionStorage) } catch { /* storage can be unavailable */ }
  for (const storage of storages) {
    if (!storage) continue
    try {
      const keys: string[] = []
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index)
        if (key && PRIVATE_MARKER_PREFIXES.some((prefix) => key.startsWith(prefix))) keys.push(key)
      }
      for (const key of keys) storage.removeItem(key)
    } catch {
      // Storage may be disabled; authentication and reading preferences still work.
    }
  }
}

export interface AuthUser {
  id: number
  username: string
  isSuperuser: boolean
}

interface IdentityState {
  user: AuthUser
  capabilityGeneration: number
}

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  login: (username: string, password: string) => Promise<AuthUser>
  register: (username: string, password: string, email?: string, inviteToken?: string) => Promise<AuthUser>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)
export { AuthContext }

function parseAuthUser(value: unknown): AuthUser {
  if (!isRecord(value) || typeof value.id !== 'number' || typeof value.username !== 'string') {
    throw new TypeError('Invalid authentication response')
  }
  return { id: value.id, username: value.username, isSuperuser: value.is_superuser === true }
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within <AuthProvider>')
  return context
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { capabilities, loading: capabilitiesLoading } = useCapabilities()
  const accountsEnabled = !capabilitiesLoading && capabilities.features.accounts.enabled
  const signupEnabled = accountsEnabled && capabilities.features.signup.enabled
  const [identity, setIdentity] = useState<IdentityState | null>(null)
  const [loading, setLoading] = useState(true)
  const [accountCapability, setAccountCapability] = useState({ enabled: accountsEnabled, generation: 0 })
  if (accountCapability.enabled !== accountsEnabled) {
    setAccountCapability({ enabled: accountsEnabled, generation: accountCapability.generation + 1 })
  }

  const mountedRef = useRef(false)
  const accountsEnabledRef = useRef(false)
  const signupEnabledRef = useRef(false)
  const capabilitiesLoadingRef = useRef(true)
  const viewerIdRef = useRef<number | null>(null)
  const epochRef = useRef(0)
  const refreshSequenceRef = useRef(0)
  const capabilityGenerationRef = useRef(accountCapability.generation)
  const refreshRef = useRef<() => Promise<void>>(() => Promise.resolve())
  const pendingMutationsRef = useRef(0)
  const mutationQueueRef = useRef<Promise<void>>(Promise.resolve())
  const csrfReadyRef = useRef(false)
  const csrfInFlightRef = useRef<Promise<string> | null>(null)

  useLayoutEffect(() => {
    accountsEnabledRef.current = accountsEnabled
    signupEnabledRef.current = signupEnabled
    capabilitiesLoadingRef.current = capabilitiesLoading
    capabilityGenerationRef.current = accountCapability.generation
  }, [accountCapability.generation, accountsEnabled, capabilitiesLoading, signupEnabled])

  const clearViewerQueries = useCallback(async () => {
    await Promise.all(PRIVATE_QUERY_KEYS.map((queryKey) =>
      queryClient.cancelQueries({ queryKey }),
    ))
    for (const queryKey of PRIVATE_QUERY_KEYS) queryClient.removeQueries({ queryKey })
  }, [])

  const invalidateCsrf = useCallback(() => {
    csrfReadyRef.current = false
    csrfInFlightRef.current = null
  }, [])

  const ensureCsrf = useCallback(async () => {
    if (csrfReadyRef.current) return
    let request = csrfInFlightRef.current
    if (!request) {
      request = fetchCsrfToken()
      csrfInFlightRef.current = request
    }
    try {
      const token = await request
      if (!token) throw new TypeError('Invalid CSRF response')
      if (csrfInFlightRef.current === request) {
        csrfReadyRef.current = true
        csrfInFlightRef.current = null
      }
    } catch (error) {
      if (csrfInFlightRef.current === request) {
        csrfReadyRef.current = false
        csrfInFlightRef.current = null
      }
      throw error
    }
  }, [])

  const refresh = useCallback(async () => {
    if (capabilitiesLoadingRef.current || !accountsEnabledRef.current || pendingMutationsRef.current > 0) return
    const generation = capabilityGenerationRef.current
    const epoch = epochRef.current
    const sequence = ++refreshSequenceRef.current
    const canCommit = () => mountedRef.current && accountsEnabledRef.current &&
      capabilityGenerationRef.current === generation && pendingMutationsRef.current === 0 &&
      epochRef.current === epoch &&
      refreshSequenceRef.current === sequence

    try {
      const nextUser = parseAuthUser(await fetchMe())
      if (!canCommit()) return
      if (viewerIdRef.current !== nextUser.id) {
        clearPrivateMarkers()
        await clearViewerQueries()
        if (!canCommit()) return
      }
      viewerIdRef.current = nextUser.id
      setIdentity({ user: nextUser, capabilityGeneration: generation })
    } catch {
      if (!canCommit()) return
      if (viewerIdRef.current !== null) {
        clearPrivateMarkers()
        await clearViewerQueries()
        if (!canCommit()) return
      }
      viewerIdRef.current = null
      setIdentity(null)
    } finally {
      if (canCommit()) setLoading(false)
    }
  }, [clearViewerQueries])

  useLayoutEffect(() => {
    refreshRef.current = refresh
  }, [refresh])

  const enqueueMutation = useCallback(<T,>(
    kind: 'login' | 'register' | 'logout',
    perform: () => Promise<T>,
    authenticatedUser?: (result: T) => AuthUser | null,
  ): Promise<T> => {
    const epoch = ++epochRef.current
    refreshSequenceRef.current += 1
    pendingMutationsRef.current += 1
    viewerIdRef.current = null
    clearPrivateMarkers()
    const clearPromise = clearViewerQueries()
    if (mountedRef.current) {
      setIdentity(null)
      setLoading(true)
    }

    const task = mutationQueueRef.current.catch(() => undefined).then(async () => {
      if (!mountedRef.current) throw new Error('Authentication provider is unavailable')
      if (capabilitiesLoadingRef.current || !accountsEnabledRef.current) throw new Error('账号功能当前不可用')
      if (kind === 'register' && !signupEnabledRef.current) throw new Error('公开注册当前已关闭')
      await clearPromise
      if (!mountedRef.current || capabilitiesLoadingRef.current || !accountsEnabledRef.current ||
        (kind === 'register' && !signupEnabledRef.current)) {
        throw new Error(kind === 'register' ? '公开注册当前已关闭' : '账号功能当前不可用')
      }
      await ensureCsrf()
      if (!mountedRef.current || capabilitiesLoadingRef.current || !accountsEnabledRef.current ||
        (kind === 'register' && !signupEnabledRef.current)) {
        throw new Error(kind === 'register' ? '公开注册当前已关闭' : '账号功能当前不可用')
      }
      return perform()
    }).then(async (result) => {
      const nextUser = authenticatedUser?.(result) ?? null
      if (nextUser && mountedRef.current && accountsEnabledRef.current && epochRef.current === epoch) {
        clearPrivateMarkers()
        await clearViewerQueries()
        if (mountedRef.current && accountsEnabledRef.current && epochRef.current === epoch) {
          viewerIdRef.current = nextUser.id
          setIdentity({ user: nextUser, capabilityGeneration: accountCapability.generation })
        }
      }
      return result
    }).finally(() => {
      pendingMutationsRef.current = Math.max(0, pendingMutationsRef.current - 1)
      if (mountedRef.current && accountsEnabledRef.current && epochRef.current === epoch) {
        setLoading(false)
      } else if (pendingMutationsRef.current === 0 && mountedRef.current && accountsEnabledRef.current) {
        void refreshRef.current()
      }
    })

    mutationQueueRef.current = task.then(() => undefined, () => undefined)
    return task
  }, [accountCapability.generation, clearViewerQueries, ensureCsrf])

  const login = useCallback((username: string, password: string) => {
    if (capabilitiesLoadingRef.current || !accountsEnabledRef.current) {
      return Promise.reject(new Error('账号功能当前不可用'))
    }
    return enqueueMutation(
      'login',
      async () => {
        const response = await loginUser(username, password)
        // Successful authentication rotates Django's CSRF secret, even when
        // this result has been fenced from changing the visible identity.
        invalidateCsrf()
        return parseAuthUser(response)
      },
      (nextUser) => nextUser as AuthUser,
    )
  }, [enqueueMutation, invalidateCsrf])

  const register = useCallback((username: string, password: string, email = '', inviteToken = '') => {
    if (capabilitiesLoadingRef.current || !accountsEnabledRef.current) {
      return Promise.reject(new Error('账号功能当前不可用'))
    }
    if (!signupEnabledRef.current) return Promise.reject(new Error('公开注册当前已关闭'))
    const token = inviteToken.trim()
    return enqueueMutation(
      'register',
      async () => {
        const response = await registerUser(username, password, email, token)
        invalidateCsrf()
        return parseAuthUser(response)
      },
      (nextUser) => nextUser as AuthUser,
    )
  }, [enqueueMutation, invalidateCsrf])

  const logout = useCallback(() => {
    if (capabilitiesLoadingRef.current || !accountsEnabledRef.current) {
      return Promise.reject(new Error('账号功能当前不可用'))
    }
    return enqueueMutation('logout', async () => {
      await logoutUser()
    })
  }, [enqueueMutation])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      epochRef.current += 1
      refreshSequenceRef.current += 1
      invalidateCsrf()
    }
  }, [invalidateCsrf])

  useEffect(() => {
    if (capabilitiesLoading) return
    if (!accountsEnabled) {
      epochRef.current += 1
      refreshSequenceRef.current += 1
      invalidateCsrf()
      viewerIdRef.current = null
      clearPrivateMarkers()
      void clearViewerQueries()
      return
    }
    queueMicrotask(() => {
      if (mountedRef.current && accountsEnabledRef.current && !capabilitiesLoadingRef.current) void refresh()
    })
  }, [accountsEnabled, capabilitiesLoading, clearViewerQueries, invalidateCsrf, refresh])

  return <AuthContext.Provider value={{
    user: accountsEnabled && identity?.capabilityGeneration === accountCapability.generation ? identity.user : null,
    loading: capabilitiesLoading || (accountsEnabled && loading),
    login,
    register,
    logout,
    refresh,
  }}>{children}</AuthContext.Provider>
}
