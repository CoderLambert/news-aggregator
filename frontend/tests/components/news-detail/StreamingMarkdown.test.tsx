import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import StreamingMarkdown from '@/components/news-detail/StreamingMarkdown'

Element.prototype.scrollTo = vi.fn()

describe('streaming Markdown', () => {
  it('keeps completed blocks and renders a growing table and incomplete code fence', async () => {
    const content = '## 概述\n\n| 项目 | 结果 |\n| --- | --- |\n| 翻译 | 进行中 |\n\n```js\nconst value = 1'
    const view = render(<StreamingMarkdown content={content} />)
    const heading = screen.getByRole('heading', { name: '概述' })
    expect(screen.getByRole('table')).toHaveTextContent('进行中')
    expect(view.container.querySelector('pre code')).toHaveTextContent('const value = 1')
    view.rerender(<StreamingMarkdown content={content + '\n```\n\n新的段落'} />)
    expect(screen.getByRole('heading', { name: '概述' })).toBe(heading)
    expect(await screen.findByText((_, element) => element?.tagName === 'P' && element.textContent === '新的段落')).toBeInTheDocument()
  })

  it('does not render raw HTML or executable links from model output', async () => {
    let view!: ReturnType<typeof render>
    await act(async () => { view = render(<StreamingMarkdown content={'<script>alert(1)</script>\n\n<iframe src="https://example.com"></iframe>\n\n[危险链接](javascript:alert%281%29)'} />) })
    expect(view.container.querySelector('script, iframe')).toBeNull()
    expect(view.container.querySelector('a[href^="javascript:"]')).toBeNull()
  })
})
