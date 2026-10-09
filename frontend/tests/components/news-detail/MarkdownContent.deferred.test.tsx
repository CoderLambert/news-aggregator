import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const richContent = vi.hoisted(() => ({
  highlight: vi.fn(async () => '<pre class="shiki"><code>highlighted</code></pre>'),
  mermaidRender: vi.fn(async () => ({ svg: '<svg><text>diagram</text></svg>' })),
}))

vi.mock('@/lib/shiki', () => ({
  normalizeShikiLanguage: (language: string) => language || 'text',
  highlightCode: richContent.highlight,
}))
vi.mock('mermaid', () => ({
  default: { initialize: vi.fn(), render: richContent.mermaidRender },
}))

import MarkdownContent from '@/components/news-detail/MarkdownContent'

const observerCallbacks: IntersectionObserverCallback[] = []

class MockIntersectionObserver {
  constructor(callback: IntersectionObserverCallback) { observerCallbacks.push(callback) }
  observe() {}
  disconnect() {}
}

beforeEach(() => {
  observerCallbacks.length = 0
  richContent.highlight.mockClear()
  richContent.mermaidRender.mockClear()
  vi.stubGlobal('IntersectionObserver', MockIntersectionObserver)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function enterPreloadMargin(index = 0) {
  act(() => {
    observerCallbacks[index]?.(
      [{ isIntersecting: true } as IntersectionObserverEntry],
      {} as IntersectionObserver,
    )
  })
}

describe('MarkdownContent deferred rich rendering', () => {
  it('starts syntax highlighting only when the code block is near the viewport', async () => {
    render(<MarkdownContent content={'```js\nconst ready = true\n```'} />)
    expect(richContent.highlight).not.toHaveBeenCalled()

    enterPreloadMargin()

    await waitFor(() => expect(richContent.highlight).toHaveBeenCalledTimes(1))
  })

  it('keeps Mermaid unloaded until its placeholder is near the viewport', async () => {
    render(<MarkdownContent content={'```mermaid\ngraph TD\n  A --> B\n```'} />)
    expect(screen.getByText('滚动到附近时渲染图表')).not.toBeNull()
    expect(richContent.mermaidRender).not.toHaveBeenCalled()

    enterPreloadMargin()

    await waitFor(() => expect(richContent.mermaidRender).toHaveBeenCalledTimes(1))
  })
})
