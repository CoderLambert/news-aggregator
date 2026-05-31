/**
 * ChatInput auto-grow behavior + scrollbar styling.
 *
 * Requirements:
 *  - Textarea auto-grows with content
 *  - Caps at 5 lines on mobile (≤640px viewport)
 *  - Beyond cap → vertical scroll (no horizontal overflow, no clipping)
 *  - Scrollbar styled (thin, brand-neutral, not default chrome)
 */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ChatInput from './ChatInput'

beforeEach(() => {
  // jsdom doesn't compute layout — stub scrollHeight so auto-grow logic is testable
  Object.defineProperty(HTMLTextAreaElement.prototype, 'scrollHeight', {
    configurable: true,
    get() {
      // Roughly emulate: scrollHeight = (lineCount) * 20 + 16 (padding)
      const lines = (this.value || '').split('\n').length
      return lines * 20 + 16
    },
  })
})

function setup(value = '') {
  const onChange = vi.fn()
  const onSend = vi.fn()
  const utils = render(
    <ChatInput value={value} onChange={onChange} onSend={onSend} isLoading={false} />,
  )
  const textarea = screen.getByLabelText('输入聊天问题')
  return { ...utils, textarea, onChange, onSend }
}

describe('ChatInput auto-grow', () => {
  it('starts at single-row height', () => {
    const { textarea } = setup('')
    // rows attr stays as the base hint
    expect(textarea).toHaveAttribute('rows', '1')
  })

  it('grows the textarea height as value gets multiline', () => {
    const { textarea, rerender, onChange } = setup('one line')
    const initialHeight = textarea.style.height

    // re-render with multiline value — component should resize via useEffect
    rerender(
      <ChatInput
        value={'l1\nl2\nl3'}
        onChange={onChange}
        onSend={() => {}}
        isLoading={false}
      />,
    )
    expect(textarea.style.height).not.toBe(initialHeight)
    // Should have been set to a pixel value
    expect(textarea.style.height).toMatch(/\d+px/)
  })

  it('caps height at 5 lines and enables scrolling beyond that', () => {
    const tenLines = Array.from({ length: 10 }, (_, i) => `line ${i}`).join('\n')
    const { textarea } = setup(tenLines)

    // 5 lines × 20 + 16 padding = 116px max
    const heightPx = parseInt(textarea.style.height, 10)
    expect(heightPx).toBeLessThanOrEqual(120) // small slack for rounding
    expect(heightPx).toBeGreaterThan(80) // but actually grew past 1 row
    // overflow should be scrollable, not hidden
    expect(textarea.style.overflowY).toBe('auto')
  })

  it('applies a custom scrollbar class (thin styled scrollbar)', () => {
    const { textarea } = setup('text')
    expect(textarea.className).toMatch(/chat-input-scroll/)
  })

  it('still sends on Enter (no Shift) regardless of multiline content', () => {
    const { textarea, onSend } = setup('hello')
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false })
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  it('allows newline on Shift+Enter without sending', () => {
    const { textarea, onSend } = setup('hello')
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true })
    expect(onSend).not.toHaveBeenCalled()
  })
})
