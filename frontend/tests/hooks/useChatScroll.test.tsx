import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useChatScroll } from '@/hooks/useChatScroll'
import type { ChatMessage } from '@/services/newsWorkflowApi'
import type { ChatPhase } from '@/hooks/useChat'

const history: ChatMessage[] = [
  { role: 'user', content: 'First question' },
  { role: 'assistant', content: 'First answer' },
]

function setup() {
  const geometry = { height: 1600, top: 0 }
  const element = document.createElement('div')
  Object.defineProperties(element, {
    scrollHeight: { get: () => geometry.height },
    clientHeight: { get: () => 400 },
    scrollTop: { get: () => geometry.top, set: value => { geometry.top = Math.min(value, geometry.height - 400) } },
  })
  const hook = renderHook(({ messages, phase, open }) => useChatScroll(messages, phase, open), {
    initialProps: { messages: [] as ChatMessage[], phase: 'loading-history' as ChatPhase, open: true },
  })
  hook.result.current.scrollRef.current = element
  hook.rerender({ messages: history, phase: 'idle', open: true })
  const scroll = (top: number) => {
    geometry.top = top
    act(() => hook.result.current.onScroll({ currentTarget: element } as never))
  }
  return { ...hook, geometry, scroll }
}

describe('conversation scrolling', () => {
  it('opens saved history at the bottom and follows streamed replies', () => {
    const { geometry, rerender } = setup()
    expect(geometry.top).toBe(1200)
    geometry.height = 1800
    rerender({ messages: [...history, { role: 'assistant', content: 'More text' }], phase: 'streaming', open: true })
    expect(geometry.top).toBe(1400)
  })

  it('keeps an earlier message visible through repeated chunks, completion and draft rerenders', () => {
    const { geometry, rerender, scroll } = setup()
    scroll(600)
    for (let i = 0; i < 10; i++) {
      geometry.height += 100
      rerender({ messages: [...history, { role: 'assistant', content: 'Streamed '.repeat(i + 1) }], phase: 'streaming', open: true })
      expect(geometry.top).toBe(600)
    }
    rerender({ messages: [...history], phase: 'success', open: true })
    rerender({ messages: [...history], phase: 'idle', open: true })
    expect(geometry.top).toBe(600)
  })

  it('resumes following when the reader returns to the bottom', () => {
    const { geometry, rerender, scroll } = setup()
    scroll(500)
    scroll(1200)
    geometry.height += 200
    rerender({ messages: [...history], phase: 'streaming', open: true })
    expect(geometry.top).toBe(1400)
  })

  it('shows a newly submitted question even when the reader was looking back', () => {
    const { geometry, rerender, scroll } = setup()
    scroll(500)
    geometry.height += 200
    rerender({ messages: [...history, { role: 'user', content: 'Second question' }, { role: 'assistant', content: '' }], phase: 'thinking', open: true })
    expect(geometry.top).toBe(1400)
  })

  it('honors an upward wheel gesture before the next streamed chunk arrives', () => {
    const { result, geometry, rerender } = setup()
    act(() => result.current.onWheel({ deltaY: -200 } as never))
    geometry.height += 200
    rerender({ messages: [...history], phase: 'streaming', open: true })
    expect(geometry.top).toBe(1200)
  })

  it('opens the latest messages after closing and reopening the panel', () => {
    const { geometry, rerender, scroll } = setup()
    scroll(500)
    rerender({ messages: history, phase: 'idle', open: false })
    rerender({ messages: history, phase: 'idle', open: true })
    expect(geometry.top).toBe(1200)
  })
})
