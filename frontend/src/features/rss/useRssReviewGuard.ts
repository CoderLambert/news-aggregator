import { useEffect } from 'react'
import { useAuth } from '@/context/AuthContext'

// A failed authorization must hide retained query data while identity refreshes.
export function useRssReviewGuard(...errors: unknown[]): boolean {
  const { refresh } = useAuth()
  const denied = errors.some(error => error !== null && typeof error === 'object' && 'status' in error && [401, 403].includes(Number(error.status)))
  useEffect(() => { if (denied && typeof refresh === 'function') void refresh() }, [denied, refresh])
  return denied
}
