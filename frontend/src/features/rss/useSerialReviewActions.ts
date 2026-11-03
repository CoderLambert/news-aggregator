import { useEffect, useRef, useState } from 'react'
import { workspaceError } from '@/services/workspaceApi'

/** Stop on the first uncertain result; retries keep each item's original key. */
export function useSerialReviewActions() {
  const alive = useRef(true)
  const running = useRef(false)
  const completed = useRef(new Set<string>())
  const keys = useRef(new Map<string, string>())
  const [busy, setBusy] = useState(false)
  const [started, setStarted] = useState(false)
  const [done, setDone] = useState<string[]>([])
  const [error, setError] = useState('')
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  async function run(ids: string[], perform: (id: string, key: string) => Promise<unknown>) {
    if (running.current || !alive.current) return
    running.current = true; setBusy(true); setStarted(true); setError('')
    try {
      for (const id of ids) {
        if (!alive.current || completed.current.has(id)) continue
        if (!keys.current.has(id)) keys.current.set(id, crypto.randomUUID())
        await perform(id, keys.current.get(id)!)
        if (!alive.current) break
        completed.current.add(id); setDone([...completed.current])
      }
    } catch (cause) {
      if (alive.current) setError(workspaceError(cause))
    } finally {
      running.current = false
      if (alive.current) setBusy(false)
    }
  }
  return { run, busy, started, done, error }
}
