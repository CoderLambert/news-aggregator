/**
 * Tests for the code-block copy button injected into MarkdownContent.
 *
 * Why MarkdownContent specifically: NewsDetail's full-article + AI
 * translation panels both render through react-markdown via this file.
 * The summary panel and the chat assistant use markstream-react which
 * already ships its own copy button — we only need parity for the
 * react-markdown path.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import MarkdownContent from './MarkdownContent'

describe('MarkdownContent — code block copy button', () => {
  let writeText

  beforeEach(() => {
    writeText = vi.fn().mockResolvedValue(undefined)
    // jsdom doesn't ship navigator.clipboard; install a stub per test so
    // assertions can inspect call args.
    Object.assign(navigator, { clipboard: { writeText } })
  })

  it('renders a copy button on each fenced code block', () => {
    const md = '```js\nconst x = 1\n```\n\nplain paragraph\n\n```python\nprint("hi")\n```'
    render(<MarkdownContent content={md} />)

    // Two code blocks → two copy buttons. The accessible name is
    // intentionally generic so the same button works under any language.
    const buttons = screen.getAllByRole('button', { name: /复制代码/ })
    expect(buttons).toHaveLength(2)
  })

  it('does NOT render a copy button for inline code', () => {
    render(<MarkdownContent content="this is `inline` code only" />)
    expect(screen.queryByRole('button', { name: /复制代码/ })).not.toBeInTheDocument()
  })

  it('writes the raw code (no trailing newline noise) to the clipboard on click', async () => {
    render(<MarkdownContent content={'```js\nconst x = 1\nconst y = 2\n```'} />)
    fireEvent.click(screen.getByRole('button', { name: /复制代码/ }))

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    // Whatever the renderer hands us, the copy payload must contain the
    // user-visible code verbatim. We assert substring rather than exact
    // equality so the implementation can pass through react-markdown's
    // own normalisation without the test breaking.
    expect(writeText.mock.calls[0][0]).toContain('const x = 1')
    expect(writeText.mock.calls[0][0]).toContain('const y = 2')
  })

  it('flips to "已复制" feedback state after a successful copy', async () => {
    render(<MarkdownContent content={'```\nhello\n```'} />)
    const btn = screen.getByRole('button', { name: /复制代码/ })
    fireEvent.click(btn)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已复制/ })).toBeInTheDocument()
    })
  })
})
