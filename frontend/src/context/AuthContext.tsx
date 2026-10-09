/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
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

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  login: (username: string, password: string) => Promise<AuthUser>
  register: (username: string, password: string, email?: string) => Promise<AuthUser>
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
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [csrfReady, setCsrfReady] = useState(false)
  const viewerIdRef = useRef<number | null>(null)

  const clearViewerQueries = useCallback(() => {
    // Provider comparisons are cached with a viewer key even though their
    // current backend collection is shared. Drop every viewer-scoped copy on
    // an identity transition so a disabled query can never reveal old data.
    void queryClient.cancelQueries({ queryKey: ['providerComparisons'] })
    queryClient.removeQueries({ queryKey: ['providerComparisons'] })
    queryClient.removeQueries({ queryKey: newsKeys.lists() })
    queryClient.removeQueries({ queryKey: newsKeys.details() })
    void queryClient.cancelQueries({ queryKey: newsWorkflowKeys.chatHistories() })
    queryClient.removeQueries({ queryKey: newsWorkflowKeys.chatHistories() })
    queryClient.removeQueries({ queryKey: ['private'] })
    void queryClient.cancelQueries({ queryKey: ['chatgptSubscription'] })
    queryClient.removeQueries({ queryKey: ['chatgptSubscription'] })
  }, [])

  const ensureCsrf = useCallback(async () => {
    if (!csrfReady) {
      try { await fetchCsrfToken() } catch { /* the unsafe request reports a useful error */ }
      setCsrfReady(true)
    }
  }, [csrfReady])

  const refresh = useCallback(async () => {
    if (!accountsEnabled) {
      clearPrivateMarkers()
      if (viewerIdRef.current !== null) clearViewerQueries()
      viewerIdRef.current = null
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const nextUser = parseAuthUser(await fetchMe())
      if (viewerIdRef.current !== nextUser.id) {
        clearViewerQueries()
        clearPrivateMarkers()
      }
      viewerIdRef.current = nextUser.id
      setUser(nextUser)
    } catch {
      if (viewerIdRef.current !== null) {
        clearViewerQueries()
        clearPrivateMarkers()
      }
      viewerIdRef.current = null
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [accountsEnabled, clearViewerQueries])

  useEffect(() => {
    if (capabilitiesLoading) {
      return
    }
    if (!accountsEnabled) {
      clearPrivateMarkers()
      if (viewerIdRef.current !== null) {
        clearViewerQueries()
        queueMicrotask(() => setUser(null))
      }
      viewerIdRef.current = null
      return
    }
    queueMicrotask(() => void refresh())
  }, [accountsEnabled, capabilitiesLoading, clearViewerQueries, refresh])

  const login = useCallback(async (username: string, password: string) => {
    if (!accountsEnabled) throw new Error('账号功能当前不可用')
    await ensureCsrf()
    const nextUser = parseAuthUser(await loginUser(username, password))
    clearViewerQueries()
    clearPrivateMarkers()
    viewerIdRef.current = nextUser.id
    setUser(nextUser)
    setLoading(false)
    return nextUser
  }, [accountsEnabled, clearViewerQueries, ensureCsrf])

  const register = useCallback(async (username: string, password: string, email = '') => {
    if (!accountsEnabled) throw new Error('账号功能当前不可用')
    if (!signupEnabled) throw new Error('公开注册当前已关闭')
    await ensureCsrf()
    const nextUser = parseAuthUser(await registerUser(username, password, email))
    clearViewerQueries()
    clearPrivateMarkers()
    viewerIdRef.current = nextUser.id
    setUser(nextUser)
    setLoading(false)
    return nextUser
  }, [accountsEnabled, clearViewerQueries, ensureCsrf, signupEnabled])

  const logout = useCallback(async () => {
    if (accountsEnabled) {
      try { await logoutUser() } catch { /* clear local identity even if the server session expired */ }
    }
    clearViewerQueries()
    clearPrivateMarkers()
    viewerIdRef.current = null
    setUser(null)
    setLoading(false)
  }, [accountsEnabled, clearViewerQueries])

  return <AuthContext.Provider value={{
    user: accountsEnabled ? user : null,
    loading: capabilitiesLoading || (accountsEnabled && loading),
    login,
    register,
    logout,
    refresh,
  }}>{children}</AuthContext.Provider>
}
