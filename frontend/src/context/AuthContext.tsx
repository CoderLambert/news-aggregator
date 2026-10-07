/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { queryClient } from '@/services/queryClient'
import { fetchCsrfToken, fetchMe, loginUser, logoutUser, registerUser } from '@/services/api'
import { isRecord } from '@/types/news'

export interface AuthUser {
  id: number
  username: string
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
  return { id: value.id, username: value.username }
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within <AuthProvider>')
  return context
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [csrfReady, setCsrfReady] = useState(false)
  const viewerIdRef = useRef<number | null>(null)

  const clearViewerQueries = useCallback(() => {
    queryClient.removeQueries({ queryKey: ['news', 'list'] })
    queryClient.removeQueries({ queryKey: ['private'] })
  }, [])

  const ensureCsrf = useCallback(async () => {
    if (!csrfReady) {
      try { await fetchCsrfToken() } catch { /* the unsafe request reports a useful error */ }
      setCsrfReady(true)
    }
  }, [csrfReady])

  const refresh = useCallback(async () => {
    try {
      const nextUser = parseAuthUser(await fetchMe())
      if (viewerIdRef.current !== nextUser.id) clearViewerQueries()
      viewerIdRef.current = nextUser.id
      setUser(nextUser)
    } catch {
      if (viewerIdRef.current !== null) clearViewerQueries()
      viewerIdRef.current = null
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [clearViewerQueries])

  useEffect(() => { queueMicrotask(() => void refresh()) }, [refresh])

  const login = useCallback(async (username: string, password: string) => {
    await ensureCsrf()
    const nextUser = parseAuthUser(await loginUser(username, password))
    clearViewerQueries()
    viewerIdRef.current = nextUser.id
    setUser(nextUser)
    return nextUser
  }, [clearViewerQueries, ensureCsrf])

  const register = useCallback(async (username: string, password: string, email = '') => {
    await ensureCsrf()
    const nextUser = parseAuthUser(await registerUser(username, password, email))
    clearViewerQueries()
    viewerIdRef.current = nextUser.id
    setUser(nextUser)
    return nextUser
  }, [clearViewerQueries, ensureCsrf])

  const logout = useCallback(async () => {
    try { await logoutUser() } catch { /* clear local identity even if the server session expired */ }
    clearViewerQueries()
    viewerIdRef.current = null
    setUser(null)
  }, [clearViewerQueries])

  return <AuthContext.Provider value={{ user, loading, login, register, logout, refresh }}>{children}</AuthContext.Provider>
}
