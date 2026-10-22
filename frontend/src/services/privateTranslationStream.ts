import { isRecord } from '@/types/news'
import { parsePrivateTranslation, type PrivateTranslationTask } from './privateTranslationApi'

const MAX_PREVIEW = 1_048_576
const CURSOR = /^\d{1,20}-\d{1,20}$/
function compareCursor(a: string, b: string) {
  const [at, ai] = a.split('-').map(BigInt), [bt, bi] = b.split('-').map(BigInt)
  return at === bt ? (ai < bi ? -1 : ai > bi ? 1 : 0) : at < bt ? -1 : 1
}

/** GET-only replay. Both the legacy snapshot stream and Redis named events are supported. */
export function observePrivateTranslation(initial: PrivateTranslationTask, handlers: {
  onTask: (task: PrivateTranslationTask) => void; onLost: () => void
}) {
  let task = initial, cursor = '', closed = false, retries = 0, reconnecting = false
  let source: EventSource | undefined, timer: ReturnType<typeof setTimeout> | undefined
  let frame: number | undefined
  const publish = (terminal = false) => {
    if (terminal) {
      if (frame !== undefined) cancelAnimationFrame(frame)
      frame = undefined
      handlers.onTask(task)
    } else if (frame === undefined) frame = requestAnimationFrame(() => {
      frame = undefined
      if (!closed) handlers.onTask(task)
    })
  }
  const shutdown = () => {
    closed = true; source?.close(); clearTimeout(timer)
    if (frame !== undefined) cancelAnimationFrame(frame)
  }
  const lost = () => {
    source?.close()
    if (closed || reconnecting) return
    if (retries++ < 3) { reconnecting = true; timer = setTimeout(() => { reconnecting = false; connect() }, 500 * 2 ** retries); return }
    shutdown(); handlers.onLost()
  }
  const identity = (value: Record<string, unknown>) => {
    if (value.task_id !== initial.task_id || value.news_id !== initial.news_id || value.generation !== initial.generation) {
      throw new Error('Translation stream identity changed')
    }
  }
  const immutable = (next: PrivateTranslationTask) => {
    if (next.model_config_id !== initial.model_config_id || next.request_id !== initial.request_id) {
      throw new Error('Translation request binding changed')
    }
  }
  const receive = (kind: string, event: MessageEvent<string>) => {
    if (closed) return
    try {
      if (event.data.length > 2_097_152) throw new Error('Translation event budget exceeded')
      const data: unknown = JSON.parse(event.data)
      if (!isRecord(data)) throw new Error('Invalid translation event')
      if (kind === 'message') {
        const next = parsePrivateTranslation(data); identity(data); immutable(next); task = next
      } else {
        identity(data)
        if (kind === 'unavailable') { lost(); return }
        const id = event.lastEventId
        if (id && !CURSOR.test(id)) throw new Error('Invalid translation cursor')
        // Redis may replay the terminal at the same cursor; it remains authoritative.
        if (id && cursor && compareCursor(id, cursor) <= 0 && kind !== 'terminal') { retries = 0; return }
        if (kind === 'delta') {
          if (!id || !cursor || data.previous_cursor !== cursor || typeof data.delta !== 'string') {
            throw new Error('Translation replay gap')
          }
          task = { ...task, status: 'running', progress: task.progress + data.delta }
        } else {
          const next = parsePrivateTranslation(data.task)
          identity(next as unknown as Record<string, unknown>); immutable(next)
          const draft = next.status === 'failed' && next.error_code === 'incomplete_response' ? task.progress : ''
          task = draft ? { ...next, progress: draft } : next
          if (kind === 'terminal' && ['queued', 'running'].includes(task.status)) throw new Error('Invalid terminal')
        }
        if (id) cursor = id
      }
      if (task.progress.length > MAX_PREVIEW) throw new Error('Translation preview budget exceeded')
      // A healthy replay resets consecutive failures; long tasks may rotate SSE.
      if (kind === 'message' || (event.lastEventId && task.status !== 'queued')) retries = 0
      const terminal = !['queued', 'running'].includes(task.status)
      publish(terminal)
      if (terminal) shutdown()
    } catch {
      // Re-read an authoritative snapshot; never append across a missing delta.
      cursor = ''; lost()
    }
  }
  function connect() {
    if (closed) return
    source = new EventSource(`/api/me/ai/translations/${encodeURIComponent(initial.task_id)}/events/${cursor ? '?cursor=' + encodeURIComponent(cursor) : ''}`)
    const current = source
    for (const kind of ['message', 'snapshot', 'delta', 'terminal', 'unavailable']) {
      current.addEventListener(kind, event => { if (source === current && !closed) receive(kind, event as MessageEvent<string>) })
    }
    current.onerror = () => { if (source === current) lost() }
  }
  if (typeof EventSource === 'undefined') { timer = setTimeout(handlers.onLost, 0) }
  else connect()
  return shutdown
}
