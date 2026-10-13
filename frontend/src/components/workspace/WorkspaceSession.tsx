import { useLayoutEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import { setWorkspaceViewer } from '@/services/workspaceApi'

export default function WorkspaceSession() {
  const { user } = useAuth()
  const client = useQueryClient()
  const viewer = user?.id ?? null
  const previous = useRef<number | null>(viewer)
  useLayoutEffect(() => {
    setWorkspaceViewer(viewer)
    if (previous.current !== viewer) {
      const oldViewer = previous.current ?? 'anonymous'
      void client.cancelQueries({ queryKey: ['workspace', oldViewer] }).then(() => {
        client.removeQueries({ queryKey: ['workspace', oldViewer] })
      })
      previous.current = viewer
    }
    return () => setWorkspaceViewer(null)
  }, [viewer, client])
  return null
}
