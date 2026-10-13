import { useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import { useCapability } from '@/context/CapabilitiesContext'
import { useNewsDetail } from '@/hooks/useNewsDetail'
import { workspaceRequest, workspaceKeys } from '@/services/workspaceApi'

export default function ReadingTracker() {
  const { id } = useParams()
  const { user } = useAuth()
  const accounts = useCapability('accounts').enabled
  const { news, error, loading } = useNewsDetail(id)
  const client = useQueryClient()
  const newsId = news?.id
  const userId = user?.id
  useEffect(() => {
    if (!accounts || !userId || !newsId || error || loading) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | null = null
    let attempted = false
    function changed() {
      if (timer) clearTimeout(timer)
      if (document.visibilityState === 'hidden' || attempted) return
      timer = setTimeout(() => {
        attempted = true
        void workspaceRequest('/me/reading-stats/', { method: 'POST', body: { news_id: newsId }, signal: controller.signal })
          .then(() => client.invalidateQueries({ queryKey: workspaceKeys.stats(userId!) }))
          .catch(() => { /* Optional reading telemetry must not disrupt the article. */ })
      }, 3000)
    }
    changed()
    document.addEventListener('visibilitychange', changed)
    return () => { controller.abort(); if (timer) clearTimeout(timer); document.removeEventListener('visibilitychange', changed) }
  }, [accounts, userId, newsId, error, loading, client])
  return null
}
