import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import { loginUser, registerUser, logoutUser, fetchMe, fetchCsrfToken } from '../services/api'

/* eslint-disable react-refresh/only-export-components */
const AuthContext = createContext(null)
export { AuthContext }

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [csrfReady, setCsrfReady] = useState(false)

  // Ensure Django CSRF cookie is set before any POST requests
  const ensureCsrf = useCallback(async () => {
    if (!csrfReady) {
      try { await fetchCsrfToken() } catch { /* ignore */ }
      setCsrfReady(true)
    }
  }, [csrfReady])

  const loadUser = useCallback(async () => {
    try {
      const data = await fetchMe()
      setUser(data)
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    queueMicrotask(() => loadUser())
  }, [loadUser])

  const login = useCallback(async (username, password) => {
    await ensureCsrf()
    const data = await loginUser(username, password)
    setUser(data)
    return data
  }, [ensureCsrf])

  const register = useCallback(async (username, password, email) => {
    await ensureCsrf()
    const data = await registerUser(username, password, email)
    setUser(data)
    return data
  }, [ensureCsrf])

  const logout = useCallback(async () => {
    try { await logoutUser() } catch { /* ignore */ }
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refresh: loadUser }}>
      {children}
    </AuthContext.Provider>
  )
}
