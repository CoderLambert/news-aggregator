import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { observePrivateTranslation } from '@/services/privateTranslationStream'
import type { PrivateTranslationTask } from '@/services/privateTranslationApi'

const initial: PrivateTranslationTask = {
  task_id: 'task-a', request_id: 'request-a', news_id: 7, generation: 1, retry_of: null,
  status: 'running', progress: '', error_code: '', model_config_id: 'saved-model',
  target_language: 'zh', result: null, previous_result: null,
}
const identity = { task_id: 'task-a', news_id: 7, generation: 1 }
class Source {
  static all: Source[] = []
  handlers = new Map<string, (event: MessageEvent<string>) => void>()
  close = vi.fn()
  onerror: null | (() => void) = null
  constructor(public url: string) { Source.all.push(this) }
  addEventListener(kind: string, handler: (event: MessageEvent<string>) => void) { this.handlers.set(kind, handler) }
  emit(kind: string, data: unknown, id = '') { this.handlers.get(kind)?.(new MessageEvent(kind, { data: JSON.stringify(data), lastEventId: id })) }
}
beforeEach(() => {
  vi.useFakeTimers(); Source.all = []; vi.stubGlobal('EventSource', Source)
  vi.stubGlobal('requestAnimationFrame', (cb: () => void) => setTimeout(cb, 16))
  vi.stubGlobal('cancelAnimationFrame', clearTimeout)
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
function setup() {
  const onTask = vi.fn(), onLost = vi.fn()
  const close = observePrivateTranslation(initial, { onTask, onLost })
  return { onTask, onLost, close, source: Source.all[0] }
}
describe('private translation read-only stream', () => {
  it('merges named snapshots/deltas, deduplicates cursors and accepts only a saved terminal result', () => {
    const view = setup()
    view.source.emit('snapshot', { ...identity, task: { ...initial, progress: '## 标题' } }, '1-0')
    view.source.emit('delta', { ...identity, delta: '\n\n正文', previous_cursor: '1-0' }, '2-0')
    view.source.emit('delta', { ...identity, delta: '重复', previous_cursor: '1-0' }, '2-0')
    vi.advanceTimersByTime(16)
    expect(view.onTask).toHaveBeenLastCalledWith(expect.objectContaining({ progress: '## 标题\n\n正文', status: 'running' }))
    const result = { result_id: 1, task_id: 'task-a', content: '## 已保存', provider: 'synthetic', model: 'saved', scope: 'private' }
    view.source.emit('terminal', { ...identity, task: { ...initial, status: 'succeeded', progress: '', result } }, '3-0')
    expect(view.onTask).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'succeeded', result }))
    expect(view.source.close).toHaveBeenCalled()
  })
  it('rejects a foreign task or generation before exposing private content', () => {
    const view = setup()
    view.source.emit('snapshot', { ...identity, generation: 9, task: { ...initial, progress: 'private other generation' } }, '1-0')
    vi.advanceTimersByTime(16)
    expect(view.onTask).not.toHaveBeenCalled()
    expect(view.source.close).toHaveBeenCalled()
    view.close()
  })
  it('recovers a missing delta through a fresh GET snapshot instead of appending across the gap', () => {
    const view = setup()
    view.source.emit('snapshot', { ...identity, task: initial }, '1-0')
    view.source.emit('delta', { ...identity, delta: 'wrong', previous_cursor: '9-0' }, '10-0')
    vi.advanceTimersByTime(1000)
    expect(Source.all).toHaveLength(2)
    expect(Source.all[1].url).not.toContain('cursor=')
    expect(view.onTask).not.toHaveBeenCalledWith(expect.objectContaining({ progress: 'wrong' }))
    view.close()
  })
  it('reconnects with the last cursor without creating a new translation', () => {
    const view = setup()
    view.source.emit('snapshot', { ...identity, task: initial }, '5-0')
    view.source.onerror?.(); vi.advanceTimersByTime(1000)
    expect(Source.all[1].url).toContain('cursor=5-0')
    view.close()
  })
  it('does not turn EOF/errors into success and stops after bounded read-only reconnects', () => {
    const view = setup()
    for (let i = 0; i < 4; i++) { Source.all.at(-1)?.onerror?.(); vi.runOnlyPendingTimers() }
    expect(view.onLost).toHaveBeenCalledOnce()
    expect(view.onTask).not.toHaveBeenCalled()
  })
  it('supports the legacy accumulated snapshot protocol and ignores late frames after unmount', () => {
    const view = setup()
    view.source.emit('message', { ...initial, progress: '已有累计片段' })
    vi.advanceTimersByTime(16)
    expect(view.onTask).toHaveBeenCalledOnce()
    view.close()
    view.source.emit('message', { ...initial, progress: '迟到的片段' }); vi.runOnlyPendingTimers()
    expect(view.onTask).toHaveBeenCalledOnce()
  })
})

it('keeps observing a long task across healthy stream rotations without exhausting failure retries', () => {
  const view = setup()
  for (let i = 1; i <= 6; i++) {
    Source.all.at(-1)?.emit('snapshot', { ...identity, task: { ...initial, progress: `片段 ${i}` } }, `${i}-0`)
    vi.advanceTimersByTime(16)
    Source.all.at(-1)?.onerror?.()
    vi.advanceTimersByTime(1000)
  }
  expect(Source.all).toHaveLength(7)
  expect(view.onLost).not.toHaveBeenCalled()
  expect(view.onTask).toHaveBeenLastCalledWith(expect.objectContaining({ progress: '片段 6' }))
  view.close()
})

it('exhausts consecutive outages even if queued HTTP snapshots precede unavailable events', () => {
  const onLost = vi.fn()
  const stop = observePrivateTranslation({ ...initial, status: 'queued' }, { onTask: vi.fn(), onLost })
  for (let i = 0; i < 5; i++) {
    Source.all.at(-1)?.emit('snapshot', { ...identity, task: { ...initial, status: 'queued' } })
    Source.all.at(-1)?.emit('unavailable', identity)
    vi.runOnlyPendingTimers()
  }
  expect(onLost).toHaveBeenCalledOnce()
  expect(Source.all).toHaveLength(4)
  stop()
})

it('retains the observed draft on incomplete output without turning it into a saved result', () => {
  const view = setup()
  view.source.emit('snapshot', { ...identity, task: { ...initial, progress: '已收到的部分译文' } }, '1-0')
  view.source.emit('terminal', { ...identity, task: { ...initial, status: 'failed', error_code: 'incomplete_response' } }, '2-0')
  expect(view.onTask).toHaveBeenLastCalledWith(expect.objectContaining({
    status: 'failed', progress: '已收到的部分译文', result: null,
  }))
  expect(view.source.close).toHaveBeenCalled()
})

it('clears the observed draft when failure may involve authorization or content revision', () => {
  const view = setup()
  view.source.emit('snapshot', { ...identity, task: { ...initial, progress: '旧版本私有译文' } }, '1-0')
  view.source.emit('terminal', { ...identity, task: { ...initial, status: 'failed', error_code: 'translation_failed' } }, '2-0')
  expect(view.onTask).toHaveBeenLastCalledWith(expect.objectContaining({ progress: '', result: null }))
})
